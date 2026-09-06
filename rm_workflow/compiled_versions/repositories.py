from rm_workflow.compiled_versions.models import CompiledVersion
from rm_workflow.workflows.models import WorkflowVersion


class CompiledVersionRepository:
    """
    The only place in rm_workflow allowed to issue queries against
    CompiledVersion. Sprint 0: basic CRUD only -- CompiledVersionService
    (Sprint 1) is what actually calls Compiler and decides when a
    (re-)compile is needed; this repository just persists/reads its output.
    """

    def get_for_version(
        self, tenant_id: str, workflow_version: WorkflowVersion
    ) -> CompiledVersion | None:
        return CompiledVersion.objects.filter(
            tenant_id=tenant_id, workflow_version=workflow_version
        ).first()

    def create(
        self,
        tenant_id: str,
        workflow_version: WorkflowVersion,
        runtime_dsl: dict,
        compiler_version: str,
    ) -> CompiledVersion:
        return CompiledVersion.objects.create(
            tenant_id=tenant_id,
            workflow_version=workflow_version,
            runtime_dsl=runtime_dsl,
            compiler_version=compiler_version,
        )

    def replace(
        self,
        existing: CompiledVersion,
        runtime_dsl: dict,
        compiler_version: str,
    ) -> CompiledVersion:
        # Re-compile of an already-compiled version (Sprint 1's
        # CompiledVersionService.recompile) -- update in place rather than
        # delete+create, so the row's created_at continues to reflect the
        # original compile if that's ever needed, while runtime_dsl and
        # compiler_version reflect the latest compile.
        # No update_fields restriction here -- RMAuditModel.save() also
        # needs to persist updated_by/updated_at on every save, and a
        # restrictive update_fields list would silently drop those (see
        # RMSoftDeleteModel.delete()'s own comment on this exact gotcha in
        # drf_base_app.models.base).
        existing.runtime_dsl = runtime_dsl
        existing.compiler_version = compiler_version
        existing.save()
        return existing
