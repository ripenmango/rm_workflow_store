# Tier B Implementation Plan — schema-per-tenant via `django-tenants` (v0.6)

**Decision this implements:** Path B from `tenant-isolation-decision.md` —
adopt `django-tenants` now, while it's cheap, rather than retrofitting later.

**Status as of v0.6: root cause found and fixed, confirmed against the real
installed `django_tenants` source (not guessed).** After `migrate_schemas`
stopped erroring, `rm_auth_tenant`'s tables still weren't being created —
silently no-op'd. Reading `django_tenants/routers.py` directly confirmed why:
stock `TenantSyncRouter.allow_migrate()` hard-codes
`installed_apps = settings.SHARED_APPS` whenever the current schema is
`"public"` — it deliberately blocks `TENANT_APPS` from ever migrating onto
`public`, full stop. That's incompatible with this plan's own hybrid model
(§1): we need `public` to hold `TENANT_APPS` data too, for every
not-yet-promoted tenant. **Fix:** a custom router,
`drf_base_app.tenancy.routers.HybridTenantSyncRouter` (subclasses the stock
one, only difference: on the public schema, allowed apps are
`SHARED_APPS + TENANT_APPS` combined, not `SHARED_APPS` alone).
`DATABASE_ROUTERS` in both harnesses now points at it instead of
`django_tenants.routers.TenantSyncRouter`. This is exactly the "needs
adapting, not a drop-in" integration risk flagged all the way back in
`tenant-isolation-decision.md`'s build-vs-buy section (§5) — now confirmed
real, not hypothetical. §2's settings snippet and §1 are updated below to
reflect this permanently; earlier sections written before this fix still
referenced the stock router and are now corrected in place rather than left
stale.

**Status as of v0.4: a real `CircularDependencyError` between
`rm_auth.0001_initial` and `rm_auth_tenant.0001_initial` surfaced by actually
running `manage.py runserver`, now fixed — see the rewritten §0.2. This
invalidates v0.3's §0.2/§6, which claimed the audit/`created_by` question
was "resolved, not a blocker" based on reasoning that turned out to be wrong
at the migration-graph level (schema co-location doesn't matter to Django's
migration dependency resolution, only declared FK targets do). Read the new
§0.2 if you read the old one.

A second, unrelated issue surfaced right after: `InconsistentMigrationHistory`
between `admin.0001_initial` and `rm_auth_tenant.0001_initial`. Root cause:
`rm_auth_project` and `rm_auth_tenant`'s dev harnesses both defaulted to the
*same* database (`appdb` on `localhost:5432`) — an oversight from copying one
harness's settings into the other without changing the database name, and
`rm_auth_tenant` never had its own `.env.example` at all. Two independent
Django projects sharing one physical `django_migrations` table corrupts both
projects' migration history. Fixed: `rm_auth_tenant`'s default `POSTGRES_DB`
is now `rm_auth_tenant_appdb`, and it has its own `.env.example`. **If you've
already run migrations against the shared `appdb`, that database's migration
history is now corrupted for both projects — drop and recreate it (or create
a fresh, separately-named database for each project per each repo's
`.env.example`) rather than trying to repair the existing one.**

