# rm_workflow_store

Workflow definition persistence layer for RipenMango -- a Django installable
app (`rm_workflow`) providing Workspaces, Projects, Workflows,
WorkflowVersions, and per-stage graph JSON, on top of `drf_base` and
`rm_auth_tenant`.

See `docs/workflow-store-design.md` (approved, v0.4.1) for the domain model,
`docs/tenant-isolation-decision.md` for the hybrid tenancy rationale, and
`docs/tier-b-implementation-plan.md` for how this repo fits into the
multi-repo split (`drf-base`, `rm_auth_project`, `rm_auth_tenant`, this repo).

## Layout

```
rm_workflow/
├── apps.py               # registers the local Tenant mirror (see tenants/models.py)
├── tenants/               # local Tenant mirror, synced from rm_auth.Tenant
├── workspaces/            # Workspace model + repository
├── projects/               # Project container model + repository
├── workflows/              # Workflow + WorkflowVersion models + repositories
├── stages/                 # Stage model + repository (graph JSON lives here)
├── validation/             # node category + per-category JSON-schema validation
├── services/                # WorkspaceService, WorkflowService, VersionService, GraphService/StageService
├── api/                     # serializers, viewsets/views, urls
└── models.py                # flat aggregator, mirrors rm_auth_tenant's convention
```

Layering (enforced via import-linter, see `pyproject.toml`):
`api` -> `services` -> `{tenants, workspaces, workflows, stages, validation}`.
Views never import models or repositories directly.

## Setup

```
./setup.sh          # venv + install deps
cp .env.example .env
# configure POSTGRES_* in .env -- also RM_CONNECTION_KEY_PROVIDER /
# RM_CONNECTION_MASTER_SECRET / RM_CONNECTION_KEY_VERSION, since rm_connection
# now runs in-process here (see "Installed apps" below) and reads those
# directly from os.environ, not from rm_connection_manager's own .env -- this
# process never touches that file. `manage.py runserver` doesn't auto-load
# .env, so either `set -a; source .env; set +a` first or export them
# directly.
python manage.py makemigrations rm_workflow
python manage.py migrate

# --- One-time tenant/role/permission bootstrap ---
# seed_roles creates the default tenant + a `platform_admin` role/persona +
# an admin user, but ONLY grants that role role:manage/persona:manage/
# user:manage -- see that command's own --help. It deliberately does NOT
# grant workspace/workflow/connection access, so the commands below are
# still required even on a freshly seeded tenant.
python manage.py seed_roles
python manage.py seed_node_types
python manage.py seed_connection_definitions

# Coarse, type-level gate (RequiresPermission) -- "can platform_admin reach
# this endpoint at all". This alone is enough to stop getting 403s, but
# list() will still come back empty -- see the object-level grants below.
python manage.py grant_permission --role platform_admin --resource workspace --action manage
python manage.py grant_permission --role platform_admin --resource project --action manage
python manage.py grant_permission --role platform_admin --resource workflow --action manage
python manage.py grant_permission --role platform_admin --resource workflow --action edit
python manage.py grant_permission --role platform_admin --resource workflow --action view
python manage.py grant_permission --role platform_admin --resource workflow --action publish
python manage.py grant_permission --role platform_admin --resource workflow --action share
python manage.py grant_permission --role platform_admin --resource connection --action manage

# Object-level scoping (rm_auth_tenant.authorization.access_scope,
# resolve_allowed_roles) -- a SEPARATE axis from the `manage` grants above.
# Skipping these is the #1 cause of "200 OK but empty list" even though the
# rows exist: TenantAndAccessScopedFilterBackend scopes list()/retrieve() to
# entities the caller owns/was shared, and without owner_only/shared granted
# that resolves to nothing visible at all. See
# rm_auth_tenant/authorization/DESIGN.md's action-vocabulary table for the
# full explanation.
python manage.py grant_permission --role platform_admin --resource workspace --action owner_only
python manage.py grant_permission --role platform_admin --resource workspace --action shared
python manage.py grant_permission --role platform_admin --resource project --action owner_only
python manage.py grant_permission --role platform_admin --resource project --action shared
python manage.py grant_permission --role platform_admin --resource workflow --action owner_only
python manage.py grant_permission --role platform_admin --resource workflow --action shared
python manage.py grant_permission --role platform_admin --resource connection --action owner_only
python manage.py grant_permission --role platform_admin --resource connection --action shared

python manage.py grant_permission --role "tenant-administrator (auto-granted)" --resource project --action owner_only
python manage.py grant_permission --role "tenant-administrator (auto-granted)" --resource project --action shared

# Seeds the ConnectionDefinition catalog (http/postgres/sendgrid/aws/slack --
# see rm_connection/management/commands/seed_connection_definitions.py) so
# rm_workflow_client's "New Connection" provider picker has real rows to
# resolve against instead of "Unknown provider: <x>".
python manage.py seed_connection_definitions

python manage.py runserver
```

