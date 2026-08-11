"""
Platform-only management of the node type catalog -- see NodeType's model
docstring for why this is Django admin (is_superuser-gated) rather than a
Casbin-backed API endpoint. Register a Django superuser with
`manage.py createsuperuser` to get /admin/ access; this is intentionally
separate from any tenant's Casbin roles/personas.
"""
from django.contrib import admin

from rm_workflow.node_types.models import NodeType, TenantNodeTypeSetting


@admin.register(NodeType)
class NodeTypeAdmin(admin.ModelAdmin):
    list_display = ("type", "label", "category", "tenant_id", "is_active", "updated_at")
    list_filter = ("category", "is_active", "tenant_id")
    search_fields = ("type", "label", "description")
    readonly_fields = ("public_id", "created_at", "updated_at", "created_by", "updated_by")
    fields = (
        "public_id",
        "tenant_id",
        "type",
        "label",
        "category",
        "icon",
        "description",
        "properties_schema",
        "is_active",
        "created_at",
        "updated_at",
        "created_by",
        "updated_by",
    )


@admin.register(TenantNodeTypeSetting)
class TenantNodeTypeSettingAdmin(admin.ModelAdmin):
    list_display = ("tenant_id", "node_type", "enabled", "updated_at")
    list_filter = ("enabled",)
    search_fields = ("tenant_id", "node_type__type")
    autocomplete_fields = ("node_type",)
