from django.db import transaction

from rm_workflow.services.compiled_version_service import (
    CompiledVersionService,
    CompiledVersionServiceError,
)
from rm_workflow.stages.repositories import StageRepository
from rm_workflow.workflows.models import Workflow
from rm_workflow.workflows.repositories import WorkflowRepository, WorkflowVersionRepository


class VersionServiceError(Exception):
    pass


class VersionService:
    """
    Version listing + publish (§5.2, §10). Draft creation on its own
    (without a publish) is handled inline by WorkflowService at workflow
    create-time -- this service owns the publish operation specifically,
    since it's the one that fans out into Stage duplication.

    Publish is compile-on-publish as of Sprint 1 (§41.1/§42): copying Stage
    rows onto the new version and compiling them into a CompiledVersion
    happen in the same @transaction.atomic block below, so a published
    WorkflowVersion always has a matching, engine-ready runtime_dsl -- a
    CompilationError aborts the publish entirely rather than leaving a
    published version with no compiled output.
    """

    def __init__(self):
        self.workflows = WorkflowRepository()
        self.versions = WorkflowVersionRepository()
        self.stages = StageRepository()
        self.compiled_versions = CompiledVersionService()

    def list_versions(self, tenant_id: str, workflow: Workflow):
        return self.versions.list_for_workflow(tenant_id, workflow)

    def get_version(self, tenant_id: str, workflow: Workflow, public_id: str):
        version = self.versions.get_by_public_id(tenant_id, workflow, public_id)
        if version is None:
            raise VersionServiceError("Workflow version not found")
        return version

    def get_latest_published(self, tenant_id: str, workflow: Workflow):
        """
        What an execution start with no explicit version pin should
        actually run. Before create_new_draft() existed, `current_version`
        and "the latest published version" were always the same thing --
        the only way current_version ever changed was publish() itself, so
        it could never be a draft. That's no longer true: create_new_draft()
        can leave `current_version` pointing at a brand new, uncompiled
        draft while an older version is still published and perfectly
        runnable. rm_engine_app's ExecutionService._resolve_compiled_version
        calls this (not workflow.current_version) for exactly that reason --
        see its own docstring/comment for the bug this fixed (an active
        FormTrigger failing every submission the moment someone starts
        editing a published workflow again, with no new publish yet).
        """
        version = self.versions.get_latest_published(tenant_id, workflow)
        if version is None:
            raise VersionServiceError(
                f"Workflow '{workflow.public_id}' has never been published"
            )
        return version

    @transaction.atomic
    def publish(self, tenant_id: str, workflow: Workflow):
        """
        Copy-on-publish (§5.2): create a NEW WorkflowVersion row and
        duplicate every Stage row from the workflow's current draft
        (`workflow.current_version`) onto it -- graph JSON copied as-is,
        no re-validation (it was already validated when it was written).
        As of Sprint 1, publish also compiles the copied stages into a
        CompiledVersion (§41.1) before marking the version published --
        "copy-on-publish" is now "compile-on-publish". The new version is
        then marked published and becomes the workflow's current_version.
        """
        draft = workflow.current_version
        if draft is None:
            raise VersionServiceError("Workflow has no current version to publish")

        draft_stages = list(self.stages.list_for_version(tenant_id, draft))

        new_version = self.versions.create_draft(tenant_id, workflow)
        self.stages.bulk_create(
            tenant_id, new_version, self._stage_copy_dicts(draft_stages)
        )
        try:
            self.compiled_versions.compile_and_store(tenant_id, new_version)
        except CompiledVersionServiceError as exc:
            raise VersionServiceError(str(exc)) from exc

        self.versions.mark_published(new_version)
        self.workflows.set_current_version(workflow, new_version)
        return new_version

    @transaction.atomic
    def create_new_draft(self, tenant_id: str, workflow: Workflow):
        """
        The counterpart create_draft() operation publish() never left
        behind for getting back INTO edit mode: publish() always leaves
        `workflow.current_version` pointed at the just-published,
        immutable version (see CompiledVersion's own model docstring, and
        StageService's is_published guards -- Sprint 10 gap-fix), and
        nothing else in this codebase ever calls
        WorkflowVersionRepository.create_draft() except publish() itself
        and WorkflowService.create_workflow()'s very first draft. Without
        this method, a workflow that's ever been published has no way to
        become editable again.

        Copies every Stage from the workflow's CURRENT version onto a
        brand new `is_published=False` WorkflowVersion (same
        stage-duplication shape as publish(), via the same
        _stage_copy_dicts() helper -- just without the compile step, since
        an unpublished draft has no CompiledVersion until IT'S published),
        and makes that new draft the workflow's current_version. An
        explicit, deliberate action (not auto-triggered by the first stage
        edit after a publish) -- see the API view's own docstring for why.

        Refuses if the current version is already a draft -- there's
        nothing published to fork from, and the caller should just keep
        editing what they have.
        """
        current = workflow.current_version
        if current is None:
            raise VersionServiceError("Workflow has no current version to fork")
        if not current.is_published:
            raise VersionServiceError(
                "The current version is already a draft -- keep editing it directly"
            )

        current_stages = list(self.stages.list_for_version(tenant_id, current))
        new_draft = self.versions.create_draft(tenant_id, workflow)
        self.stages.bulk_create(
            tenant_id, new_draft, self._stage_copy_dicts(current_stages)
        )
        self.workflows.set_current_version(workflow, new_draft)
        return new_draft

    @staticmethod
    def _stage_copy_dicts(stages) -> list[dict]:
        """Shared by publish() and create_new_draft() -- both duplicate a
        version's stages onto a brand new WorkflowVersion the exact same
        way; kept in one place so a future new stage attribute only needs
        to be added to the copy here once, not in each caller."""
        return [
            {
                "name": stage.name,
                "description": stage.description,
                "order": stage.order,
                "graph": stage.graph,
                "required_form_id": stage.required_form_id,
            }
            for stage in stages
        ]