Instead of the manual `grant_permission` calls above, `rm_workflow_store`'s
own `config/settings.py` has an `RM_AUTH["DEFAULT_PERSONA_PERMISSIONS"]`
block (currently commented out) that auto-grants a list of `(resource,
action)` pairs to every default-persona user, present and future -- see
`rm_auth_tenant`'s own `config/settings.py` for the fully-populated version
of that block (workspace/workflow entries) as a template, and extend it with
the same `connection` entries granted manually above. Uncommenting and
extending it there is less error-prone for a team than re-running
`grant_permission` by hand on every new environment, but the manual commands
above work either way and are what actually shape a specific role today.

This repo's own `config/settings.py` is a standalone test harness only (same
convention as `rm_auth_tenant`'s harness) -- a consuming platform project
defines its own settings and installs `rm_auth`, `rm_auth_tenant`, and
`rm_workflow` together.

### Installed apps

`rm_connection` (source: `rm_connection_manager`, a separate repo) is also
installed here as a dependency, alongside `rm_workflow`'s own app --
mounted at `api/connections/` in `config/urls.py`. It's consumed as a built
wheel (`pip install .../rm_connection_manager/dist/rm_connection-*.whl`),
not an editable install, so changes made in that repo's source need a
rebuild + reinstall here before they take effect:

```
cd ../rm_connection_manager && source .venv/bin/activate && python -m build --wheel
cd ../rm_workflow_store && source .venv/bin/activate
pip install --force-reinstall --no-deps ../rm_connection_manager/dist/rm_connection-0.1.0-py3-none-any.whl
```

## API surface (see docs/workflow-store-design.md §10)

- `GET/POST /api/workflow/workspaces`, `GET/PATCH/DELETE /api/workflow/workspaces/<id>`
- `GET/POST /api/workflow/projects` (requires a `workspace`),
  `GET/PATCH/DELETE /api/workflow/projects/<id>`
- `GET/POST /api/workflow/workflows` (optional `?workspace=<id>` or
  `?project=<id>` filter; `project` is optional on create),
  `GET/PATCH/DELETE /api/workflow/workflows/<id>`
- `POST /api/workflow/workflows/<id>/publish` -- copy-on-publish (§5.2)
- `GET /api/workflow/workflows/<id>/versions`
- `GET/POST /api/workflow/workflows/<id>/versions/<version_id>/stages`
- `GET/PATCH/DELETE /api/workflow/workflows/<id>/versions/<version_id>/stages/<stage_id>`
- `PUT /api/workflow/workflows/<id>/versions/<version_id>/stages/<stage_id>/graph`

Interactive docs at `/api/docs/` once the harness is running.

## Known follow-ups

- Migrations aren't generated yet -- run `makemigrations rm_workflow` against
  a real Postgres instance once dependencies are installed.
- `validation/category_schemas.CATEGORY_SCHEMAS` is intentionally empty --
  the per-category node `data` shapes are frontend-owned and not finalized
  in the design doc; populate it as those stabilize.
- No `tests/` suite yet (only the module structure exists) -- worth mirroring
  `rm_auth_tenant`'s `conftest.py`/`tests/factories.py` pattern once there's a
  security-context test fixture story for this app.


## build and update dependency 
cd /Users/lsharma/personal/rm_auth_tenant
rm -f dist/rm_auth_tenant-0.1.0*        # clear the stale artifacts
python -m build --wheel                 # or: pip wheel . -w dist --no-deps

cd /Users/lsharma/personal/rm_workflow_store
source .venv/bin/activate
pip install --force-reinstall --no-deps \
  /Users/lsharma/personal/rm_auth_tenant/dist/rm_auth_tenant-0.1.0-py3-none-any.whl