A third issue: the old, undeleted `rm_auth/migrations/0002_seed_system_user.py`
seeded both the system user *and* the default tenant in one `RunPython`,
deliberately combined because `Tenant` used to require a `User` to exist
first (`RMAuditModel`'s NOT NULL `created_by`/`updated_by`). That coupling
is exactly what §0.2's fix removed -- `Tenant` no longer needs a `User` at
all. That old migration is now broken twice over (`apps.get_model("rm_auth",
"User")` -- `User` doesn't live there anymore; `Tenant.objects.create(...,
created_by_id=...)` -- those fields don't exist anymore either) and must be
deleted, not patched. Replaced with two fully independent seed migrations:
`rm_auth/migrations/0002_seed_default_tenant.py` (no `User` dependency at
all now) and `rm_auth_tenant/migrations/0002_seed_system_user.py` (the
system-user half, now scoped entirely within the app that actually owns
`User`).

**Status as of v0.3 (still current): the app split (§0.1/§3.3) is DONE**, and
done as **two separate repos/packages**, not one repo with two apps as v0.2
assumed — `rm_auth_tenant` now lives at `/Users/lsharma/personal/rm_auth_tenant`,
its own repo, own `pyproject.toml` (`rm-auth-tenant`), own dev harness
(`manage.py`/`config/`), depending on `rm_auth`'s wheel exactly the way
`rm_auth` itself depends on `drf_base`'s. This is a stronger version of the
boundary than v0.2 planned: "`rm_auth_tenant` depends on `rm_auth`, never the
reverse" is no longer just an `import-linter` rule inside one shared repo —
`rm_auth`'s own environment doesn't have `rm_auth_tenant` installed at all,
so a violation would be a hard `ImportError`, not just a lint failure. See
§0.1 for the full before/after.

**What changed in v0.2 (for history):** the shared-vs-tenant data
classification was corrected. v0.1 kept *all* of `rm_auth` (identity and
authorization data included) in the shared schema, isolating only
`rm_workflow`. That's wrong — `User`, `Role`, `Persona`, `Permission`,
`PolicyRule`, and `RoleAssignment` are tenant-specific data and belong in the
per-tenant schema alongside `rm_workflow`'s tables; only `Tenant`, `Domain`,
and `Action` are genuinely platform-wide. The rollout mechanics (§1's hybrid
model — most tenants share `public`, promotion is explicit and on-demand)
remain **unchanged** through both v0.2 and v0.3; only *what* moves into the
tenant schema, and now *where that code physically lives*, changed.

## 0. Shared schema vs. tenant schema — the corrected classification

Verified against the actual model code, not assumed — `rm_auth`'s own
`Action` docstring states the underlying principle directly: *"Not
tenant-scoped — the verbs available are a platform concept, only which role
can perform which verb is tenant-scoped."* That's precisely the line between
the two columns below.

| Shared schema (platform-wide metadata + auth bootstrap) | Tenant schema (business + tenant-specific data) |
|---|---|
| `Tenant` | `User`, `PasswordHistory` |
| `Domain` | `Role`, `Persona`, `UserPersonaAssignment` |
| `Action` (global verb vocabulary — no `tenant_id` field at all) | `Resource`, `Permission` (both carry `tenant_id`) |
| | `PolicyRule`, `RoleAssignment` (both carry `tenant_id`) |
| | *(already planned)* `rm_workflow`'s `Workspace`/`Workflow`/`WorkflowVersion`/`Stage` |

Everything in the right-hand column is either explicitly `tenant_id`-scoped
today, or (for `User`) uniquely constrained on `(tenant_id, username)` —
i.e. it's already conceptually tenant data, just currently stored in one
shared table filtered by `tenant_id` (Tier A). Moving it into the tenant
schema is a storage-location change, not a data-model change.

## 0.1 Why this requires splitting `rm_auth` into two Django apps

`django-tenants` assigns `SHARED_APPS`/`TENANT_APPS` **per Django app** (per
`INSTALLED_APPS` entry), not per model. Today every model above — `Tenant`
down to `RoleAssignment` — is one single app (`rm_auth`'s own `apps.py`
docstring: *"Single app_label for the whole library... one installable app
with one migrations history"*). To get the left column shared while the
right column is per-tenant, `rm_auth` has to become two apps:

- **`rm_auth`** (trimmed) — keeps only `tenants/` (`Tenant`, `Domain`) and the
  `Action` model. Stays `SHARED_APPS`.
- **`rm_auth_tenant`** (new) — takes `accounts/` (`User`, `PasswordHistory`),
  `roles/` (`Role`, `Persona`, `UserPersonaAssignment`), `permissions/`
  (`Resource`, `Permission` — *not* `Action`, which stays behind), and
  `policy/` (`PolicyRule`, `RoleAssignment`). Becomes `TENANT_APPS`, alongside
  `rm_workflow`.

Everything that *consumes* these models — `services/` (`authentication_service`,
`role_service`, `user_service`), `authentication/` (`jwt_authentication`),
`authorization/` (`policy_permission`), `jwt_auth/`, `middleware/`, and the
management commands (`seed_roles`, `create_role`, `create_user`,
`set_default_persona`, `rotate_signing_keys`) — needs its import paths updated
to point at `rm_auth_tenant` wherever they currently import from `accounts`,
`roles`, `permissions`, or `policy`. This is real, mechanical surface area
across most of `rm_auth`'s non-model code, not just the four model files —
worth sizing accordingly before starting.

**Why this is cheaper than it sounds, given where the project is:** because
you're still in development and regenerating migrations freely (per your
first note in `CLAUDE.md`), this is a clean cut, not a live migration-history
split — delete `rm_auth`'s existing migrations, regenerate fresh initial
migrations for both `rm_auth` (now small) and `rm_auth_tenant` (new). No
production data is being carried across this boundary yet.

## 0.2 The audit/bootstrap question this raises — CORRECTED in v0.4 (was wrong in v0.3)

**v0.3 claimed this was resolved. It wasn't** — the reasoning (schema
co-location) addressed the wrong layer. Django's migration dependency graph
has no concept of schemas at all; it only looks at declared FK targets. Here's
what actually happened:

`Tenant`/`Domain` (shared, in `rm_auth`) originally inherited `RMAuditModel`,
which gives every model `created_by`/`updated_by` as **hard `ForeignKey`s to
`settings.AUTH_USER_MODEL`**. Once `User` moved to `rm_auth_tenant` and a
consuming project sets `AUTH_USER_MODEL = "rm_auth_tenant.User"`, Django
auto-generates a migration dependency **from `rm_auth` onto `rm_auth_tenant`**
(so the `User` table exists before anything can FK to it) — the exact
reverse of `rm_auth_tenant`'s own dependency on `rm_auth` (via
`Permission.action` → `rm_auth`'s `Action`). Two apps each needing the other
first is an unresolvable cycle: `django.db.migrations.exceptions.
CircularDependencyError: rm_auth.0001_initial, rm_auth_tenant.0001_initial`.

**The actual fix:** `Tenant` and `Action` (the two shared models that
previously used `RMAuditModel`) now use **`RMTimeStampModel`** instead —
`created_at`/`updated_at` only, no `created_by`/`updated_by`, no FK to
`AUTH_USER_MODEL`, no cross-app migration dependency in that direction at
all. (`Domain` was already fine — it only ever inherited `DomainMixin`, never
`RMAuditModel`.) This does mean `Tenant`/`Action` no longer record *who*
created/updated them — an accepted, deliberate trade-off for a platform-level
bootstrap record, not something to route around with a workaround. If "who
provisioned this tenant" audit trail is wanted later, that's a separate,
non-FK field (e.g. a plain username string, same pattern as `tenant_id`
elsewhere in this whole project) — never a FK back into a `TENANT_APPS`
model, for exactly this reason.

**The broader lesson, worth generalizing:** *any* shared/platform model in
`rm_auth` must never use `RMAuditModel` (or anything else with a hard FK to
`settings.AUTH_USER_MODEL`) once `AUTH_USER_MODEL` points at a `TENANT_APPS`
model. This isn't unique to `Tenant`/`Action` — it's a standing constraint on
anything added to `rm_auth` going forward.

## 1. The hybrid model — unchanged from v0.1

`django-tenants` defaults to "every tenant gets its own schema." That's not
what you want for a self-serve/small-tenant product — provisioning a new
Postgres schema for every free-tier signup is real ongoing overhead for no
benefit. Instead:

- **One special tenant, `schema_name="public"`**, holds every tenant that
  hasn't been explicitly promoted — this is where `rm_auth_tenant`'s tables
  *and* `rm_workflow`'s tables are migrated (every `TENANT_APPS` table, not
  just `rm_workflow`'s), and rows there are still `tenant_id`-filtered
  exactly like today (Tier A behavior, unchanged, for everyone by default).
- **A tenant gets its own dedicated schema only when explicitly promoted**
  (§7) — that's the moment Tier B isolation actually kicks in for that one
  tenant, and it's an on-demand operation, not something every signup pays for.

This is the part of adopting `django-tenants` that isn't just "install the
library and flip a setting" — it's a deliberate customization on top of its
default all-tenants-get-a-schema assumption, and it's what makes doing this
now cheap rather than an ops burden on day one.

**Confirmed in v0.6, not just assumed:** the stock `TenantSyncRouter`
(`django_tenants.routers`) actively fights this hybrid model — its
`allow_migrate()` only permits `SHARED_APPS` on the `public` schema, full
stop, blocking `TENANT_APPS` there. Making this hybrid model actually work
required a custom router, `HybridTenantSyncRouter` (§2), not just this
section's settings. If you ever revert to the stock router, this hybrid
model silently stops working — `TENANT_APPS` migrations on `public` will
no-op rather than error, which is exactly what happened before this was
diagnosed.

## 2. Dependencies & settings

New dependency: `django-tenants` (added to `rm_auth`'s `pyproject.toml`,
since `Tenant`/`Domain` live there).

Settings changes — **these belong in whatever project actually composes
`rm_auth` + `rm_auth_tenant` + `drf_base` + `rm_workflow` into one deployable
Django settings file.** Still flagging plainly: **I don't have access to
that project.** `rm_auth_project`'s own `config/settings.py` explicitly says
*"A consuming platform project would NOT use this file"* — it's a standalone
test harness. Worth confirming whether that composing project exists
somewhere else, or needs to be created as part of this work.

```python
DATABASES = {
    "default": {
        "ENGINE": "django_tenants.postgresql_backend",  # was: django.db.backends.postgresql
        ...  # same NAME/USER/PASSWORD/HOST/PORT as today
    }
}

DATABASE_ROUTERS = ["drf_base_app.tenancy.routers.HybridTenantSyncRouter"]  # NOT django_tenants.routers.TenantSyncRouter -- see §1's correction, v0.6
# Required alongside the override above: django_tenants' own AppConfig.ready()
# otherwise demands the stock TenantSyncRouter specifically be present in
# DATABASE_ROUTERS (see django_tenants/apps.py) -- this setting is its
# documented escape hatch for a custom router.
TENANT_SYNC_ROUTER = "drf_base_app.tenancy.routers.HybridTenantSyncRouter"

TENANT_MODEL = "rm_auth.Tenant"
TENANT_DOMAIN_MODEL = "rm_auth.Domain"

SHARED_APPS = [
    "django_tenants",  # must come first
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.admin",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "django.contrib.messages",
    "rest_framework",
    "drf_spectacular",
    "drf_base_app",
    "rm_auth",             # trimmed: Tenant, Domain, Action only (§0)
]

TENANT_APPS = [
    "rm_auth_tenant",       # User, PasswordHistory, Role, Persona, UserPersonaAssignment,
                            # Resource, Permission, PolicyRule, RoleAssignment (§0)
    "rm_workflow",          # Workspace, Workflow, WorkflowVersion, Stage
]

INSTALLED_APPS = list(SHARED_APPS) + [app for app in TENANT_APPS if app not in SHARED_APPS]
```

**Correction, found by actually running the code:** `ENGINE`,
`DATABASE_ROUTERS`, `TENANT_MODEL`, `TENANT_DOMAIN_MODEL`, **and**
`SHARED_APPS`/`TENANT_APPS` themselves aren't only needed by "whatever
composes everything," as this section originally said — **any environment
that even installs `django_tenants`** needs all of these, including each
app's own standalone dev harness. Two separate things learned by hitting
real errors:
1. `django_tenants`'s `DomainMixin` builds a real `ForeignKey` field from
   `settings.TENANT_MODEL` at class-definition time — the moment
   `rm_auth.tenants.models` is imported by anything, anywhere — not lazily,
   only when `migrate_schemas` or real schema-switching runs.
2. `django_tenants`'s own `AppConfig.ready()` unconditionally checks that
   `TENANT_APPS` exists as a setting **and is non-empty** if `"django_tenants"`
   is itself registered in `INSTALLED_APPS` ("`TENANT_APPS is empty. Maybe
   you don't need this app?`"). Registering `django_tenants` as an app is
   only needed by an environment that actually runs
   `migrate_schemas`/schema-switching, i.e. one with a genuinely non-empty
   `TENANT_APPS`.

Both `rm_auth_project/config/settings.py` and `rm_auth_tenant/config/settings.py`
now define real `SHARED_APPS`/`TENANT_APPS` lists and derive `INSTALLED_APPS`
from them. `rm_auth`'s own harness has an empty `TENANT_APPS` (no
tenant-scoped app of its own installed) and, per point 2 above, does **not**
register `"django_tenants"` as an app at all — only the four settings, so
`Tenant`/`Domain`'s field construction still works. `rm_auth_tenant`'s
harness has a real `TENANT_APPS = ["rm_auth_tenant"]` and *does* register
`"django_tenants"`. Neither harness runs actual schema-per-tenant switching.

