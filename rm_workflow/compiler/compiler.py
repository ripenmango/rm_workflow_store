"""
The Compiler (architecture doc §41.1/§41.2): translates a published
WorkflowVersion's Stage graphs -- each Stage.graph is frontend-shaped,
per-stage {"nodes": [...], "edges": [...]} JSON (§7, and see
stages.models.Stage's own docstring on why edges can't cross stages) --
into one flattened, engine-ready `runtime_dsl` document, persisted as a
CompiledVersion (compiled_versions/models.py).

Sprint 1 scope (architecture doc §42): flatten already-valid per-Stage
graphs into one execution graph, resolve each node's `nodeType` against the
existing Node Registry (rm_workflow.node_types), and resolve any
`connectionId` a node's config carries against rm_connection_manager's
connection *definitions* only (never credentials -- §30). Node/edge-level
*content* validation (structural integrity, per-category schema) already
happened at write time via GraphService (§41's "Ground truth" correction),
so the Compiler does not re-validate that -- it only does what a from-write
validator structurally cannot: reason about the graph *across* stages, and
resolve references into other apps' registries.

Which node type prefixes compile is a settings-driven allow-list
(RM_WORKFLOW.ALLOWED_NODE_TYPE_PREFIXES, see conf.py and
UnsupportedNodeTypeError below), not a hardcoded check -- Sprint 1
hardcoded it to `core.*` only, since no Plugin Registry (§12) existed yet
to resolve connector types against. Sprint 5 replaces that hardcoded
check with the settings-driven allow-list (default `["*"]`) once a real
connector (rm_connector_demo) exists to prove the path end-to-end -- the
Worker-side Plugin Registry (§12) this docstring used to describe as a
blocker is still Sprint 7+ work (see rm_worker_sdk.plugin.registry's own
docstring), but it turned out not to be a prerequisite for the Compiler
to stop hardcoding `core.` as the only allowed prefix.

Cross-stage transitions -- two mechanisms, resolved into plain edges here
(architecture doc §41.1):

  1. Implicit linear chaining (the default): every node with no outgoing
     edge in Stage N ("exit node") gets an implicit edge to every node
     with no incoming edge in Stage N+1 ("entry node"), in `order`.

  2. Explicit stage jump: a node's `config` may carry a `branches` map,
     `{when_label: target_stage_public_id}` (e.g. a `core.condition` node
     with `{"true": "stg_approved", "false": "stg_rejected"}`). This MUST
     be resolved into concrete node-to-node edges here, at compile time --
     rm_workflow_engine only ever reads the flattened runtime_dsl and has
     no concept of "Stage" at all (§41.3/§41.4), so "jump to Stage X" isn't
     something that can be deferred to the Engine; the Compiler is the
     only place that still knows Stage boundaries exist. A node with an
     explicit `branches` map fully owns its own outgoing routing and is
     excluded from mechanism 1's implicit "exit node" set for that stage,
     so it never *also* picks up an unconditioned edge to the literal next
     stage in `order` on top of its explicit, conditioned ones. Target
     stages are resolved by `Stage.public_id` against this same
     WorkflowVersion's own Stage set.

     **Forward-only, by policy decision:** a branch may only target a
     Stage with a strictly greater `order` than the branching node's own
     stage -- targeting the same or an earlier Stage is a
     BackwardStageJumpError, not a silently-accepted edge. Restarting a
     workflow from the beginning, or any other intentional backward
     transition, is a separate, explicit, manually-triggered operation
     (e.g. re-invoking the workflow), never something the compiled graph
     itself encodes -- allowing a branch to point backward would let a
     single published version compile into a graph with a cycle in it,
     which the Engine has no bounded-loop construct to execute safely
     (unlike §40.7's node-level Loop, there is no Stage-level equivalent),
     so it's rejected outright rather than deferred as an open question.

Deliberately its own module, not a method on WorkflowVersionRepository or
VersionService: per §41.1, translating a nested per-stage node/edge graph
into a single flat execution DSL is a real algorithm (entry/exit detection,
cross-stage reference resolution, node-type resolution against rm_workflow's
own node-type registry) with its own test surface, not persistence logic --
it belongs in a class services/repositories can call, not folded into
either layer.
"""

from rm_workflow.node_types.repositories import NodeTypeRepository


class CompilationError(Exception):
    """
    Base class for every reason a WorkflowVersion's Stage graphs can't be
    compiled. Subclassed below (§41.1's own docstring predicted "likely one
    subclass per failure category, so VersionService.publish() can return a
    specific, actionable validation error rather than a generic 500") --
    now that there's a real algorithm that can fail in specific ways worth
    distinguishing.
    """


