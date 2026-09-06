from rm_workflow.compiled_versions.repositories import CompiledVersionRepository
from rm_workflow.compiler.compiler import CompilationError, Compiler
from rm_workflow.workflows.models import WorkflowVersion


class CompiledVersionServiceError(Exception):
    pass


class CompiledVersionService:
    """
    Owns compile-on-publish (§41.1, Sprint 1): calls Compiler.compile() and
    persists the result as a CompiledVersion. Called from
    VersionService.publish(), inside that method's own @transaction.atomic
    block, so a WorkflowVersion is never marked published without a
    matching CompiledVersion existing for it -- a CompilationError rolls
    back the whole publish, stages included.
    """

    def __init__(self, compiler: Compiler | None = None, compiled_versions=None):
        self.compiler = compiler or Compiler()
        self.compiled_versions = compiled_versions or CompiledVersionRepository()

    def compile_and_store(self, tenant_id: str, workflow_version: WorkflowVersion):
        try:
            runtime_dsl = self.compiler.compile(workflow_version)
        except CompilationError as exc:
            raise CompiledVersionServiceError(str(exc)) from exc

        existing = self.compiled_versions.get_for_version(tenant_id, workflow_version)
        if existing is not None:
            # Not reached on the normal publish path -- VersionService.publish()
            # always creates a brand new WorkflowVersion first (see that
            # method's own docstring), so there's never an already-compiled
            # row to replace here. Kept so a future explicit "recompile"
            # operation (see CompiledVersion's own model docstring) has
            # somewhere to live without inventing a second code path.
            return self.compiled_versions.replace(
                existing, runtime_dsl, self.compiler.version
            )
        return self.compiled_versions.create(
            tenant_id, workflow_version, runtime_dsl, self.compiler.version
        )

    def get_for_version(self, tenant_id: str, workflow_version: WorkflowVersion):
        return self.compiled_versions.get_for_version(tenant_id, workflow_version)