## 3. Model changes

### 3.1 `rm_auth.tenants.models.Tenant` gains `TenantMixin` — corrected in v0.4 (see §0.2)

```python
from django_tenants.models import TenantMixin
from drf_base_app.models.base import RMTimeStampModel  # NOT RMAuditModel -- see §0.2

class Tenant(TenantMixin, RMTimeStampModel):
    id = models.CharField(max_length=64, primary_key=True)  # unchanged
    name = models.CharField(max_length=255)                  # unchanged
    # ... existing fields unchanged ...

    # schema_name is added automatically by TenantMixin (unique CharField)

    auto_create_schema = False  # <-- the key customization, see §1/§7
    auto_drop_schema = False    # never auto-drop a tenant's schema on delete
```

### 3.2 New `rm_auth.tenants.models.Domain` — unchanged from v0.1

```python
from django_tenants.models import DomainMixin

class Domain(DomainMixin):
    class Meta:
        app_label = "rm_auth"
```

Populated with a placeholder, non-DNS-resolving domain per tenant
(`f"{tenant.id}.rm.internal"`) purely to satisfy the framework's requirement
— not real subdomain routing yet (deliberate stub, see v0.1 for the fuller
rationale, unchanged here).

### 3.3 New: `rm_auth_tenant` app — the actual split (new in v0.2)