class UnknownNodeTypeError(CompilationError):
    """A node references a `data.nodeType` that isn't registered (or isn't
    active) in rm_workflow's own Node Registry for this tenant -- see
    node_types.repositories.NodeTypeRepository.get_by_type."""


class UnsupportedNodeTypeError(CompilationError):
    """
    A node references a real, registered, active node type whose prefix
    isn't in RM_WORKFLOW's ALLOWED_NODE_TYPE_PREFIXES (see conf.py).
    Sprint 1 hardcoded this to "core." only, since no Plugin Registry (§12)
    existed yet to resolve connector types against; Sprint 5 replaces that
    hardcoded check with a settings-driven allow-list (default ["*"], i.e.
    allow everything) now that a real connector (rm_connector_demo) exists
    to prove the path end-to-end. Publishing a workflow that uses a
    disallowed node type still fails loudly here rather than silently
    producing a runtime_dsl the Engine can't execute.
    """


class UnresolvedConnectionError(CompilationError):
    """
    A node's `connectionId` (in its `config`) doesn't resolve to a
    Connection the tenant can see, or that Connection's provider has no
    active ConnectionDefinition (§41.1 point 3). Never raised for a
    missing/invalid credential -- credential resolution never happens at
    compile time, only at execution time inside rm_workflow_engine (§30).
    """


class UnknownStageError(CompilationError):
    """A node's explicit `branches` config (see module docstring, "Explicit
    stage jump") names a target Stage `public_id` that doesn't exist in
    this WorkflowVersion, or the `branches` value itself isn't a
    {str: str} mapping."""


class BackwardStageJumpError(CompilationError):
    """A node's `branches` config targets a Stage whose `order` is not
    strictly greater than the branching node's own Stage -- i.e. the same
    Stage, or an earlier one. Rejected outright (§41.1's "forward-only, by
    policy decision"): allowing this would let a compiled graph contain a
    cycle, and the Engine has no bounded-loop construct to run one safely.
    A workflow that needs to go backward (restart, rework, etc.) does so
    as an explicit, separate operation outside the compiled graph, not via
    a `branches` edge."""


def _qualified_id(stage, local_id: str) -> str:
    """
    Stage-qualified execution node/edge id (§7's "stable execution node
    IDs"). Node ids are only unique *within* a single Stage's own graph
    JSON (GraphService only checks uniqueness inside one document) -- two
    different stages can reuse the same local id, so the flattened,
    single-document runtime graph must qualify every id with its owning
    stage to stay collision-free.
    """
    return f"{stage.public_id}:{local_id}"


def _explicit_branches(compiled_node: dict) -> dict | None:
    """
    Returns the `{when_label: target_stage_public_id}` map from a compiled
    node's `config.branches`, or None if the node has no explicit stage
    jump configured. Raises UnknownStageError for a `branches` value that
    isn't a flat {str: str} mapping -- deliberately checked here rather
    than left to blow up on a `.items()` call somewhere less obvious.
    """
    branches = compiled_node["config"].get("branches")
    if branches is None:
        return None
    if not isinstance(branches, dict) or not all(
        isinstance(label, str) and isinstance(target, str)
        for label, target in branches.items()
    ):
        raise UnknownStageError(
            f"Node '{compiled_node['id']}' has a malformed `branches` config -- "
            "expected {when_label: target_stage_public_id}, both strings"
        )
    return branches or None  # an empty dict is the same as "no explicit branches"


