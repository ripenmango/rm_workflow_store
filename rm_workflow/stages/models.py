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
        WorkflowVersion, to_field="public_id", on_delete=dj_models.CASCADE, related_name="stages"
    )
    tenant_id = models.CharField(max_length=64, db_index=True)  # denormalized
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    order = models.PositiveIntegerField()  # tab ordering
    graph = models.JSONField(default=dict)  # {"nodes": [...], "edges": [...]}
    # Form <-> Workflow integration (rm_form_store Architecture & Design doc
    # SS18 "Direction 2", this codebase's own Phase 5). A plain,
    # unconstrained public_id reference to a Form in rm_form_store (prefix
    # "frm"), NOT a real FK -- rm_workflow_store must not import
    # rm_form_store (import-linter's cross-package boundary is a hard
    # contract), and there is no local mirror table for Form the way
    # Form.workspace/Form.project mirror INTO rm_form_store from the other
    # direction, so a real FK is not an option here regardless of any
    # policy preference. NULL means "this stage has no attached form" (the
    # ordinary case for the overwhelming majority of stages).
    #
    # Deliberately validated NOWHERE inside this package: SS18 frames
    # Stage<->Form as two independent aggregates that reference each other
    # by public_id, checked (if at all) at the point each is authored --
    # and "the point a Stage is authored" is a client that already holds
    # both a workflow-store session and a form-store session (today, the
    # frontend composing both APIs; there is no in-process caller that
    # could check "does this Form exist and is it published" without
    # exactly the cross-package coupling import-linter exists to forbid).
    # This is called out explicitly, not silently assumed safe -- an
    # authored Stage can reference a Form public_id that is later archived,
    # deleted, or never existed at all, and rm_workflow_store has no way to
    # know. Revisit if/when a service-to-service validation call (HTTP, not
    # a Python import) is worth the added runtime coupling.
    required_form_id = models.CharField(max_length=64, null=True, blank=True)

    class Meta:
        app_label = "rm_workflow"
        db_table = "rm_workflow_stage"
        ordering = ["order"]
        indexes = [
            ActiveIndex(fields=["tenant_id", "workflow_version"]),
            jsonb_gin_index("graph"),
            # Lets a future "which stages require Form X" lookup (e.g. an
            # admin tool warning before a Form is archived) avoid a
            # sequential scan -- no in-process caller does this query yet
            # (see field-level comment above on why cross-package
            # validation isn't performed here), but the index costs
            # nothing to add now and the column is already sparse (mostly
            # NULL).
            ActiveIndex(fields=["tenant_id", "required_form_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.workflow_version_id}:{self.name}"

    def save(self, *args, **kwargs):
        if self.workflow_version_id:
            self.tenant_id = self.workflow_version.tenant_id
        super().save(*args, **kwargs)
