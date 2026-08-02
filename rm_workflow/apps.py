from django.apps import AppConfig


class RmWorkflowConfig(AppConfig):
    """
    Single app_label ("rm_workflow") for the whole library, even though the
    code is organized into sub-packages (tenants/, workspaces/, workflows/,
    stages/) -- every model's Meta.app_label is set explicitly to
    "rm_workflow", matching rm_auth/rm_auth_tenant's "one installable app,
    one migrations history" convention (see rm_auth.apps.RmAuthConfig).

    A TENANT_APPS entry (see the "Tier B Implementation Plan" doc, §2) --
    migrated onto every tenant schema, including "public" (the shared home
    for every not-yet-promoted tenant, per that doc's hybrid model, §1).
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "rm_workflow"
    label = "rm_workflow"
    verbose_name = "RM Workflow"

    def ready(self):
        # rm_workflow.tenants.models.Tenant registers itself against
        # TenantMirrorRegistry via the @TenantMirrorRegistry.register
        # decorator at import time (see workflow-store-design.md §12) --
        # the actual signal connection happens in rm_auth's own
        # apps.py.ready() (rm_auth owns the real Tenant model and is the one
        # app that should decide the sync wiring exists). This import here
        # just guarantees rm_workflow's mirror model has been imported (and
        # therefore registered) by the time any Tenant is saved, regardless
        # of Django's app-loading order.
        from rm_workflow.tenants import models  # noqa: F401
