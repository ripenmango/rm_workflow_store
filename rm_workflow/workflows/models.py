from django.db import models as dj_models

from drf_base_app import models
from drf_base_app.models.base import RMAuditModel, RMPublicIdModel, RMSoftDeleteModel
from drf_base_app.models.indexes import Index as ActiveIndex

from rm_workflow.workspaces.models import Workspace


class Workflow(RMAuditModel, RMSoftDeleteModel, RMPublicIdModel):
    """
    Metadata only -- name/description/workspace (§5.1/§5.2). Saving a
    Workflow never touches Stage content; editing a workflow's name and
    editing a stage's canvas are two independent operations that can't race
    each other (§5.1).
    """

    public_id_prefix = "wrf"

    workspace = models.ForeignKey(
        Workspace, to_field="public_id", on_delete=dj_models.CASCADE, related_name="workflows"
    )
    # Denormalized from workspace.tenant_id, kept in sync at write time
    # (§5.2) -- see save() below.
    tenant_id = models.CharField(max_length=64, db_index=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    # Published (or latest draft) version -- null until the first draft
    # exists (set by WorkflowService.create_workflow in the same
    # transaction as the Workflow row itself, so this is only ever null
    # transiently, never in practice after create_workflow returns).
    current_version = models.ForeignKey(
        "rm_workflow.WorkflowVersion",
        to_field="public_id",
        null=True,
        blank=True,
        on_delete=dj_models.SET_NULL,
        related_name="+",
    )

    class Meta:
        app_label = "rm_workflow"
        db_table = "rm_workflow_workflow"
        indexes = [
            ActiveIndex(fields=["tenant_id", "workspace"]),
        ]

    def __str__(self) -> str:
        return f"{self.tenant_id}:{self.name}"

    def save(self, *args, **kwargs):
        # Always resynced from workspace.tenant_id, not just on first save --
        # workspace reassignment (not currently exposed via the API, §10,
        # but not forbidden at the model level either) must never leave a
        # stale tenant_id behind.
        if self.workspace_id:
            self.tenant_id = self.workspace.tenant_id
        super().save(*args, **kwargs)


class WorkflowVersion(RMAuditModel, RMPublicIdModel):
    """
    A pure container/pointer -- its content lives in its Stage rows (reverse
    FK), never on this model itself (§5.2). Deliberately NOT soft-deleting
    (§11): only one version matters at a time (the current draft, or the
    current published version), so there's no meaningful "soft-delete an old
    version" operation -- a Workflow's own soft-delete already makes all its
    versions unreachable through the normal API.
    """

    public_id_prefix = "wfv"

    workflow = models.ForeignKey(
        Workflow, to_field="public_id", on_delete=dj_models.CASCADE, related_name="versions"
    )
    tenant_id = models.CharField(max_length=64, db_index=True)  # denormalized
    version_number = models.PositiveIntegerField()  # monotonic per workflow
    is_published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "rm_workflow"
        db_table = "rm_workflow_workflow_version"
        constraints = [
            dj_models.UniqueConstraint(
                fields=["workflow", "version_number"],
                name="uniq_workflow_version_number",
            ),
        ]
        indexes = [
            dj_models.Index(fields=["tenant_id", "workflow"]),
        ]
        ordering = ["-version_number"]

    def __str__(self) -> str:
        return f"{self.workflow_id}:v{self.version_number}"
