from rm_workflow.stages.repositories import StageRepository
from rm_workflow.validation.category_schemas import (
    GraphValidationError,
    validate_node_data,
)
from rm_workflow.workflows.models import WorkflowVersion


class GraphService:
    """
    Pure validator/normalizer for a single stage's `{"nodes": [...], "edges":
    [...]}` graph JSON (§9). No DB access -- StageService (below) is what
    composes this with StageRepository to actually read/write a Stage's
    graph.

    Structural integrity (an edge's source/target must reference a node id
    present in the SAME document) is checked here because nodes and edges
    live in the same per-stage JSON blob -- there's no cross-stage graph to
    reason about (§9).
    """

    def validate(self, graph: dict) -> dict:
        if not isinstance(graph, dict):
            raise GraphValidationError(
                "graph must be an object with 'nodes' and 'edges'"
            )

        nodes = graph.get("nodes", [])
        edges = graph.get("edges", [])
        if not isinstance(nodes, list) or not isinstance(edges, list):
            raise GraphValidationError("'nodes' and 'edges' must both be arrays")

        node_ids: set[str] = set()
        for node in nodes:
            node_id = node.get("id")
            if not node_id:
                raise GraphValidationError("Every node requires an 'id'")
            if node_id in node_ids:
                raise GraphValidationError(f"Duplicate node id '{node_id}'")
            node_ids.add(node_id)
            validate_node_data(
                node.get("data", {}).get("category"), node.get("data", {})
            )

        edge_ids: set[str] = set()
        for edge in edges:
            edge_id = edge.get("id")
            if not edge_id:
                raise GraphValidationError("Every edge requires an 'id'")
            if edge_id in edge_ids:
                raise GraphValidationError(f"Duplicate edge id '{edge_id}'")
            edge_ids.add(edge_id)

            source, target = edge.get("source"), edge.get("target")
            if source not in node_ids:
                raise GraphValidationError(
                    f"Edge '{edge_id}' references unknown source node '{source}'"
                )
            if target not in node_ids:
                raise GraphValidationError(
                    f"Edge '{edge_id}' references unknown target node '{target}'"
                )

        return {"nodes": nodes, "edges": edges}


class StageServiceError(Exception):
    """Not-found / lookup errors for stages -- kept distinct from
    GraphValidationError, which is specifically for malformed graph content
    (400) rather than a missing resource (404). api/views.py maps the two
    to different HTTP statuses."""


class StageService:
    """
    Stage CRUD + the dedicated graph write path (§10). Metadata edits
    (name/description/order) and graph edits are two separate methods on
    purpose -- update_metadata() never touches `graph`, update_graph() never
    touches metadata, matching the two independent write paths the API
    exposes (PATCH .../stages/{id} vs PUT .../stages/{id}/graph).
    """

    def __init__(self):
        self.stages = StageRepository()
        self.graph = GraphService()

    def list_stages(self, tenant_id: str, workflow_version: WorkflowVersion):
        return self.stages.list_for_version(tenant_id, workflow_version)

    def get_stage(
        self, tenant_id: str, workflow_version: WorkflowVersion, public_id: str
    ):
        stage = self.stages.get_by_public_id(tenant_id, workflow_version, public_id)
        if stage is None:
            raise StageServiceError("Stage not found")
        return stage

    def create_stage(
        self,
        tenant_id: str,
        workflow_version: WorkflowVersion,
        name: str,
        description: str = "",
        order: int | None = None,
        graph: dict | None = None,
    ):
        validated_graph = self.graph.validate(graph or {"nodes": [], "edges": []})
        return self.stages.create(
            tenant_id=tenant_id,
            workflow_version=workflow_version,
            name=name,
            description=description,
            order=order,
            graph=validated_graph,
        )

    def update_metadata(self, stage, **fields):
        return self.stages.update_metadata(stage, **fields)

    def update_graph(self, stage, graph: dict):
        validated_graph = self.graph.validate(graph)
        return self.stages.update_graph(stage, validated_graph)

    def delete_stage(self, stage) -> None:
        self.stages.soft_delete(stage)
