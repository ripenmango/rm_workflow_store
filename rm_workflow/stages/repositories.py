from rm_workflow.stages.models import Stage
from rm_workflow.workflows.models import WorkflowVersion


class StageRepository:
    """
    The only place in rm_workflow allowed to issue queries against Stage.
    """

    def get_by_public_id(
        self, tenant_id: str, workflow_version: WorkflowVersion, public_id: str
    ) -> Stage | None:
        return Stage.objects.filter(
            tenant_id=tenant_id, workflow_version=workflow_version, public_id=public_id
        ).first()

    def list_for_version(self, tenant_id: str, workflow_version: WorkflowVersion):
        return Stage.objects.filter(
            tenant_id=tenant_id, workflow_version=workflow_version
        ).order_by("order")

    def next_order(self, workflow_version: WorkflowVersion) -> int:
        last = (
            Stage.objects.filter(workflow_version=workflow_version)
            .order_by("-order")
            .values_list("order", flat=True)
            .first()
        )
        return 0 if last is None else last + 1

    def create(
        self,
        tenant_id: str,
        workflow_version: WorkflowVersion,
        name: str,
        order: int | None = None,
        description: str = "",
        graph: dict | None = None,
    ) -> Stage:
        return Stage.objects.create(
            tenant_id=tenant_id,
            workflow_version=workflow_version,
            name=name,
            description=description,
            order=self.next_order(workflow_version) if order is None else order,
            graph=graph or {"nodes": [], "edges": []},
        )

    def update_metadata(self, stage: Stage, **fields) -> Stage:
        # Metadata only -- name/description/order. `graph` is never written
        # through this method; see update_graph() below for that separate,
        # dedicated write path (§10).
        fields.pop("graph", None)
        for field, value in fields.items():
            setattr(stage, field, value)
        stage.save(update_fields=list(fields))
        return stage

    def update_graph(self, stage: Stage, graph: dict) -> Stage:
        stage.graph = graph
        stage.save(update_fields=["graph"])
        return stage

    def soft_delete(self, stage: Stage) -> None:
        stage.delete()

    def bulk_create(
        self, tenant_id: str, workflow_version: WorkflowVersion, stages_data: list[dict]
    ) -> list[Stage]:
        """
        Used for both create-time bootstrap (§10) and copy-on-publish
        (VersionService.publish) -- stages_data items are plain dicts with
        name/description/order/graph keys, already validated by the caller.
        """
        stages = [
            Stage(
                tenant_id=tenant_id,
                workflow_version=workflow_version,
                name=data["name"],
                description=data.get("description", ""),
                order=data.get("order", index),
                graph=data.get("graph") or {"nodes": [], "edges": []},
            )
            for index, data in enumerate(stages_data)
        ]
        return Stage.objects.bulk_create(stages)
