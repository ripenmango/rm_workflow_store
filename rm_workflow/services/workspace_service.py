from rm_workflow.workspaces.repositories import WorkspaceRepository


class WorkspaceServiceError(Exception):
    pass


class WorkspaceService:
    def __init__(self):
        self.workspaces = WorkspaceRepository()

    def list_workspaces(self, tenant_id: str):
        return self.workspaces.list(tenant_id)

    def get_workspace(self, tenant_id: str, public_id: str):
        workspace = self.workspaces.get_by_public_id(tenant_id, public_id)
        if workspace is None:
            raise WorkspaceServiceError("Workspace not found")
        return workspace

    def create_workspace(self, tenant_id: str, name: str, description: str = ""):
        return self.workspaces.create(tenant_id, name=name, description=description)

    def update_workspace(self, tenant_id: str, public_id: str, **fields):
        workspace = self.get_workspace(tenant_id, public_id)
        return self.workspaces.update(workspace, **fields)

    def delete_workspace(self, tenant_id: str, public_id: str) -> None:
        workspace = self.get_workspace(tenant_id, public_id)
        self.workspaces.soft_delete(workspace)
