"""
RM_WORKFLOW settings accessor -- mirrors rm_engine_app.conf.RMEngineSettings
exactly (and, transitively, rm_form_store.conf.RMFormStoreSettings /
rm_auth_tenant.conf.RMAuthTenantSettings): a small class reading its OWN
namespace off Django settings (RM_WORKFLOW, not settings.<random_key>
directly), so rm_workflow never guesses at a consuming project's settings
shape and every key rm_workflow reads is documented in exactly one place.

Sprint 5: ALLOWED_NODE_TYPE_PREFIXES replaces the Compiler's old hardcoded
"only core.* compiles" check (see compiler.py's _compile_node). Defaults to
["*"] (allow everything) -- i.e. today's actual behavior once the hardcoded
check is removed, not a new restriction. A consuming platform project can
tighten this later (e.g. ["core.", "demo.", "gmail."]) per-environment
without another Compiler code change.
"""

from django.conf import settings
from drf_base_app.conf import BaseSettings

class RMWorkflowSettings(BaseSettings):
    namespace = "RM_WORKFLOW"

    defaults = {
        "ALLOWED_NODE_TYPE_PREFIXES": ["*"],
    }

    @property
    def config(self) -> dict:
        return {**self.defaults, **getattr(settings, self.namespace, {})}

    @property
    def allowed_node_type_prefixes(self) -> list[str]:
        return self.config["ALLOWED_NODE_TYPE_PREFIXES"]


rm_workflow_settings = RMWorkflowSettings()
