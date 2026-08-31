from django.db import transaction
from drf_base_app.audit.context import AuditContext
from rm_auth_tenant.authorization.access_scope import EntityAccessService

from rm_workflow.projects.repositories import ProjectRepository
from rm_workflow.services.graph_service import GraphService
from rm_workflow.stages.repositories import StageRepository
from rm_workflow.validation.category_schemas import GraphValidationError
from rm_workflow.workflows.repositories import (
    WorkflowRepository,
    WorkflowVersionRepository,
)
from rm_workflow.workspaces.repositories import WorkspaceRepository


class WorkflowServiceError(Exception):
    pass


class WorkflowService:
    """
    The entry point api/views.py calls for Workflow CRUD + first-time stage
    bootstrap (§10). update_workflow() only ever touches Workflow's own
    metadata (name/description) -- it never touches stage content, matching
    §5.1's "editing a workflow's name and editing a stage's canvas are two
    independent operations that can't race each other."

    Plain tenant-scoped queries only -- no owner_id/scoping params. Every
    method here assumes the caller has already been cleared to act on the
    specific workspace/workflow public_id it's given (RMScopedModelViewSet's
    filter backend + RequiresPermission.has_object_permission, both backed
    by EntityAccessGrant -- see rm_auth_tenant's authorization/DESIGN.md).
    """

    def __init__(self):
        self.workflows = WorkflowRepository()
        self.versions = WorkflowVersionRepository()
        self.workspaces = WorkspaceRepository()
        self.projects = ProjectRepository()
        self.stages = StageRepository()
        self.graph = GraphService()

    def _require_workspace(self, tenant_id: str, workspace_public_id: str):
        workspace = self.workspaces.get_by_public_id(tenant_id, workspace_public_id)
        if workspace is None:
            raise WorkflowServiceError("Workspace not found")
        return workspace

    def _require_project(self, tenant_id: str, project_public_id: str):
        project = self.projects.get_by_public_id(tenant_id, project_public_id)
        if project is None:
            raise WorkflowServiceError("Project not found")
        return project

    def list_workflows(
        self,
        tenant_id: str,
        workspace_public_id: str | None = None,
        project_public_id: str | None = None,
    ):
        resolved_workspace_public_id = None
        if workspace_public_id is not None:
            resolved_workspace_public_id = self._require_workspace(
                tenant_id, workspace_public_id
            ).public_id
        resolved_project_public_id = None
        if project_public_id is not None:
            resolved_project_public_id = self._require_project(
                tenant_id, project_public_id
            ).public_id
        return self.workflows.list(
            tenant_id,
            workspace_public_id=resolved_workspace_public_id,
            project_public_id=resolved_project_public_id,
        )

    def get_workflow(self, tenant_id: str, public_id: str):
        workflow = self.workflows.get_by_public_id(tenant_id, public_id)
        if workflow is None:
            raise WorkflowServiceError("Workflow not found")
        return workflow

    @transaction.atomic
    def create_workflow(
        self,
        tenant_id: str,
        workspace_public_id: str,
        name: str,
        description: str = "",
        stages: list[dict] | None = None,
        project_public_id: str | None = None,
    ):
        """
        Creates a Workflow + its first draft WorkflowVersion together. The
        optional `stages` argument is the create-time-only bootstrap
        allowance from §10: if present, every stage's graph is validated
        and all Stage rows are created against that draft version, in the
        same transaction as the Workflow/WorkflowVersion rows. This is NOT
        a general whole-document write path for later edits -- ongoing
        stage edits go through StageService (metadata) and
        StageService.update_graph() (graph), one stage at a time.
        """
        workspace = self._require_workspace(tenant_id, workspace_public_id)
        project = None
        if project_public_id is not None:
            project = self._require_project(tenant_id, project_public_id)
            if project.workspace_id != workspace.public_id:
                raise WorkflowServiceError(
                    "Project must belong to the workflow workspace"
                )

        workflow = self.workflows.create(
            tenant_id=tenant_id,
            workspace=workspace,
            project=project,
            name=name,
            description=description,
        )
        # Makes the creator this workflow's `owner` EntityAccessGrant, same
        # transaction as the workflow row itself -- see
        # WorkspaceService.create_workspace's identical pattern.
        creator_id = AuditContext.get_user()
        if creator_id is not None:
            EntityAccessService().grant_owner(
                tenant_id, "workflow", workflow.public_id, creator_id
            )

        draft = self.versions.create_draft(tenant_id, workflow)
        self.workflows.set_current_version(workflow, draft)

        if stages:
            bootstrap_stages = []
            for index, stage_data in enumerate(stages):
                try:
                    graph = self.graph.validate(
                        stage_data.get("graph") or {"nodes": [], "edges": []}
                    )
                except GraphValidationError as exc:
                    raise WorkflowServiceError(f"stages[{index}]: {exc}") from exc
                bootstrap_stages.append(
                    {
                        "name": stage_data["name"],
                        "description": stage_data.get("description", ""),
                        "order": stage_data.get("order", index),
                        "graph": graph,
                        # rm_form_store Architecture & Design doc SS18
                        # "Direction 2", this codebase's own Phase 5 --
                        # carried through bootstrap the same as every
                        # other stage attribute; absent from most bootstrap
                        # payloads (StageRepository.bulk_create defaults
                        # missing keys to None).
                        "required_form_id": stage_data.get("required_form_id"),
                    }
                )
            self.stages.bulk_create(tenant_id, draft, bootstrap_stages)

        return workflow

    def update_workflow(self, tenant_id: str, public_id: str, **fields):
        # Metadata/project membership only. Never touches stages.
        fields.pop("stages", None)
        workflow = self.get_workflow(tenant_id, public_id)
        if "project" in fields:
            project_public_id = fields["project"]
            if project_public_id is None:
                fields["project"] = None
            else:
                project = self._require_project(tenant_id, project_public_id)
                if project.workspace_id != workflow.workspace_id:
                    raise WorkflowServiceError(
                        "Project must belong to the workflow workspace"
                    )
                fields["project"] = project
        return self.workflows.update(workflow, **fields)

    def delete_workflow(self, tenant_id: str, public_id: str) -> None:
        workflow = self.get_workflow(tenant_id, public_id)
        self.workflows.soft_delete(workflow)
