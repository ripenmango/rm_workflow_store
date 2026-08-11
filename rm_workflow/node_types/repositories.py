from django.db.models import Q

from rm_workflow.node_types.models import NodeType, TenantNodeTypeSetting


class NodeTypeRepository:
    """The only place in rm_workflow allowed to issue queries against
    NodeType/TenantNodeTypeSetting -- see WorkspaceRepository's docstring
    for the import-linter contract this follows (services call repositories,
    api/views.py never imports these models directly)."""

    def list_available(self, tenant_id: str):
        """Global (tenant_id=NULL) node types plus this tenant's own, minus
        whichever ones this tenant has an explicit disabling override for.
        Mirrors NodeType.is_active as the default when no override exists."""
        disabled_overrides = set(
            TenantNodeTypeSetting.objects.filter(
                tenant_id=tenant_id, enabled=False
            ).values_list("node_type_id", flat=True)
        )
        queryset = (
            NodeType.objects.filter(Q(tenant_id__isnull=True) | Q(tenant_id=tenant_id))
            .filter(is_active=True)
            .order_by("category", "label")
        )
        if disabled_overrides:
            queryset = queryset.exclude(id__in=disabled_overrides)
        return queryset

    def get_by_type(self, tenant_id: str, type_key: str) -> NodeType | None:
        return (
            NodeType.objects.filter(Q(tenant_id__isnull=True) | Q(tenant_id=tenant_id))
            .filter(type=type_key)
            .order_by("-tenant_id")  # tenant-owned override, if any, wins over global
            .first()
        )
