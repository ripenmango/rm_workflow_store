from django.db import transaction
from django.utils import timezone

from rm_workflow.workflows.models import Workflow, WorkflowVersion


class WorkflowRepository:
    """
    The only place in rm_workflow allowed to issue queries against Workflow.
    """

    def get_by_public_id(self, tenant_id: str, public_id: str) -> Workflow | None:
        return Workflow.objects.filter(tenant_id=tenant_id, public_id=public_id).first()

    def get_by_id(self, tenant_id: str, workflow_id: int) -> Workflow | None:
        return Workflow.objects.filter(tenant_id=tenant_id, id=workflow_id).first()

    def list(self, tenant_id: str, workspace_public_id: str | None = None):
        qs = Workflow.objects.filter(tenant_id=tenant_id)
        if workspace_public_id is not None:
            # workspace_id column now stores Workspace.public_id (FK
            # to_field), not the integer PK -- filter by that directly.
            qs = qs.filter(workspace_id=workspace_public_id)
        return qs.order_by("name")

    def create(self, tenant_id: str, workspace, name: str, description: str = "") -> Workflow:
        return Workflow.objects.create(
            tenant_id=tenant_id, workspace=workspace, name=name, description=description
        )

    def update(self, workflow: Workflow, **fields) -> Workflow:
        for field, value in fields.items():
            setattr(workflow, field, value)
        workflow.save(update_fields=list(fields))
        return workflow

    def soft_delete(self, workflow: Workflow) -> None:
        workflow.delete()

    def set_current_version(self, workflow: Workflow, version: WorkflowVersion) -> Workflow:
        workflow.current_version = version
        workflow.save(update_fields=["current_version"])
        return workflow


class WorkflowVersionRepository:
    """
    The only place in rm_workflow allowed to issue queries against
    WorkflowVersion.
    """

    def get_by_public_id(
        self, tenant_id: str, workflow: Workflow, public_id: str
    ) -> WorkflowVersion | None:
        return WorkflowVersion.objects.filter(
            tenant_id=tenant_id, workflow=workflow, public_id=public_id
        ).first()

    def list_for_workflow(self, tenant_id: str, workflow: Workflow):
        return WorkflowVersion.objects.filter(
            tenant_id=tenant_id, workflow=workflow
        ).order_by("-version_number")

    def latest_version_number(self, workflow: Workflow) -> int:
        latest = (
            WorkflowVersion.objects.filter(workflow=workflow)
            .order_by("-version_number")
            .values_list("version_number", flat=True)
            .first()
        )
        return latest or 0

    @transaction.atomic
    def create_draft(self, tenant_id: str, workflow: Workflow) -> WorkflowVersion:
        next_number = self.latest_version_number(workflow) + 1
        return WorkflowVersion.objects.create(
            tenant_id=tenant_id,
            workflow=workflow,
            version_number=next_number,
            is_published=False,
        )

    def mark_published(self, version: WorkflowVersion) -> WorkflowVersion:
        version.is_published = True
        version.published_at = timezone.now()
        version.save(update_fields=["is_published", "published_at"])
        return version
