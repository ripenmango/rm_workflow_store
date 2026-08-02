# rm_workflow_store

Workflow definition persistence layer for RipenMango -- a Django installable
app (`rm_workflow`) providing Workspaces, Workflows, WorkflowVersions, and
per-stage graph JSON, on top of `drf_base` and `rm_auth_tenant`.

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
# configure POSTGRES_* in .env, then:
python manage.py makemigrations rm_workflow
python manage.py migrate
python manage.py runserver
```

This repo's own `config/settings.py` is a standalone test harness only (same
convention as `rm_auth_tenant`'s harness) -- a consuming platform project
defines its own settings and installs `rm_auth`, `rm_auth_tenant`, and
`rm_workflow` together.

## API surface (see docs/workflow-store-design.md §10)

- `GET/POST /api/workflow/workspaces`, `GET/PATCH/DELETE /api/workflow/workspaces/<id>`
- `GET/POST /api/workflow/workflows` (optional `?workspace=<id>` filter),
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
