from drf_base_app import models
from drf_base_app.models.base import RMAuditModel, RMPublicIdModel, RMSoftDeleteModel
from drf_base_app.models.indexes import Index as ActiveIndex


class Workspace(RMAuditModel, RMSoftDeleteModel, RMPublicIdModel):
    """
    Top-level container under a tenant (e.g. "HR", "Finance") -- §5.2.
    """

    public_id_prefix = "ws"

    tenant_id = models.CharField(max_length=64, db_index=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")

    class Meta:
        app_label = "rm_workflow"
        db_table = "rm_workflow_workspace"
        # NOTE: the design doc's original §5.2 UniqueConstraint(tenant_id, name)
        # -- mirroring rm_auth's (tenant_id, username) -- assumed tenant_id
        # identifies one organization (its own example: "HR", "Finance" as
        # sibling departments under one tenant). That assumption doesn't hold
        # for shared bucket tenants like rm_community, where many unrelated
        # users share a single tenant_id and each privately owns their own
        # workspace (scoped via EntityAccessGrant, not by row visibility) --
        # every one of them defaults to "My Workspace" on signup, so the
        # constraint collided across users who have no relationship to each
        # other. Removed 2026-08-08; see docs/workflow-store-design.md errata.
        # `name` is a display label; `public_id` is the actual identifier.
        indexes = [
            ActiveIndex(fields=["tenant_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.tenant_id}:{self.name}"
