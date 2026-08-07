from django.db import transaction

from drf_base_app.audit.context import AuditContext
from rm_auth_tenant.authorization.access_scope import EntityAccessService
from rm_workflow.workspaces.repositories import WorkspaceRepository


class WorkspaceServiceError(Exception):
    pass


class WorkspaceService:
    """
    Plain tenant-scoped CRUD -- no owner_id/scoping params here anymore.
    Object-level "who can see/act on which workspace" is handled entirely
    upstream of this service now, by RMScopedModelViewSet's
    TenantAndAccessScopedFilterBackend (list/queryset scoping) and
    RequiresPermission.has_object_permission (single-object scoping),
    both backed by EntityAccessGrant -- see rm_auth_tenant's
    authorization/DESIGN.md for why this replaced the earlier owner_id=
    kwarg threaded through every method here. By the time a call reaches
    this service, the caller has already been cleared to act on this
    specific workspace_public_id (or the queryset was already scoped before
    get_workspace's public_id lookup ran against it).
    """

    def __init__(self):
        self.workspaces = WorkspaceRepository()

    def list_workspaces(self, tenant_id: str):
        return self.workspaces.list(tenant_id)

    def get_workspace(self, tenant_id: str, public_id: str):
        workspace = self.workspaces.get_by_public_id(tenant_id, public_id)
        if workspace is None:
            raise WorkspaceServiceError("Workspace not found")
        return workspace

    @transaction.atomic
    def create_workspace(self, tenant_id: str, name: str, description: str = ""):
        workspace = self.workspaces.create(
            tenant_id, name=name, description=description
        )
        # Makes the creator the workspace's `owner` EntityAccessGrant --
        # this, not created_by, is what every subsequent scoped read/write
        # checks. Same transaction as the workspace row itself.
        creator_id = AuditContext.get_user()
        if creator_id is not None:
            EntityAccessService().grant_owner(
                tenant_id, "workspace", workspace.public_id, creator_id
            )
        return workspace

    def update_workspace(self, tenant_id: str, public_id: str, **fields):
        workspace = self.get_workspace(tenant_id, public_id)
        return self.workspaces.update(workspace, **fields)

    def delete_workspace(self, tenant_id: str, public_id: str) -> None:
        workspace = self.get_workspace(tenant_id, public_id)
        self.workspaces.soft_delete(workspace)