Directory moves (physical relocation, not just an `app_label` change — each
Django app needs its own migrations history):

```text
rm_auth/                          rm_auth_tenant/           (new app)
  tenants/       (stays)            accounts/               (moved)
  permissions/                        models.py: User, PasswordHistory
    models.py: Action  (stays)      roles/                  (moved)
    Resource, Permission -->           models.py: Role, Persona,
        MOVE to rm_auth_tenant                    UserPersonaAssignment
  models.py      (trimmed)          permissions/            (moved, minus Action)
  apps.py        (unchanged label)    models.py: Resource, Permission
                                     policy/                 (moved)
                                       models.py: PolicyRule, RoleAssignment
                                     models.py               (new aggregator)
                                     apps.py                 (new AppConfig,
                                        app_label="rm_auth_tenant")
                                     migrations/              (new, fresh)
```

`db_table` names (e.g. `"rm_auth_user"`, `"rm_auth_role"`) can stay exactly
as they are — `db_table` is independent of `app_label`, so no column/table
renaming is forced by this move, only Python import paths and each model's
`Meta.app_label`.

**Everything that imports these models needs updating** — `services/`,
`authentication/`, `authorization/`, `jwt_auth/`, `middleware/`, and the
management commands all reference `accounts`/`roles`/`permissions`/`policy`
today; every one of those import paths becomes `rm_auth_tenant.accounts...`
etc. This is the bulk of the actual work in this plan — more files touched
than any other single step, even though each individual change (an import
line) is small.

