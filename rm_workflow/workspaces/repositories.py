from rm_workflow.workspaces.models import Workspace


class WorkspaceRepository:
    """
    The only place in rm_workflow allowed to issue queries against
    Workspace. Services call this; api/views.py never imports Workspace
    directly (import-linter contract, §14).
    """

    def get_by_public_id(self, tenant_id: str, public_id: str) -> Workspace | None:
        return Workspace.objects.filter(tenant_id=tenant_id, public_id=public_id).first()

    def get_by_id(self, tenant_id: str, workspace_id: int) -> Workspace | None:
        return Workspace.objects.filter(tenant_id=tenant_id, id=workspace_id).first()

    def list(self, tenant_id: str):
        return Workspace.objects.filter(tenant_id=tenant_id).order_by("name")

    def create(self, tenant_id: str, name: str, description: str = "") -> Workspace:
        return Workspace.objects.create(
            tenant_id=tenant_id, name=name, description=description
        )

    def update(self, workspace: Workspace, **fields) -> Workspace:
        for field, value in fields.items():
            setattr(workspace, field, value)
        workspace.save(update_fields=list(fields))
        return workspace

    def soft_delete(self, workspace: Workspace) -> None:
        workspace.delete()  # RMSoftDeleteModel override -- sets deleted_at, no real DELETE
