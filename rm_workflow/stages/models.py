from django.db import models as dj_models

from drf_base_app import models
from drf_base_app.models.base import RMAuditModel, RMPublicIdModel, RMSoftDeleteModel
from drf_base_app.models.indexes import Index as ActiveIndex, jsonb_gin_index

from rm_workflow.workflows.models import WorkflowVersion


class Stage(RMAuditModel, RMSoftDeleteModel, RMPublicIdModel):
    """
    A single stage/tab within a WorkflowVersion, saved independently of its
    siblings (§5.1's point 4: concurrent edits to two different stages of
    the same draft must not overwrite each other). `graph` holds nodes/edges
    verbatim as the frontend's canvas shapes them (§5.2) -- arbitrary,
    frontend-shaped JSON, never queried relationally by this app on its own
    (§7).

    Because nodes and edges live in the SAME stage's JSON document, an edge
    can never structurally reference a node in a different stage -- the
    "same-stage" validation rule is a structural fact of this data shape,
    not something GraphService needs to check across documents (§9).
    """

    public_id_prefix = "stg"

    workflow_version = models.ForeignKey(
        WorkflowVersion, on_delete=dj_models.CASCADE, related_name="stages"
    )
    tenant_id = models.CharField(max_length=64, db_index=True)  # denormalized
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    order = models.PositiveIntegerField()  # tab ordering
    graph = models.JSONField(default=dict)  # {"nodes": [...], "edges": [...]}

    class Meta:
        app_label = "rm_workflow"
        db_table = "rm_workflow_stage"
        ordering = ["order"]
        indexes = [
            ActiveIndex(fields=["tenant_id", "workflow_version"]),
            jsonb_gin_index("graph"),
        ]

    def __str__(self) -> str:
        return f"{self.workflow_version_id}:{self.name}"

    def save(self, *args, **kwargs):
        if self.workflow_version_id:
            self.tenant_id = self.workflow_version.tenant_id
        super().save(*args, **kwargs)