## 4. Reconciling `django-tenants`' hostname-first design with `rm_auth`'s header/JWT resolution — unchanged from v0.1

`django-tenants`' standard middleware (`TenantMainMiddleware`) resolves the
tenant from the request's `Host` header via `Domain` rows. `rm_auth` already
resolves tenant from a header/JWT claim (`TenantResolutionMiddleware` →
`request.tenant_id`) — not being replaced. Fix: don't use
`TenantMainMiddleware`; a small custom middleware
(`drf_base_app.tenancy.schema_activation.SchemaActivationMiddleware`,
already built) does the schema switch keyed off `request.tenant_id` instead.
`Tenant` staying in the trimmed, shared `rm_auth` app (§0/§3.3) means this
middleware's lookup (`get_tenant_model().objects.get(id=request.tenant_id)`)
is unaffected by the app split — still a shared-schema lookup, exactly as
before.

## 5. Migrations

Two commands replace plain `migrate` (both from `django-tenants`):

- `migrate_schemas --shared` — migrates `SHARED_APPS` (the trimmed `rm_auth`,
  `drf_base_app`, Django's own apps) into the `public` schema. Run once.
- `migrate_schemas` — migrates `TENANT_APPS` (`rm_auth_tenant` **and**
  `rm_workflow`, now both) into **every existing tenant schema**, including
  `public` (since `public` also hosts every not-yet-promoted tenant's data,
  per §1). Run on every `rm_auth_tenant`/`rm_workflow` migration going
  forward, not just once.

Per §0.1: since you're still regenerating migrations freely, the practical
sequence is delete `rm_auth`'s current migration history, create the new
`rm_auth_tenant` app, then run `makemigrations` fresh for both apps before
the first `migrate_schemas --shared` + `migrate_schemas` pair.

## 6. `created_by`/`updated_by` — corrected in v0.4 (see §0.2 for what changed and why)

`Tenant`/`Action` no longer have `created_by`/`updated_by` at all (moved to
`RMTimeStampModel`, §0.2) — that's what actually fixes the migration cycle,
not schema co-location as v0.3 claimed. `rm_workflow`'s (and
`rm_auth_tenant`'s own internal, e.g. `Permission.role`) FKs to `User` are
unaffected by this — they resolve *within* whatever schema is currently
active, promoted or not, since `User` lives in `TENANT_APPS` alongside them.
The only models that needed changing were the two platform-level ones that
used to reach across the app boundary via the swappable `AUTH_USER_MODEL`.

## 7. Tenant provisioning — two paths now, where there was one

### 7.1 Ordinary tenant creation — unchanged in cost, one new field

`seed_roles` changes minimally: `Tenant.objects.get_or_create(id=tenant_id,
schema_name="public", ...)` — new tenants default straight into the shared
`public` schema, same as every tenant today. No new provisioning cost for
the common case.

### 7.2 Promoting a tenant to its own dedicated schema — the genuinely risky piece, now with more tables

New management command, `promote_tenant_to_dedicated_schema --tenant <id>`.
Same procedure as v0.1, with the table list in step 3 expanded to match
§0's corrected classification:

1. Generate a `schema_name` (e.g. `tenant_acme`), create the tenant's
   `Domain` stub (§3.2).
2. Create the physical schema and run `migrate_schemas --schema=<new_schema>`
   to lay down `TENANT_APPS` tables in it (empty, matching current
   migrations).
3. **Copy this tenant's existing rows** out of `public` (filtered by
   `tenant_id`) into the new schema's tables, in dependency order:
   `User` → `PasswordHistory` → `Role` → `Persona` → `UserPersonaAssignment`
   → `Resource` → `Permission` → `PolicyRule` → `RoleAssignment` →
   `Workspace` → `Workflow` → `WorkflowVersion` → `Stage`. More tables than
   v0.1's plan, same mechanism.
