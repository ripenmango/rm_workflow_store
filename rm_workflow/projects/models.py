from django.db import models as dj_models
from drf_base_app import models
from drf_base_app.models.base import RMAuditModel, RMPublicIdModel, RMSoftDeleteModel
from drf_base_app.models.indexes import Index as ActiveIndex

from rm_workflow.workspaces.models import Workspace


class Project(RMAuditModel, RMSoftDeleteModel, RMPublicIdModel):
    """A workspace-scoped container for a user-facing project.

    Automation flows belong to a project through ``Workflow.project``.
    Keeping the relationship nullable preserves existing standalone workflows
    and lets them be assigned to a project incrementally.
    """

    public_id_prefix = "prj"

    workspace = models.ForeignKey(
        Workspace,
        to_field="public_id",
        on_delete=dj_models.CASCADE,
        related_name="projects",
    )
    tenant_id = models.CharField(max_length=64, db_index=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")

    class Meta:
        app_label = "rm_workflow"
        db_table = "rm_workflow_project"
        indexes = [
            ActiveIndex(
                fields=["tenant_id", "workspace"],
                name="idx_project_tenant_ws",
            )
        ]

    def __str__(self) -> str:
        return f"{self.tenant_id}:{self.name}"

    def save(self, *args, **kwargs):
        if self.workspace_id:
            self.tenant_id = self.workspace.tenant_id
        super().save(*args, **kwargs)
