from django.db import models as dj_models

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
        constraints = [
            # The design doc (§5.2) specifies a plain UniqueConstraint(tenant_id, name)
            # mirroring rm_auth's (tenant_id, username). Made partial here
            # (condition=deleted_at IS NULL) instead, since Workspace is also
            # soft-deleting (§11) -- without the condition, soft-deleting a
            # Workspace named "Finance" would permanently block ever creating
            # another "Finance" workspace for that tenant, which contradicts
            # what soft-delete is for. Matches the same partial-active
            # convention drf_base_app.models.indexes.Index already
            # establishes for soft-deleted rows.
            dj_models.UniqueConstraint(
                fields=["tenant_id", "name"],
                condition=dj_models.Q(deleted_at__isnull=True),
                name="uniq_workspace_tenant_name_active",
            ),
        ]
        indexes = [
            ActiveIndex(fields=["tenant_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.tenant_id}:{self.name}"