4. **Verify row counts match** between source (`public`, filtered by
   `tenant_id`) and destination (new schema, unfiltered) before touching
   anything in `public` — across *all* of the tables in step 3, including
   the identity/authz ones now in scope.
5. Only after verification: soft-delete the tenant's rows in `public`
   (never hard-delete — rollback safety net for a defined retention window).
6. Flip `Tenant.schema_name` to the new schema.

**Still recommend `--dry-run` first, and a communicated maintenance window**
— unchanged advice from v0.1, more consequential now that a tenant's user
accounts (not just their workflow data) are part of what's being moved: a
login landing mid-copy is a worse failure mode than a workflow-edit landing
mid-copy.

## 8. Validating the isolation claim

Unchanged from v0.1: after promoting a test tenant, confirm a raw SQL query
(bypassing the ORM and any `tenant_id` filtering) genuinely cannot see
another tenant's rows from the dedicated schema's connection — now covering
both identity/authz tables and `rm_workflow`'s tables, since both are in
scope as of §0.

## 9. Rollout checklist

1. Confirm where the composing platform settings file lives (§2's open item) — still open.
2. **DONE.** Split `rm_auth` → `rm_auth` (trimmed) + `rm_auth_tenant` (new,
   separate repo) per §0.1/§3.3 — model moves, `Meta.app_label` changes,
   import-path updates across `services/`, `authentication/`,
   `authorization/`, `jwt_auth/`, `middleware/`, management commands, tests,
   and `conftest.py`. Both repos have their own `pyproject.toml`,
   `import-linter` contracts, and dev harness now.
3. **DONE.** `django-tenants` dependency; `TenantMixin`/`Domain` changes in
   `rm_auth` (§3.1/§3.2).
4. **DONE.** `SchemaActivationMiddleware` in `drf_base` (§4).
5. **Not done — required before anything below can run:** rebuild `rm_auth`'s
   wheel (`dist/rm_auth-0.1.0-py3-none-any.whl` is stale — built before this
   split, so `rm_auth_tenant`'s `pip install -e ".[dev]"` would currently pull
   in the *old*, untrimmed `rm_auth`), delete `rm_auth`'s old migrations
   (`0001_initial.py`, `0002_seed_system_user.py` — they still reflect the
   untrimmed app), then `makemigrations` fresh for both `rm_auth` and
   `rm_auth_tenant` (§5).
6. `SHARED_APPS`/`TENANT_APPS` split, `migrate_schemas --shared` +
   `migrate_schemas` run once against existing data — blocked on step 1.
7. `seed_roles` updated for new tenants (§7.1) — **DONE**, verify no behavior
   change for ordinary tenant creation once step 5 is complete and both apps
   actually run.
8. Build `promote_tenant_to_dedicated_schema` with `--dry-run` (§7.2), test
   against a copied dataset — not started.
9. §8's raw-SQL isolation test, run against a real promoted test tenant — not started.
10. Only then: promote a real tenant, with a communicated maintenance window.

## 10. What this plan deliberately does not do

- Doesn't turn on real subdomain-based tenant resolution — the `Domain`
  model exists (framework requirement) but isn't wired to actual routing
  yet (§3.2).
- Doesn't build Tier C (database-per-tenant) — still explicitly deferred
  per the decision doc, unchanged by this plan.
- Doesn't attempt a zero-downtime migration-history split for `rm_auth` →
  `rm_auth_tenant` — relies on the dev-phase "regenerate migrations freely"
  allowance (§0.1); revisit this assumption once there's real production
  data that would need a careful live split instead.

---

**Next step:** the `rm_auth`/`rm_auth_tenant` app split (§0.1/§3.3/§9 step 2)
is the biggest remaining piece of actual work and the main blocker for
everything after it — ready to start on it whenever you say go.
