from drf_base_app import models
from drf_base_app.models.base import RMAuditModel, RMPublicIdModel, RMSoftDeleteModel
from drf_base_app.models.indexes import Index as ActiveIndex, TenantIndex, jsonb_gin_index

from rm_workflow.validation.category_schemas import NODE_CATEGORIES
from django.db import models as dj_models


# Mirrors NodePalette.tsx's `iconMap` keys on the frontend (lucide-react
# component names) -- same cross-repo sync situation as NODE_CATEGORIES
# above (no shared schema package between the two repos yet). This is the
# "decoupling" fix discussed for icon storage: not base64 image data (bloats
# the palette response, loses lucide's currentColor theming, and doesn't
# remove the coupling -- something still has to interpret bytes into
# pixels), but validating the semantic key against a documented vocabulary so
# a typo/removed icon fails loudly here rather than silently falling back to
# NodePalette's default (Cog) on the frontend. Update BOTH lists together.
ICON_KEYS = frozenset(
    {
        "ArrowDownToLine",
        "Cog",
        "ArrowUpFromLine",
        "GitBranch",
        "Globe",
        "Mail",
        "Clock",
        "Filter",
        "Webhook",
        "Workflow",
        "Zap",
        "ArrowRightLeft",
    }
)


class NodeType(RMAuditModel, RMSoftDeleteModel, RMPublicIdModel):
    """
    Catalog entry for a draggable node type in the workflow builder's
    palette (e.g. "API Call", "Send Email"). Replaces what used to be a
    hardcoded array in the frontend's mockData.ts -- see rm_workflow_client's
    CLAUDE.md, "Node property schema" section, for the DSL this mirrors
    (property-dsl.ts's PropertyField[] shape).

    `tenant_id=NULL` means a system-wide default, available to every tenant
    unless overridden by a TenantNodeTypeSetting row (see below) -- this is
    the only kind seeded today (via `manage.py seed_node_types`). Non-null
    `tenant_id` is reserved for a possible future "tenant-authored custom
    node type" (not built yet -- nothing currently creates one).

    Editing `properties_schema` or `is_active` is deliberately NOT exposed
    through this app's Casbin-gated API at all (see api/views.py --
    NodeTypeListView is read-only). It's platform-catalog data, edited via
    Django admin (/admin/), which is is_superuser-gated and INTENTIONALLY
    independent of the tenant-scoped Casbin permission system -- same
    separation seed_roles.py's docstring describes for platform_admin vs.
    is_superuser. There is no "platform" Casbin domain to hang a `manage`
    permission off in this model.conf (every policy row is tenant-scoped,
    see policy/casbin_model.conf's matcher requiring r.dom == p.dom), so
    Django admin -- not a new API resource -- is the correct fit for a
    genuinely cross-tenant, platform-only capability.
    """

    public_id_prefix = "ntype"

    tenant_id = models.CharField(max_length=64, db_index=True, null=True, blank=True)
    type = models.CharField(
        max_length=100
    )  # e.g. 'apiCallNode' -- matches frontend NodeDefinition.type
    label = models.CharField(max_length=255)
    category = models.CharField(
        max_length=32, choices=[(c, c) for c in sorted(NODE_CATEGORIES)]
    )  # validated against NODE_CATEGORIES in clean(); choices= gives Django admin a dropdown
    icon = models.CharField(
        max_length=100, choices=[(k, k) for k in sorted(ICON_KEYS)]
    )  # lucide-react icon name -- validated against ICON_KEYS in clean(); choices= gives Django admin a dropdown
    description = models.TextField(blank=True, default="")
    # PropertyField[] -- see rm_workflow_client/src/lib/property-dsl.ts. Kept
    # as opaque JSON here (not modeled relationally) same rationale as
    # Stage.graph: frontend-shaped, not queried relationally by this app.
    properties_schema = models.JSONField(default=list)
    is_active = models.BooleanField(
        default=True
    )  # global kill switch (deprecate a type everywhere)

    class Meta:
        app_label = "rm_workflow"
        db_table = "rm_workflow_node_type"
        constraints = [
            dj_models.UniqueConstraint(
                fields=["tenant_id", "type"], name="uniq_tenant_node_type"
            ),
        ]
        indexes = [
            ActiveIndex(fields=["tenant_id"], name="idx_active_ntype_tenant"),
            jsonb_gin_index("properties_schema"),
        ]

    def clean(self):
        from django.core.exceptions import ValidationError

        errors = {}
        if self.category not in NODE_CATEGORIES:
            errors["category"] = (
                f"Unknown node category '{self.category}'. Must be one of: {sorted(NODE_CATEGORIES)}"
            )
        if self.icon not in ICON_KEYS:
            errors["icon"] = (
                f"Unknown icon key '{self.icon}'. Must be one of: {sorted(ICON_KEYS)} "
                f"(see NodePalette.tsx's iconMap on the frontend -- add it there first "
                f"if this is a genuinely new icon)."
            )
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        scope = self.tenant_id or "global"
        return f"{scope}:{self.type}"


class TenantNodeTypeSetting(RMAuditModel):
    """
    Per-tenant override of whether a NodeType is enabled for that tenant's
    palette. Absence of a row for a given (tenant_id, node_type) pair means
    "inherit NodeType.is_active" -- only tenants that actually deviate from
    the default get a row here, same "store only the delta" approach as
    Workspace's now-removed name-uniqueness constraint (see that model's
    Meta comment). This is what satisfies "which nodes are enabled for the
    customer" -- also platform-managed via Django admin, not a tenant
    self-service setting (see NodeType's docstring for why).
    """

    tenant_id = models.CharField(max_length=64, db_index=True)
    node_type = models.ForeignKey(
        NodeType, to_field="public_id", on_delete=dj_models.CASCADE
    )
    enabled = models.BooleanField()

    class Meta:
        app_label = "rm_workflow"
        db_table = "rm_workflow_tenant_node_type_setting"
        constraints = [
            dj_models.UniqueConstraint(
                fields=["tenant_id", "node_type"], name="uniq_tenant_node_type_setting"
            ),
        ]
        indexes = [
            # Plain TenantIndex, not ActiveIndex -- this model has no
            # deleted_at (no RMSoftDeleteModel), so ActiveIndex's default
            # `WHERE deleted_at IS NULL` partial-index condition doesn't
            # apply here.
            TenantIndex(fields=["tenant_id"], name="idx_setting_tenant"),
        ]

    def __str__(self) -> str:
        return (
            f"{self.tenant_id}:{self.node_type.type}={'on' if self.enabled else 'off'}"
        )
