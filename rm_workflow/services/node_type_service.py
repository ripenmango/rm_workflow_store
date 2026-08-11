from rm_workflow.node_types.repositories import NodeTypeRepository


class NodeTypeService:
    """Read-only by design -- see NodeType's model docstring for why
    writes (properties_schema edits, enable/disable overrides) go through
    Django admin instead of a service method here."""

    def __init__(self):
        self.node_types = NodeTypeRepository()

    def list_available(self, tenant_id: str):
        return self.node_types.list_available(tenant_id)
