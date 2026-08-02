from rm_workflow.tenants.models import Tenant


class TenantRepository:
    """
    Reads against the local Tenant mirror only -- rm_workflow never queries
    rm_auth's real Tenant table directly (see models.py's docstring). Kept
    read-oriented: the mirror is written exclusively by
    TenantMirrorRegistry's signal receiver, never by application code here.
    """

    def get(self, tenant_id: str) -> Tenant | None:
        return Tenant.objects.filter(id=tenant_id, is_active=True).first()
