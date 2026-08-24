from rm_workflow.projects.models import Project


class ProjectRepository:
    """The only data-access layer for Project rows."""

    def get_by_public_id(self, tenant_id: str, public_id: str) -> Project | None:
        return Project.objects.filter(tenant_id=tenant_id, public_id=public_id).first()

    def list(self, tenant_id: str, workspace_public_id: str | None = None):
        print(f"ProjectRepository.list: tenant_id={tenant_id}, workspace_public_id={workspace_public_id}")
        queryset = Project.objects.filter(tenant_id=tenant_id)
        if workspace_public_id is not None:
            queryset = queryset.filter(workspace_id=workspace_public_id)
        return queryset.order_by("name")

    def create(
        self, tenant_id: str, workspace, name: str, description: str = ""
    ) -> Project:
        return Project.objects.create(
            tenant_id=tenant_id,
            workspace=workspace,
            name=name,
            description=description,
        )

    def update(self, project: Project, **fields) -> Project:
        for field, value in fields.items():
            setattr(project, field, value)
        project.save(update_fields=list(fields))
        return project

    def soft_delete(self, project: Project) -> None:
        project.delete()
