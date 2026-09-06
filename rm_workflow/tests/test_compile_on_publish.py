"""
Sprint 1's stated test goal (architecture doc §42): publish a multi-stage
draft, assert the resulting runtime_dsl is a correctly flattened, single
graph. Exercised through the real public entry points
(WorkflowService.create_workflow + VersionService.publish), not by poking
Stage rows directly, so this also proves the wiring into publish() (§41.1)
actually works end to end, not just Compiler.compile() in isolation.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from drf_base_app.audit.context import AuditContext
from rm_workflow.compiled_versions.repositories import CompiledVersionRepository
from rm_workflow.compiler.compiler import Compiler
from rm_workflow.services.version_service import VersionService, VersionServiceError
from rm_workflow.services.workflow_service import WorkflowService
from rm_workflow.services.workspace_service import WorkspaceService
from rm_workflow.stages.repositories import StageRepository

TENANT_ID = "tenant-compiler-sprint1"


@pytest.fixture
def actor(db):
    """A real User row + an AuditContext bound to it -- create_workflow()/
    create_workspace() both grant an `owner` EntityAccessGrant to
    AuditContext.get_user(), and RMAuditModel.save() wants a created_by."""
    user = get_user_model().objects.create_user(
        tenant_id=TENANT_ID, username="compiler-sprint1-actor"
    )
    with AuditContext.use(user.id):
        yield user


@pytest.fixture
def core_node_types(db):
    """Sprint 1's core.* node types (seed_node_types.py) -- run directly so
    tests don't depend on the management command having been run against
    whatever database pytest-django spins up."""
    call_command("seed_node_types")


def _core_node(node_id, node_type, category, **properties):
    return {
        "id": node_id,
        "data": {"category": category, "nodeType": node_type, "properties": properties},
    }


def _two_stage_workflow(name="Two-stage workflow"):
    workspace = WorkspaceService().create_workspace(TENANT_ID, name=f"WS for {name}")
    return WorkflowService().create_workflow(
        tenant_id=TENANT_ID,
        workspace_public_id=workspace.public_id,
        name=name,
        stages=[
            {
                "name": "Stage 1",
                "graph": {
                    "nodes": [
                        _core_node("n1", "core.input", "input", source="form"),
                        _core_node("n2", "core.process", "process", operation="transform"),
                    ],
                    "edges": [{"id": "e1", "source": "n1", "target": "n2"}],
                },
            },
            {
                "name": "Stage 2",
                "graph": {
                    "nodes": [
                        _core_node("n1", "core.condition", "condition", expression="true"),
                    ],
                    "edges": [],
                },
            },
        ],
    )


@pytest.mark.django_db
def test_publish_compiles_and_flattens_a_multi_stage_draft(actor, core_node_types):
    workflow = _two_stage_workflow()

    version = VersionService().publish(TENANT_ID, workflow)

    compiled = CompiledVersionRepository().get_for_version(TENANT_ID, version)
    assert compiled is not None
    assert compiled.compiler_version == Compiler.version

    runtime_dsl = compiled.runtime_dsl
    assert runtime_dsl["schema_version"] == "1.0"
    assert runtime_dsl["workflow"] == {
        "id": workflow.public_id,
        "version": version.version_number,
    }

    stage1, stage2 = list(version.stages.all())  # Stage.Meta.ordering = ["order"]

    # Every node id is qualified with its owning stage, so two stages
    # reusing the local id "n1" don't collide in the flattened graph.
    node_by_id = {node["id"]: node for node in runtime_dsl["nodes"]}
    assert len(node_by_id) == 3
    assert f"{stage1.public_id}:n1" in node_by_id
    assert f"{stage1.public_id}:n2" in node_by_id
    assert f"{stage2.public_id}:n1" in node_by_id

    # node_type resolved through to the runtime type + a version stamp
    assert node_by_id[f"{stage1.public_id}:n2"]["type"] == "core.process"
    assert node_by_id[f"{stage1.public_id}:n2"]["version"] == Compiler.NODE_VERSION
    assert node_by_id[f"{stage1.public_id}:n2"]["config"] == {"operation": "transform"}

    edges = runtime_dsl["edges"]

    # The within-stage edge is preserved, qualified the same way.
    assert {
        "source": f"{stage1.public_id}:n1",
        "target": f"{stage1.public_id}:n2",
    } in edges

    # Stage 1's only exit node (n2 -- nothing in stage 1 depends on it) is
    # implicitly chained to Stage 2's only entry node (n1 -- nothing
    # targets it), since no explicit cross-stage edges exist in the source
    # graphs (the linear-chaining assumption documented in compiler.py).
    assert {
        "source": f"{stage1.public_id}:n2",
        "target": f"{stage2.public_id}:n1",
    } in edges

    assert len(edges) == 2


@pytest.mark.django_db
def test_publish_is_atomic_when_compilation_fails(actor, core_node_types):
    """A node referencing a node type the Compiler can't resolve must fail
    the whole publish -- no orphaned published WorkflowVersion, no
    CompiledVersion row, same as if the Stage-copy step itself had failed."""
    workspace = WorkspaceService().create_workspace(TENANT_ID, name="Bad WS")
    workflow = WorkflowService().create_workflow(
        tenant_id=TENANT_ID,
        workspace_public_id=workspace.public_id,
        name="Unregistered node type workflow",
        stages=[
            {
                "name": "Stage 1",
                "graph": {
                    "nodes": [_core_node("n1", "does.not.exist", "custom")],
                    "edges": [],
                },
            }
        ],
    )

    with pytest.raises(VersionServiceError):
        VersionService().publish(TENANT_ID, workflow)

    versions = VersionService().list_versions(TENANT_ID, workflow)
    assert not any(v.is_published for v in versions)
    # Only the original draft exists -- publish() didn't leave a second,
    # unpublished WorkflowVersion behind either.
    assert versions.count() == 1


@pytest.mark.django_db
def test_publish_rejects_node_types_outside_the_configured_allow_list(
    actor, core_node_types, settings
):
    """Sprint 1 hardcoded the Compiler to only ever compile `core.*` node
    types. Sprint 5 replaced that hardcoded check with a settings-driven
    allow-list (RM_WORKFLOW.ALLOWED_NODE_TYPE_PREFIXES, see conf.py),
    defaulting to ["*"] -- i.e. allow everything, which is what actually
    lets `rm_connector_demo`'s `demo.*` node types compile at all now.
    This test proves the allow-list mechanism itself still rejects a
    disallowed prefix correctly when a tenant/environment configures one
    -- it no longer describes today's *default* behavior, since the
    default is now permissive by design."""
    settings.RM_WORKFLOW = {"ALLOWED_NODE_TYPE_PREFIXES": ["core."]}

    workspace = WorkspaceService().create_workspace(TENANT_ID, name="Legacy type WS")
    workflow = WorkflowService().create_workflow(
        tenant_id=TENANT_ID,
        workspace_public_id=workspace.public_id,
        name="Legacy node type workflow",
        stages=[
            {
                "name": "Stage 1",
                "graph": {
                    "nodes": [_core_node("n1", "processNode", "process")],
                    "edges": [],
                },
            }
        ],
    )

    with pytest.raises(VersionServiceError):
        VersionService().publish(TENANT_ID, workflow)


@pytest.mark.django_db
def test_publish_allows_non_core_node_types_by_default(actor, core_node_types):
    """Companion to the test above: with RM_WORKFLOW left unconfigured
    (today's actual default, ["*"]), a real, registered, active node type
    outside the `core.*` prefix -- `processNode`, one of the pre-existing
    frontend-facing builder types -- compiles successfully. This is the
    behavior change Sprint 5 introduced on purpose, so it gets its own
    assertion rather than only being implied by the absence of a
    failure."""
    workspace = WorkspaceService().create_workspace(TENANT_ID, name="Non-core allowed WS")
    workflow = WorkflowService().create_workflow(
        tenant_id=TENANT_ID,
        workspace_public_id=workspace.public_id,
        name="Non-core node type workflow",
        stages=[
            {
                "name": "Stage 1",
                "graph": {
                    "nodes": [_core_node("n1", "processNode", "process")],
                    "edges": [],
                },
            }
        ],
    )

    version = VersionService().publish(TENANT_ID, workflow)
    compiled = CompiledVersionRepository().get_for_version(TENANT_ID, version)
    assert compiled is not None
    assert compiled.runtime_dsl["nodes"][0]["type"] == "processNode"


@pytest.mark.django_db
def test_publish_of_single_stage_draft_has_no_cross_stage_edges(actor, core_node_types):
    """Sanity check on the flattening logic with only one stage -- no
    cross-stage chaining should be invented out of nothing."""
    workspace = WorkspaceService().create_workspace(TENANT_ID, name="Single stage WS")
    workflow = WorkflowService().create_workflow(
        tenant_id=TENANT_ID,
        workspace_public_id=workspace.public_id,
        name="Single stage workflow",
        stages=[
            {
                "name": "Only stage",
                "graph": {
                    "nodes": [_core_node("n1", "core.input", "input")],
                    "edges": [],
                },
            }
        ],
    )

    version = VersionService().publish(TENANT_ID, workflow)
    compiled = CompiledVersionRepository().get_for_version(TENANT_ID, version)

    assert len(compiled.runtime_dsl["nodes"]) == 1
    assert compiled.runtime_dsl["edges"] == []


def _three_stage_workflow_for_branching(name):
    """Three stages, none referencing each other yet -- Stage public_ids
    only exist once created, so the branch target below is wired in
    afterwards via StageRepository.update_graph(), not at creation time."""
    workspace = WorkspaceService().create_workspace(TENANT_ID, name=f"WS for {name}")
    return WorkflowService().create_workflow(
        tenant_id=TENANT_ID,
        workspace_public_id=workspace.public_id,
        name=name,
        stages=[
            {
                "name": "Stage 1 (branches explicitly)",
                "graph": {
                    "nodes": [_core_node("n1", "core.condition", "condition", expression="true")],
                    "edges": [],
                },
            },
            {
                "name": "Stage 2 (skipped by the explicit jump)",
                "graph": {"nodes": [_core_node("n1", "core.input", "input")], "edges": []},
            },
            {
                "name": "Stage 3 (explicit jump target)",
                "graph": {"nodes": [_core_node("n1", "core.process", "process")], "edges": []},
            },
        ],
    )


@pytest.mark.django_db
def test_publish_resolves_explicit_stage_jump_and_skips_default_chain(actor, core_node_types):
    """A condition node's `branches` config must compile into a concrete,
    `when`-tagged edge straight to the target Stage's entry node -- and
    that node must NOT also pick up the default implicit edge to the
    literal next Stage in `order` (Stage 2 here), since its branches
    config already fully owns its outgoing routing."""
    workflow = _three_stage_workflow_for_branching("Explicit jump workflow")
    stage1, stage2, stage3 = list(workflow.current_version.stages.all())

    StageRepository().update_graph(
        stage1,
        {
            "nodes": [
                _core_node(
                    "n1",
                    "core.condition",
                    "condition",
                    expression="true",
                    branches={"true": stage3.public_id},
                )
            ],
            "edges": [],
        },
    )

    version = VersionService().publish(TENANT_ID, workflow)
    compiled = CompiledVersionRepository().get_for_version(TENANT_ID, version)
    stage1_v, stage2_v, stage3_v = list(version.stages.all())
    edges = compiled.runtime_dsl["edges"]

    # Explicit jump: stage1's node -> stage3's entry node, conditioned on
    # the branch label.
    assert {
        "source": f"{stage1_v.public_id}:n1",
        "target": f"{stage3_v.public_id}:n1",
        "when": "true",
    } in edges

    # Suppressed: no unconditioned edge from stage1 to stage2 (the literal
    # next stage in `order`) -- the branching node owns its own routing.
    assert not any(
        edge["source"] == f"{stage1_v.public_id}:n1" and "when" not in edge for edge in edges
    )

    # Unrelated to the branching feature: stage2's own node still chains
    # implicitly to stage3 via the ordinary default mechanism (stage2 is
    # untouched, still a normal linear link to the next stage in order).
    assert {
        "source": f"{stage2_v.public_id}:n1",
        "target": f"{stage3_v.public_id}:n1",
    } in edges

    assert len(edges) == 2


@pytest.mark.django_db
def test_publish_fails_for_branch_targeting_unknown_stage(actor, core_node_types):
    workflow = _three_stage_workflow_for_branching("Unknown branch target workflow")
    stage1, _stage2, _stage3 = list(workflow.current_version.stages.all())

    StageRepository().update_graph(
        stage1,
        {
            "nodes": [
                _core_node(
                    "n1",
                    "core.condition",
                    "condition",
                    expression="true",
                    branches={"true": "stg_does_not_exist"},
                )
            ],
            "edges": [],
        },
    )

    with pytest.raises(VersionServiceError):
        VersionService().publish(TENANT_ID, workflow)


@pytest.mark.django_db
def test_publish_fails_for_malformed_branches_config(actor, core_node_types):
    workflow = _three_stage_workflow_for_branching("Malformed branches workflow")
    stage1, _stage2, _stage3 = list(workflow.current_version.stages.all())

    StageRepository().update_graph(
        stage1,
        {
            "nodes": [
                _core_node(
                    "n1",
                    "core.condition",
                    "condition",
                    expression="true",
                    branches={"true": 12345},  # not a string target
                )
            ],
            "edges": [],
        },
    )

    with pytest.raises(VersionServiceError):
        VersionService().publish(TENANT_ID, workflow)


@pytest.mark.django_db
def test_publish_fails_for_backward_branch_jump(actor, core_node_types):
    """A branch may only target a Stage that comes *after* its own Stage in
    `order` -- targeting an earlier Stage (or itself) must be rejected, not
    silently compiled into a cycle the Engine has no way to run safely."""
    workflow = _three_stage_workflow_for_branching("Backward branch workflow")
    stage1, stage2, _stage3 = list(workflow.current_version.stages.all())

    # Stage 2 (a later stage) branches BACK to Stage 1 (an earlier one).
    StageRepository().update_graph(
        stage2,
        {
            "nodes": [
                _core_node(
                    "n1",
                    "core.condition",
                    "condition",
                    expression="retry",
                    branches={"retry": stage1.public_id},
                )
            ],
            "edges": [],
        },
    )

    with pytest.raises(VersionServiceError):
        VersionService().publish(TENANT_ID, workflow)


@pytest.mark.django_db
def test_publish_fails_for_self_targeting_branch_jump(actor, core_node_types):
    """A branch targeting its own Stage (order equal, not strictly greater)
    is rejected the same way a backward jump is."""
    workflow = _three_stage_workflow_for_branching("Self-branch workflow")
    stage1, _stage2, _stage3 = list(workflow.current_version.stages.all())

    StageRepository().update_graph(
        stage1,
        {
            "nodes": [
                _core_node(
                    "n1",
                    "core.condition",
                    "condition",
                    expression="retry",
                    branches={"retry": stage1.public_id},
                )
            ],
            "edges": [],
        },
    )

    with pytest.raises(VersionServiceError):
        VersionService().publish(TENANT_ID, workflow)

