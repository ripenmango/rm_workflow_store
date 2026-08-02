from drf_base_app import models
from drf_base_app.models.base import RMAuditModel
from drf_base_app.tenancy.sync import TenantMirrorRegistry


@TenantMirrorRegistry.register
class Tenant(RMAuditModel):
    """
    Thin, local mirror of rm_auth.tenants.models.Tenant -- NOT imported from
    it directly (see workflow-store-design.md §12, "Local Tenant model +
    sync"). Kept in sync via drf_base_app.tenancy.sync.TenantMirrorRegistry's
    centralized post_save receiver, wired up by rm_auth's own
    apps.py.ready() (RmAuthConfig) against the real rm_auth.Tenant model --
    rm_workflow only has to register here, it doesn't wire the signal itself.

    Uses RMAuditModel (not RMTimeStampModel) deliberately, unlike rm_auth's
    own Tenant/Action: rm_workflow is a TENANT_APPS entry (see the "Tier B
    Implementation Plan" doc, §2), same tier as rm_auth_tenant (which owns
    AUTH_USER_MODEL). A hard FK from this model's created_by/updated_by to
    rm_auth_tenant.User only creates a ONE-DIRECTION migration dependency
    (rm_workflow -> rm_auth_tenant), which is fine -- the circular-dependency
    problem that forced rm_auth's own Tenant/Action onto RMTimeStampModel
    (see that model's docstring) only arises for models that stay behind in
    the SHARED_APPS tier while AUTH_USER_MODEL lives in TENANT_APPS. That
    doesn't apply here.

    This is a same-process/same-database-signal-bus mechanism (see
    TenantMirrorRegistry's own docstring for when to revisit that
    assumption).
    """

    id = models.CharField(max_length=64, primary_key=True)  # same slug as rm_auth's Tenant.id
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)

    class Meta:
        app_label = "rm_workflow"
        db_table = "rm_workflow_tenant"

    def __str__(self) -> str:
        return self.id
