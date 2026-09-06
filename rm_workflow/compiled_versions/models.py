from django.db import models as dj_models
from drf_base_app import models
from drf_base_app.models.base import RMAuditModel

from rm_workflow.workflows.models import WorkflowVersion


class CompiledVersion(RMAuditModel):
    """
    The Compiler's output (architecture doc §41.1/§41.2): a flattened,
    engine-ready representation of a published WorkflowVersion's Stage
    graph, produced by rm_workflow.compiler.Compiler and consumed by
    rm_engine_app -- never rebuilt from Stage rows at execution time, so a
    later in-place edit to an already-published WorkflowVersion's stages
    (if that's ever allowed) can't silently change what a running execution
    is executing (§41.1's core motivation for splitting Compiler output
    from the editable Stage graph).

    One-to-one, not one-to-many: only ever compiled once per WorkflowVersion
    (a WorkflowVersion is otherwise immutable once published, mirroring
    WorkflowVersion's own "no soft-delete, nothing to version further"
    design in workflows.models.WorkflowVersion). Re-publishing the same
    logical workflow content always creates a NEW WorkflowVersion row
    first, not a re-compile of an old one.

    Deliberately NOT an RMPublicIdModel: nothing outside this app or
    rm_engine_app addresses a CompiledVersion directly by id today -- it's
    always looked up via its workflow_version's public_id
    (CompiledVersionService, added in Sprint 1). Add RMPublicIdModel later,
    additively, if/when a use case needs to reference one directly (YAGNI).

    `created_at` (from RMAuditModel) doubles as "compiled_at" -- no separate
    field, since a CompiledVersion is create-once, never updated in place
    (a re-compile creates a new row, replacing this one via
    CompiledVersionService.recompile in Sprint 1, not an in-place update).
    """

    workflow_version = models.OneToOneField(
        WorkflowVersion,
        to_field="public_id",
        on_delete=dj_models.CASCADE,
        related_name="compiled_version",
    )
    # Denormalized from workflow_version.tenant_id, same convention as
    # Workflow/WorkflowVersion's own tenant_id -- kept in sync in save()
    # below, not just on first save (see Workflow.save()'s own comment on
    # why: workspace/version reassignment must never leave a stale value).
    tenant_id = models.CharField(max_length=64, db_index=True)
    # The Compiler's flattened output (§41.2) -- shape defined by the
    # Compiler itself (Sprint 1), not by this model. Read by rm_engine_app
    # via CompiledVersionService only, never queried directly cross-app
    # (import-linter contract in rm_workflow_engine's pyproject.toml).
    runtime_dsl = dj_models.JSONField()
    # Version of rm_workflow.compiler.Compiler that produced this row --
    # lets a future Compiler change decide whether old CompiledVersion rows
    # need a one-time re-compile, without guessing from created_at alone.
    compiler_version = models.CharField(max_length=32)

    class Meta:
        app_label = "rm_workflow"
        db_table = "rm_workflow_compiled_version"
        indexes = [
            dj_models.Index(fields=["tenant_id", "workflow_version"]),
        ]

    def __str__(self) -> str:
        return f"compiled:{self.workflow_version_id}"

    def save(self, *args, **kwargs):
        if self.workflow_version_id:
            self.tenant_id = self.workflow_version.tenant_id
        super().save(*args, **kwargs)
