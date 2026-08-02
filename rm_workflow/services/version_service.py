from django.db import transaction

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
    """

    def __init__(self):
        self.workflows = WorkflowRepository()
        self.versions = WorkflowVersionRepository()
        self.stages = StageRepository()

    def list_versions(self, tenant_id: str, workflow: Workflow):
        return self.versions.list_for_workflow(tenant_id, workflow)

    def get_version(self, tenant_id: str, workflow: Workflow, public_id: str):
        version = self.versions.get_by_public_id(tenant_id, workflow, public_id)
        if version is None:
            raise VersionServiceError("Workflow version not found")
        return version

    @transaction.atomic
    def publish(self, tenant_id: str, workflow: Workflow):
        """
        Copy-on-publish (§5.2): create a NEW WorkflowVersion row and
        duplicate every Stage row from the workflow's current draft
        (`workflow.current_version`) onto it -- graph JSON copied as-is,
        no re-validation (it was already validated when it was written).
        The new version is then marked published and becomes the
        workflow's current_version.
        """
        draft = workflow.current_version
        if draft is None:
            raise VersionServiceError("Workflow has no current version to publish")

        draft_stages = list(self.stages.list_for_version(tenant_id, draft))

        new_version = self.versions.create_draft(tenant_id, workflow)
        self.stages.bulk_create(
            tenant_id,
            new_version,
            [
                {
                    "name": stage.name,
                    "description": stage.description,
                    "order": stage.order,
                    "graph": stage.graph,
                }
                for stage in draft_stages
            ],
        )
        self.versions.mark_published(new_version)
        self.workflows.set_current_version(workflow, new_version)
        return new_version
