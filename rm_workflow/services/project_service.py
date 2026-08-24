from django.db import transaction
from drf_base_app.audit.context import AuditContext
from rm_auth_tenant.authorization.access_scope import EntityAccessService

from rm_workflow.projects.repositories import ProjectRepository
from rm_workflow.workspaces.repositories import WorkspaceRepository


class ProjectServiceError(Exception):
    pass


class ProjectService:
    """Tenant-scoped CRUD for project containers."""

    def __init__(self):
        self.projects = ProjectRepository()
        self.workspaces = WorkspaceRepository()

    def _require_workspace(self, tenant_id: str, workspace_public_id: str):
        workspace = self.workspaces.get_by_public_id(tenant_id, workspace_public_id)
        if workspace is None:
            raise ProjectServiceError("Workspace not found")
        return workspace

    def list_projects(self, tenant_id: str, workspace_public_id: str | None = None):
        if workspace_public_id is not None:
            workspace_public_id = self._require_workspace(
                tenant_id, workspace_public_id
            ).public_id
        projects = self.projects.list(tenant_id, workspace_public_id)
        print(f"ProjectService.list_projects: tenant_id={tenant_id}, workspace_public_id={workspace_public_id}, projects={projects}")
        return projects

    def get_project(self, tenant_id: str, public_id: str):
        project = self.projects.get_by_public_id(tenant_id, public_id)
        if project is None:
            raise ProjectServiceError("Project not found")
        return project

    @transaction.atomic
    def create_project(
        self, tenant_id: str, workspace_public_id: str, name: str, description: str = ""
    ):
        workspace = self._require_workspace(tenant_id, workspace_public_id)
        project = self.projects.create(tenant_id, workspace, name, description)
        creator_id = AuditContext.get_user()
        if creator_id is not None:
            EntityAccessService().grant_owner(
                tenant_id, "project", project.public_id, creator_id
            )
        return project

    def update_project(self, tenant_id: str, public_id: str, **fields):
        return self.projects.update(self.get_project(tenant_id, public_id), **fields)

    def delete_project(self, tenant_id: str, public_id: str) -> None:
        self.projects.soft_delete(self.get_project(tenant_id, public_id))
