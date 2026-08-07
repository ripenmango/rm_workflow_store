from django.conf import settings

print("1. rm_workflow_store's actual DB connection:")
db = settings.DATABASES["default"]
print("   NAME:", db.get("NAME"))
print("   HOST:", db.get("HOST"))
print("   PORT:", db.get("PORT"))

from rm_auth_tenant.policy.models import PolicyRule
from rm_auth_tenant.roles.models import Persona

print("2. Personas visible to THIS process for tenant_id='rm_community':")
for p in Persona.objects.filter(tenant_id="rm_community"):
    print("   -", repr(p.name), "slug=", p.slug, "roles=", [r.name for r in p.roles.all()])

print("3. PolicyRule rows visible to THIS process for workspace/workflow:")
rows = list(PolicyRule.objects.filter(tenant_id="rm_community", resource__in=["workspace", "workflow"]))
if not rows:
    print("   NONE -- this process cannot see the grants at all (separate DB, or wrong tenant_id)")
for row in rows:
    print("   -", row.subject, row.resource, row.action)

print("4. Calling PolicyService().is_allowed(...) directly, bypassing any view/cache assumptions:")
from rm_auth_tenant.policy.service import PolicyService

for action in ("manage", "owner_only", "shared"):
    result = PolicyService().is_allowed("rm_community", "tenant-administrator", "workspace", action)
    print(f"   is_allowed(rm_community, tenant-administrator, workspace, {action}) =", result)

print("5. Checking the in-process Casbin enforcer cache directly:")
from rm_auth_tenant.policy import engine

print("   cached tenants:", list(engine._cache.keys()))
if "rm_community" in engine._cache:
    cached_at = engine._cache["rm_community"]
    print("   rm_community cache entry:", cached_at)
    print("   --> if this was cached BEFORE your recent DB clear/signup, it's stale.")
    print("   --> try: from rm_auth_tenant.policy.engine import invalidate; invalidate('rm_community')")
    print("   --> then re-run step 4 above to see if the result changes.")
