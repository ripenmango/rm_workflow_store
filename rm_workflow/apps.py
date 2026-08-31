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
        #
        # The reverse direction: rm_workflow OWNS Workspace and Project, so
        # unlike Tenant above, THIS app is the one that decides the
        # mirror-sync wiring exists for consuming apps (e.g. rm_form_store --
        # see its Architecture & Design doc, SS17) that keep local, thin
        # mirrors of these two models. Connects the real post_save signal
        # against rm_workflow's own Workspace/Project model classes;
        # consuming apps only ever need to register a mirror model, never
        # connect this signal themselves.
        from drf_base_app.tenancy.sync import (
            connect_project_mirror_signal,
            connect_workspace_mirror_signal,
        )

        connect_workspace_mirror_signal()
        connect_project_mirror_signal()
        # Purges EntityAccessGrant rows (rm_auth_tenant) if a Workspace/
        # Workflow is ever hard-deleted -- see
        # rm_auth_tenant.authorization.signals for why this is opt-in per
        # model rather than automatic.
        from rm_auth_tenant.authorization.signals import connect_hard_delete_cleanup

        from rm_workflow.projects.models import Project
        from rm_workflow.tenants import models  # noqa: F401
        from rm_workflow.workflows.models import Workflow
        from rm_workflow.workspaces.models import Workspace

        connect_hard_delete_cleanup(Workspace, "workspace")
        connect_hard_delete_cleanup(Project, "project")
        connect_hard_delete_cleanup(Workflow, "workflow")

        # Registers check_every_view_declares_access against THIS service's
        # own URL conf -- rm_workflow_store is a separate deployable service
        # from rm_auth_tenant, with its own `manage.py check`/CI run, so the
        # check (defined once in rm_auth_tenant since it's generic, no
        # rm_auth_tenant-specific logic) needs importing here too, not just
        # there -- see rm_auth_tenant/authorization/DESIGN.md.
        from rm_auth_tenant import checks  # noqa: F401