class Compiler:
    """
    Flattens a WorkflowVersion's ordered Stage graphs into one Engine
    Runtime DSL document (§4A.2). Handed a `WorkflowVersion` model instance
    by the caller (CompiledVersionService) -- this class never queries for
    one itself, matching every other cross-model class in this repo being
    handed models rather than ids.
    """

    #: Bumped whenever compile()'s output shape changes -- stored on each
    #: CompiledVersion row (compiler_version) so a future Compiler change
    #: can identify which already-compiled rows need a one-time re-compile.
    version = "1.2.0"

    #: Hardcoded pending real node/plugin versioning (§40.7's semver
    #: decision is Sprint 4+ work, once real connector plugins exist to
    #: version against) -- every compiled node gets this same runtime
    #: version for now, since NodeType itself has no version field yet.
    NODE_VERSION = "1.0"

    #: Runtime DSL's own schema version (§4A.6) -- independent of
    #: Compiler.version, Workflow.version_number, and node/plugin versions.
    SCHEMA_VERSION = "1.0"

    def __init__(
        self,
        node_types=None,
        connections=None,
        connection_definitions=None,
        allowed_prefixes=None,
    ):
        self.node_types = node_types if node_types is not None else NodeTypeRepository()
        # Left unset by default and resolved lazily, per call, in
        # _resolve_connection() -- importing rm_connection's services at
        # call time (not module import time) means a Compiler that never
        # compiles a node with a `connectionId` (true of every node type
        # Sprint 1 actually seeds) never needs rm_connection's
        # settings/DB configured at all. Tests inject fakes here directly.
        self.connections = connections
        self.connection_definitions = connection_definitions
        # Same lazy-default pattern: reading rm_workflow_settings at
        # __init__ time (not module import time) would force every caller
        # to have Django settings configured just to construct a Compiler.
        # Injected directly by tests (e.g. allowed_prefixes=["core."]) to
        # exercise the restriction without a settings module at all.
        self._allowed_prefixes = allowed_prefixes

    @property
    def allowed_prefixes(self) -> list:
        if self._allowed_prefixes is None:
            from rm_workflow.conf import rm_workflow_settings

            self._allowed_prefixes = rm_workflow_settings.allowed_node_type_prefixes
        return self._allowed_prefixes

    def compile(self, workflow_version) -> dict:
        """
        Returns the flattened runtime_dsl dict for the given
        WorkflowVersion. Raises CompilationError (or a subclass) if the
        version's Stage graphs can't be compiled.
        """
        tenant_id = workflow_version.tenant_id
        stages = list(workflow_version.stages.all())  # Stage.Meta.ordering = ["order"]
        stage_by_public_id = {stage.public_id: stage for stage in stages}

        compiled_nodes: list[dict] = []
        compiled_edges: list[dict] = []
        stage_entry_ids: dict[int, list[str]] = {}
        stage_exit_ids: dict[int, list[str]] = {}
        # (source_stage, source_qualified_node_id, {when_label: target_stage_public_id})
        # -- resolved into edges only after every stage's entries are known
        # (a jump can target a stage this loop hasn't reached yet).
        pending_branches: list[tuple] = []

        for stage in stages:
            graph = stage.graph or {}
            nodes = graph.get("nodes", [])
            edges = graph.get("edges", [])
            local_ids = [node["id"] for node in nodes]

            targeted = {edge["target"] for edge in edges}
            sourced = {edge["source"] for edge in edges}

            branching_local_ids: set[str] = set()
            for node in nodes:
                compiled_node = self._compile_node(tenant_id, stage, node)
                compiled_nodes.append(compiled_node)
                branches = _explicit_branches(compiled_node)
                if branches:
                    branching_local_ids.add(node["id"])
                    pending_branches.append((stage, compiled_node["id"], branches))

            entries = [
                _qualified_id(stage, local_id)
                for local_id in local_ids
                if local_id not in targeted
            ]
            all_qualified = [_qualified_id(stage, local_id) for local_id in local_ids]
            stage_entry_ids[stage.id] = entries or all_qualified

            # Exit-node detection for the *implicit* linear chain only --
            # explicit branching nodes are never candidates, regardless of
            # whether they're structurally an exit within their own stage
            # (see module docstring, mechanism 2).
            non_branching_ids = [
                local_id for local_id in local_ids if local_id not in branching_local_ids
            ]
            exits = [
                local_id for local_id in non_branching_ids if local_id not in sourced
            ]
            # A stage that's entirely a cycle (every non-branching node
            # both sourced and targeted by some edge) has no structural
            # exit -- fall back to every non-branching node so the
            # implicit chain still has somewhere to attach, rather than
            # silently dropping the stage from it. Never falls back to a
            # branching node -- if every node in the stage branches
            # explicitly, this stage contributes nothing to the implicit
            # chain, which is correct: there's nothing left un-routed.
            stage_exit_ids[stage.id] = [
                _qualified_id(stage, local_id) for local_id in (exits or non_branching_ids)
            ]

            for edge in edges:
                compiled_edge = {
                    "source": _qualified_id(stage, edge["source"]),
                    "target": _qualified_id(stage, edge["target"]),
                }
                if "when" in edge:
                    compiled_edge["when"] = edge["when"]
                compiled_edges.append(compiled_edge)

        # Mechanism 1: implicit linear chaining, in `order` -- see module
        # docstring.
        for current_stage, next_stage in zip(stages, stages[1:]):
            for exit_id in stage_exit_ids[current_stage.id]:
                for entry_id in stage_entry_ids[next_stage.id]:
                    compiled_edges.append({"source": exit_id, "target": entry_id})

        # Mechanism 2: explicit stage jumps -- see module docstring.
        for source_stage, source_id, branches in pending_branches:
            for when_label, target_stage_public_id in branches.items():
                target_stage = stage_by_public_id.get(target_stage_public_id)
                if target_stage is None:
                    raise UnknownStageError(
                        f"Node '{source_id}' branch '{when_label}' targets unknown "
                        f"stage '{target_stage_public_id}'"
                    )
                if target_stage.order <= source_stage.order:
                    raise BackwardStageJumpError(
                        f"Node '{source_id}' branch '{when_label}' targets stage "
                        f"'{target_stage_public_id}' (order={target_stage.order}), which is "
                        f"not after its own stage '{source_stage.public_id}' "
                        f"(order={source_stage.order}) -- backward or same-stage jumps "
                        "aren't allowed (see BackwardStageJumpError)"
                    )
                for entry_id in stage_entry_ids[target_stage.id]:
                    compiled_edges.append(
                        {"source": source_id, "target": entry_id, "when": when_label}
                    )

        return {
            "schema_version": self.SCHEMA_VERSION,
            "workflow": {
                "id": workflow_version.workflow.public_id,
                "version": workflow_version.version_number,
            },
            "nodes": compiled_nodes,
            "edges": compiled_edges,
        }

    def _compile_node(self, tenant_id: str, stage, node: dict) -> dict:
        node_id = node.get("id")
        data = node.get("data") or {}
        type_key = data.get("nodeType")
        if not type_key:
            raise UnknownNodeTypeError(
                f"Stage '{stage.public_id}' node '{node_id}' has no `data.nodeType`"
            )

        node_type = self.node_types.get_by_type(tenant_id, type_key)
        if node_type is None or not node_type.is_active:
            raise UnknownNodeTypeError(
                f"Stage '{stage.public_id}' node '{node_id}' references unknown "
                f"or inactive node type '{type_key}'"
            )
        # NOTE: doesn't check this tenant's TenantNodeTypeSetting disabling
        # overrides (NodeTypeRepository.get_by_type() doesn't apply them --
        # only list_available() does, for the builder palette). Sprint 1
        # doesn't exercise per-tenant overrides on the core.* types; revisit
        # if a tenant ever disables one and still expects publish to reject it.
        allowed = self.allowed_prefixes
        if "*" not in allowed and not any(type_key.startswith(p) for p in allowed):
            raise UnsupportedNodeTypeError(
                f"Stage '{stage.public_id}' node '{node_id}' has type '{type_key}', "
                "whose prefix isn't in RM_WORKFLOW's ALLOWED_NODE_TYPE_PREFIXES "
                f"({sorted(allowed)}) -- see rm_workflow.conf."
            )

        config = dict(data.get("properties") or {})
        compiled = {
            "id": _qualified_id(stage, node_id),
            "type": type_key,
            "version": self.NODE_VERSION,
            "config": config,
        }

        # Convention for connector node types: a `connectionId` in
        # `properties` is a Connection's public_id, resolved here against
        # connection *definitions* only, never credentials (§30). First
        # exercised for real by rm_connector_demo's `demo.echo_with_connection`
        # (Sprint 5) -- see conf.py/UnsupportedNodeTypeError above for how
        # connector node types got past the Sprint 1 core.*-only gate.
        connection_id = config.get("connectionId")
        if connection_id:
            compiled["connection"] = {
                "id": self._resolve_connection(tenant_id, connection_id)
            }

        return compiled

    def _resolve_connection(self, tenant_id: str, connection_public_id: str) -> str:
        from rm_connection.services.connection_service import (
            ConnectionService,
            ConnectionServiceError,
        )
        from rm_connection.services.definition_service import (
            ConnectionDefinitionService,
            ConnectionDefinitionServiceError,
        )

        connections = (
            self.connections if self.connections is not None else ConnectionService()
        )
        try:
            connection = connections.get_connection(tenant_id, connection_public_id)
        except ConnectionServiceError as exc:
            raise UnresolvedConnectionError(str(exc)) from exc

        definitions = (
            self.connection_definitions
            if self.connection_definitions is not None
            else ConnectionDefinitionService()
        )
        try:
            definitions.get_active(connection.provider)
        except ConnectionDefinitionServiceError as exc:
            raise UnresolvedConnectionError(str(exc)) from exc

        return connection.public_id
