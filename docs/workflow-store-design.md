# RipenMango Workflow Store — Design Document (v0.4.1, for review)

**Scope of this doc:** design of `rm_workflow` — a Django app, installed from the
`rm_workflow_store` repo, whose *only* job is to persist workflow definitions,
packaged as a reusable library inside a modular monolith, in support of the
RipenMango SaaS + white-label strategy. Nothing here is implemented yet — this is
the review artifact.

**What changed in v0.4.1:** answered "is this easily pluggable later, or a
refactor?" for the not-yet-built `TenantRouter` — added as a pluggability
assessment in §4.3. Short version: mostly pluggable already, one real landmine
(`created_by`/`updated_by`'s hard FK to `User`) named explicitly rather than
glossed over. Nothing else changed from v0.4.

## §0. Answers to this round's 5 items — status of each

| # | Item | Status |
|---|---|---|
| 1 | "What does `TenantRouter` mean?" | Explained in §4.3 |
| 2 | Tenant sync via signal + centralized listener (monolith, for now) | Designed in §12 |
| 3 | Mixins (`RMPublicIdModel`, `RMSoftDeleteModel`) live in `drf_base` | Applied in §6.2, §11 |
| 4 | `Workflow` → `Stage` table back, saved independently per stage; whole-JSON accepted only on first create | Redesigned in §5, §10 |
| 5 | Confirmed: no per-version soft delete, only one version matters at a time | Locked in in §11 |

---

## 1. Product framing

RipenMango is being positioned as a BPM/orchestration platform (Appian/Zapier-class)
with a specific differentiator: **customers (or RipenMango itself) can build
white-labeled applications on top of the workflow engine**, rather than only using a
single canonical UI. That differentiator has a direct architectural consequence:

> The Workflow Store's API contract *is* the product surface for white-label builders.
> It needs to be stable, versioned, and UI-agnostic — it cannot assume the React Flow
> canvas is the only consumer.

## 2. What this app is / is not responsible for

**In scope**
- CRUD + versioning of Workflow definitions (Workspace → Workflow → WorkflowVersion → Stage)
- Structural validation of each stage's graph JSON (referential integrity within
  a stage, schema shape per node category)
- Serving definitions to: the canvas editor, an execution engine (future), and
  third-party/white-label consumers via API

**Explicitly out of scope** (per `CLAUDE.md`'s "Known Gaps" section — separate
concerns/apps, not this app's job)
- Workflow **execution** / orchestration runtime
- **Asset** (running instance) tracking and state
- Cross-workflow **triggering** logic
- **Auth**, tenancy resolution, permissions — consumed from `rm_auth`
- UI concerns (React Flow positions are stored as opaque data, not interpreted)

## 3. Position in the modular monolith

- Repo root: `rm_workflow_store` (matches the empty repo you already have).
- Installable Django app / pip package: **`rm_workflow`** — `pyproject.toml`
  project name `rm-workflow`, Python package `rm_workflow`, `INSTALLED_APPS`
  entry `"rm_workflow"`, mirroring `rm-auth`'s flat `rm_auth` package.
- Dependency direction: `rm_workflow` depends on `drf-base` and `rm-auth` (both
  as `file://...dist/*.whl` path dependencies during dev). Nothing in `drf_base`
  or `rm_auth` imports from `rm_workflow`. No sibling business app (execution
  engine, assets) is an import-time dependency of this app.

## 4. Base classes and conventions

### 4.1 `drf_base_app` base model classes

- **`RMAuditModel`** → `id` (`BigAutoField`), `created_at`, `updated_at`,
  `created_by`/`updated_by` (non-null FK to user, auto-populated from
  `AuditContext`). Every model here inherits this.
- No built-in soft-delete on `RMAuditModel` today — being added as
  `RMSoftDeleteModel` per your point 3, see §11.
- No built-in typed/public id today — being added as `RMPublicIdModel` per your
  point 3, see §6.2.
- Field types imported from `drf_base_app.models.fields`, not raw
  `django.db.models`, matching `rm_auth`'s style.
- `drf_base_app.models.indexes` — `TenantIndex`, `jsonb_gin_index`, and a
  soft-delete-aware partial `Index` — all directly relevant given how JSON-heavy
  this app is (§5, §7, §9).

### 4.2 `rm_auth` — tenant resolution

- `rm_auth.tenants.models.Tenant`: control-plane record, `id` is a `CharField`
  slug PK, not a synthetic id.
- Every tenant-scoped `rm_auth` model carries a plain
  `tenant_id = CharField(max_length=64, db_index=True)` — never an FK to `Tenant`.
- Resolved per-request via JWT claim (authenticated) or
  `TenantResolutionMiddleware` (pre-auth), landing on `request.tenant_id` /
  `SecurityContext.tenant_id`.

### 4.3 Reconciling row-level `tenant_id` with schema/DB-per-tenant — and what a "TenantRouter" actually is

Same reconciliation as before: every model carries a plain `tenant_id` CharField
for portability/filtering; physical isolation (which literal database a query
hits) is a separate concern, handled underneath the ORM.

**Plain-language explainer, since this term didn't land last time (your item 1):**
Django lets you register one or more **database router** classes
(`settings.DATABASE_ROUTERS`) that get consulted on every query. A router is just
a small class with methods like `db_for_read(model, **hints)` and
`db_for_write(model, **hints)` that Django calls before running a query, and
whatever database alias that method returns is where the query actually goes —
completely transparent to the rest of the code, which just calls
`Workflow.objects.filter(...)` as normal. A **`TenantRouter`** is a custom router
whose `db_for_read`/`db_for_write` look at "which tenant is this request for"
(read from a thread-local/contextvar the request middleware sets, the same place
`SecurityContext.tenant_id` comes from) and return a different database alias
depending on the tenant — e.g. `tenant_acme` gets routed to a
`acme_dedicated_db` connection, while a smaller tenant on the shared tier gets
routed to the default `shared_db` connection. That's the actual mechanism behind
"Tier A shared schema vs. Tier B/C schema/DB-per-tenant" — the application code
(this app's models, services, API) never has to know or care which tier a given
tenant is on; the router silently sends the query to the right place. It's
referenced in both `drf_base` and `rm_auth`'s own docstrings as living in
`platform_core.tenancy`, but that package isn't in either repo shared with me —
**still open**, see §15, since I can't confirm `rm_workflow` will actually plug
into that same router without seeing it.

**Pluggability assessment — how much of this needs refactoring once a router
does exist, since it doesn't today:**

Mostly none, because the `tenant_id`-as-CharField decision (§4.2) was already
made for exactly this reason — but there's one real landmine worth naming now
rather than discovering it later.

*Already safe, no refactor needed:*
- Every model reads/writes through the plain Django ORM
  (`Workflow.objects.filter(...)`) with no hardcoded `.using("default")`
  anywhere in this design — a router just intercepts those calls transparently
  once one exists.
- No hard FK to `Tenant` anywhere (that's the whole reason `tenant_id` is a
  CharField) — so there's no FK for a router to break by routing two related
  rows to different databases.
- The internal FKs that *do* exist (`Workflow → Workspace`, `Stage →
  WorkflowVersion`, etc.) stay safe under per-tenant routing, because every row
  in one tenant's object graph is created through the same request/tenant
  context and would always land on the same database connection — a router
  keyed on `tenant_id` naturally keeps them together.
- `allow_migrate()` — the part of a router that decides which apps' tables get
  created on which database — is a standard, well-worn Django pattern (it's how
  Django itself lets you keep `auth`/`contenttypes` on every database in a
  multi-db setup), not something exotic `platform_core` would have to invent.

*The one real landmine: `created_by`/`updated_by` on `RMAuditModel`.* These are
non-null **hard `ForeignKey`s to the User model** (§4.1) — used by every single
model in this app, since everything inherits `RMAuditModel`. A hard FK across
two different physical databases simply isn't possible in Postgres. The moment
a tenant is routed to its own isolated database (Tier B/C), one of two things
has to happen, and neither is free:
1. `rm_auth`'s `User`/`Tenant` tables get **replicated onto every tenant
   database** via `allow_migrate()` — the standard Django answer, but it means
   user data now needs a cross-database sync story, not just one source of
   truth.
2. Or `created_by`/`updated_by` get **loosened from a hard FK to a plain id
   field**, matching the `tenant_id` pattern — a change to `RMAuditModel`
   itself, in `drf_base`, affecting `rm_auth` too — not something `rm_workflow`
   can quietly work around on its own.

Recommend proceeding with `rm_workflow` against plain single-database Django now
— none of this blocks starting implementation. This landmine only matters
*when* `platform_core.tenancy` actually gets built, and it's the same landmine
for every app built on `RMAuditModel`, not something specific to this design —
worth a decision at that point, flagged again in §15.

### 4.4 Layered architecture + packaging convention

`rm_workflow` follows the same **api → services → repositories → models**
layering as `rm_auth`, enforced with an `import-linter` contract, domain-folders
each owning their own `models.py`/`repositories.py`, `services/` as the only
thing `api/views.py` may import. See §14 for the file tree.

---

## 5. Domain model — `Stage` is a row again, per your point 4

### 5.1 What changed and why

v0.3 collapsed everything below `WorkflowVersion` into one `definition` JSON
blob, flagging one cost explicitly: concurrent edits to two different stages of
the same draft would overwrite each other on save. Your point 4 resolves that by
bringing `Stage` back as its own row — each stage saved independently — while
still keeping nodes/edges as JSON *within* a stage (not the old `Step`/`Edge`
tables from v0.2). This is the middle ground between v0.2 (fully relational) and
v0.3 (fully JSON): the granularity that actually needs independent
save/concurrency (a stage) is a row; the granularity that's arbitrary and
frontend-shaped (what's inside a stage) stays JSON.

Your point 4 also draws a clean line for `Workflow` itself: saving `Workflow`
only ever touches its own metadata (`name`, `description`, `workspace`) — it
never touches stage content, so editing a workflow's name and editing a stage's
canvas are two independent operations that can't race each other.

### 5.2 The model

```text
Tenant (rm_auth's Tenant, CharField id — plus a local mirror, §12)
  └── Workspace (e.g. "HR", "Finance")
        └── Workflow (metadata only: name, description)
              └── WorkflowVersion (draft | published — a container, no content of its own)
                    └── Stage (name, description, order + its own graph JSON)
                          graph: {"nodes": [...], "edges": [...]}
```

#### `Workspace`
| Field | Type | Notes |
|---|---|---|
| *(RMAuditModel + soft-delete, §11)* | — | |
| `public_id` | CharField, unique | `ws_...`, §6 |
| `tenant_id` | CharField(64), db_index | plain field, per §4.2/§4.3 |
| `name` | CharField | e.g. "HR", "Finance" |
| `description` | TextField, blank | |
| Constraint | `UniqueConstraint(tenant_id, name)` | mirrors `rm_auth.User`'s `(tenant_id, username)` |

#### `Workflow`
| Field | Type | Notes |
|---|---|---|
| *(RMAuditModel + soft-delete)* | — | |
| `public_id` | CharField, unique | `wrf_...`, §6 |
| `workspace` | FK → `Workspace` | |
| `tenant_id` | CharField(64), db_index | denormalized from `workspace.tenant_id`, kept in sync at write time |
| `name` | CharField | |
| `description` | TextField, blank | |
| `current_version` | FK → `WorkflowVersion`, null | published (or latest draft) version |

#### `WorkflowVersion`
| Field | Type | Notes |
|---|---|---|
| *(RMAuditModel — no soft delete, see §11)* | — | |
| `public_id` | CharField, unique | `wfv_...`, §6 |
| `workflow` | FK → `Workflow` | |
| `tenant_id` | CharField(64), db_index | denormalized |
| `version_number` | PositiveIntegerField | monotonic per workflow |
| `is_published` | BooleanField | |
| `published_at` | DateTimeField, null | |
| Constraint | `UniqueConstraint(workflow, version_number)` | |

A `WorkflowVersion` is now purely a container/pointer — its content lives in its
`Stage` rows (reverse FK). Publish = create a **new** `WorkflowVersion` row and
duplicate all of the draft's `Stage` rows (each stage's `graph` JSON copied
as-is) onto it — copy-on-publish, same as before, just applied to stage rows
instead of one big document or three tables.

#### `Stage`
| Field | Type | Notes |
|---|---|---|
| *(RMAuditModel + soft-delete)* | — | |
| `public_id` | CharField, unique | `stg_...`, §6 |
| `workflow_version` | FK → `WorkflowVersion` | |
| `tenant_id` | CharField(64), db_index | denormalized |
| `name` | CharField | |
| `description` | TextField, blank | |
| `order` | PositiveIntegerField | tab ordering |
| `graph` | JSONField | `{"nodes": [...], "edges": [...]}`, shaped to match the frontend's per-stage `nodes`/`edges` arrays verbatim |

```json
{
  "nodes": [
    {"id": "node-1", "category": "action", "position": {"x": 40, "y": 80}, "data": {...}}
  ],
  "edges": [
    {"id": "edge-1", "source": "node-1", "target": "node-2", "data": {}}
  ]
}
```

Because `edges` and `nodes` now both live inside the *same* stage's JSON
document, an edge can never structurally reference a node in a different stage
— the old "same-stage" validation rule from v0.2 is now a structural fact of the
data shape, not something that needs checking (§9).

## 6. Identifiers — `id` / `public_id`

| ID | Type | Purpose |
|---|---|---|
| `id` | `BigAutoField` | internal PK, unchanged, matches `RMAuditModel` convention |
| `public_id` | `CharField(unique=True, db_index=True)` | API-facing identifier, export/import key, prefixed and COMB-encoded |

### 6.1 COMB-style UUID

A COMB ("combined") GUID interleaves a timestamp with random bits so the id is
both globally unique *and* mostly sortable/insert-friendly, unlike a fully random
UUIDv4 (a well-known B-tree index fragmentation problem at scale in Postgres):

```python
import os, time, uuid

def comb_uuid() -> uuid.UUID:
    ts_ms = int(time.time() * 1000).to_bytes(6, "big")  # 48-bit ms timestamp
    rand = os.urandom(10)                                 # 80 bits of randomness
    return uuid.UUID(bytes=ts_ms + rand)
```

### 6.2 Prefixed public ids — now in `drf_base` (your point 3)

```python
PUBLIC_ID_PREFIXES = {
    "workspace": "ws",
    "workflow": "wrf",
    "workflow_version": "wfv",
    "stage": "stg",
}

def generate_public_id(prefix: str) -> str:
    encoded = base32_crockford(comb_uuid().bytes).lower().rstrip("=")
    return f"{prefix}_{encoded}"
```

Per your point 3, `RMPublicIdModel` and `RMSoftDeleteModel` (§11) move into
`drf_base_app.models.base`, composable the same way `RMSluggedModel` already is
(`public_id_prefix = "wrf"` set per model, generated on first save). This is a
change to a shared library that `rm_auth` also depends on, so it needs its own
version bump/release in `drf-base` before `rm_workflow` can depend on the new
version — worth sequencing as its own small PR against `drf-base` before
`rm_workflow`'s models start using it, rather than developing both in lockstep.
`rm_workflow`'s own `PUBLIC_ID_PREFIXES` dict (which prefix maps to which of
*this app's* models) still lives locally in `rm_workflow`, since `drf_base`
shouldn't need to know about workflow-specific model names — only the generic
mixin/generator function belongs there.

## 7. Why `Workflow`/`WorkflowVersion`/`Stage` are rows, but node/edge internals are JSON

`Workspace`/`Workflow`/`WorkflowVersion`/`Stage` are rows because each is
something the *product* needs to address, list, rename, reorder, or save
independently: list workflows in a workspace, list/reorder stages in a tab bar,
save one stage without touching its siblings (your point 4), check
`is_published`, soft-delete a workflow. None of that requires looking inside a
stage's contents. What's *inside* a stage — nodes, edges, positions, node
`data` — stays JSON because it's arbitrary, frontend-shaped, and only ever
interpreted by the canvas or the parser service, never queried relationally by
this app on its own.

## 8. Node category (confirmed, unchanged)

`category` stays a plain string inside each node's JSON, validated against a
fixed set (`input/process/output/decision/custom/action/condition/transition`,
matching the frontend) by the parser service, not a DB registry. Deferred, per
your earlier answer — a natural future migration if a white-label tenant needs
custom categories.

## 9. Validation (via `GraphParser`, not DB constraints)

- Each node's `data` validated against a JSON schema keyed by `category` (§8).
- Every edge's `source`/`target` must reference a node `id` present in that
  *same stage's* `graph.nodes` — this is now a structural guarantee of the data
  shape (§5.2), not a cross-document check, so validation is just "does this id
  exist in this JSON array," no cross-stage lookup needed.
- Workflow Trigger's `targetWorkflowId` (a node's `data` field) validated by
  looking up a `Workflow` by `public_id` and checking `tenant_id` matches — a
  plain lookup, not an FK.

## 10. API surface (DRF, via `drf_base`)

- `POST /workflows/` — creates `Workflow` + an initial draft `WorkflowVersion`.
  Body is normally just `{name, description, workspace}`. Per your point 4, it
  **may optionally** include a full `stages: [...]` payload for first-time
  bootstrap (e.g. duplicating a template, or an import) — if present, the
  service validates and creates all `Stage` rows for that draft version in one
  transaction. This is a **create-time-only** allowance; it does not reopen a
  whole-document write path for later edits.
- `GET/PATCH/DELETE /workflows/{public_id}/` — metadata only (`name`,
  `description`, `workspace`). Never touches stages.
- `POST /workflows/{public_id}/publish/` — copy-on-publish (§5.2).
- `GET /workflows/{public_id}/versions/` — version history.
- `GET /workflows/{public_id}/versions/{version_public_id}/stages/` — list
  stages (metadata + graph, for rendering the tab bar + canvas).
- `POST .../stages/` — add a stage.
- `PATCH .../stages/{stage_public_id}/` — rename/reorder a stage (metadata only,
  doesn't touch `graph`).
- `PUT .../stages/{stage_public_id}/graph/` — save **one stage's** `{nodes,
  edges}` — the primary, per-stage write path per your point 4. Two different
  stages save independently; there's no whole-workflow write for ongoing edits.
- `DELETE .../stages/{stage_public_id}/` — soft-delete a stage (§11).
- URL identifiers throughout are `public_id`, never the internal `id`.
- Tenant scoping: every queryset filtered by `tenant_id` from
  `SecurityContext`/`request.tenant_id` via a shared `TenantScopedQuerySetMixin`.

## 11. Soft delete, no hard delete

Applies to `Workspace`, `Workflow`, and `Stage`. New mixin,
`RMSoftDeleteModel`, now built in `drf_base_app.models.base` per your point 3:

- `deleted_at = DateTimeField(null=True, blank=True, db_index=True)`
- Default manager excludes `deleted_at__isnull=False` rows; an `.all_objects`
  manager exists for admin/audit access.
- `.delete()` overridden to set `deleted_at = now()` instead of issuing a
  `DELETE`; `.hard_delete()` is an explicit, rarely-called escape hatch for
  actual erasure requests, not exposed via the API.
- Indexed via `drf_base_app.models.indexes.Index`'s existing
  `deleted_field="deleted_at"` partial-index convention (§4.1).

**`WorkflowVersion` is the one exception — confirmed, per your point 5:** no
`deleted_at` on `WorkflowVersion` itself. Your reasoning — only one version
matters at a time (the current draft, or the current published version) — means
there's no meaningful "soft-delete an old version" operation to support; a
`Workflow`'s soft-delete already makes all its versions unreachable through the
normal API, which is sufficient.

## 12. Local `Tenant` model + sync (your points 1 & 2)

`rm_workflow` gets its own thin, local `Tenant` mirror, same shape as
`rm_auth.tenants.models.Tenant`, not imported from it:

```python
# rm_workflow/tenants/models.py
class Tenant(RMAuditModel):
    id = models.CharField(max_length=64, primary_key=True)  # same slug as rm_auth's
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)

    class Meta:
        app_label = "rm_workflow"
        db_table = "rm_workflow_tenant"
```

**Sync mechanism — signal-based, per your point 2**, since everything currently
sits in one monolith/database: a `post_save` receiver on
`rm_auth.tenants.models.Tenant` upserts the local mirror. Per your note to keep
this as a **centralized listener** rather than one-off receivers scattered per
app (useful the moment a second app besides `rm_workflow` also wants a local
`Tenant` mirror), this lives in `drf_base` as a small, reusable piece rather than
duplicated per consuming app:

```python
# drf_base_app/tenancy/sync.py
class TenantMirrorRegistry:
    """Apps register their local Tenant model once; a single post_save
    receiver on rm_auth.tenants.models.Tenant fans out to every registered
    mirror, instead of each app wiring its own signal by hand."""

    _mirrors: list[type] = []

    @classmethod
    def register(cls, mirror_model):
        cls._mirrors.append(mirror_model)
        return mirror_model


@receiver(post_save, sender="rm_auth.Tenant")
def _sync_all_mirrors(sender, instance, **kwargs):
    for mirror_model in TenantMirrorRegistry._mirrors:
        mirror_model.objects.update_or_create(
            id=instance.id,
            defaults={"name": instance.name, "is_active": instance.is_active},
        )
```

```python
# rm_workflow/tenants/models.py
@TenantMirrorRegistry.register
class Tenant(RMAuditModel):
    ...
```

Registered in `rm_workflow/apps.py`'s `ready()` so the mirror is wired up on
app startup. This is a same-process/same-database assumption (it relies on
`rm_workflow` and `rm_auth` sharing a Django signal bus), which is fine for the
monolith today — per your note, revisit if/when `rm_auth` and `rm_workflow` are
ever deployed as genuinely separate processes rather than apps in one project.

## 13. Migrations

Per your note that you're in development phase and regenerate migrations freely:
this doc assumes migrations will be squashed/finalized once the schema is
approved here, not before.

## 14. Project structure

```text
rm_workflow_store/                        # repo root
├── pyproject.toml                        # project name "rm-workflow"; packages: rm_workflow*
├── README.md
├── manage.py                              # dev harness only, excluded from the wheel
├── config/                                # dev-only Django project (settings/urls)
│   ├── settings.py
│   └── urls.py
├── rm_workflow/                           # the installable app package
│   ├── __init__.py
│   ├── apps.py                            # registers Tenant mirror in ready(), §12
│   │
│   ├── tenants/                           # local Tenant mirror, §12
│   │   ├── models.py
│   │   └── repositories.py
│   │
│   ├── workspaces/                        # Workspace, §5.2
│   │   ├── models.py
│   │   └── repositories.py
│   │
│   ├── workflows/                         # Workflow, WorkflowVersion, §5.2
│   │   ├── models.py
│   │   └── repositories.py
│   │
│   ├── stages/                            # Stage (+ its graph JSON), §5.2
│   │   ├── models.py
│   │   └── repositories.py
│   │
│   ├── services/                          # the ONLY thing api/ may import (import-linter contract)
│   │   ├── workflow_service.py            # create/update workflow metadata, workspace scoping
│   │   ├── version_service.py             # publish / copy-on-publish
│   │   └── graph_service.py               # GraphParser — validates/reads/writes one stage's `graph` JSON (§7, §9)
│   │
│   ├── validation/
│   │   └── category_schemas.py            # per-category JSON-schema validation (§8, §9)
│   │
│   ├── api/
│   │   ├── serializers.py
│   │   ├── views.py                       # imports services/ only
│   │   └── urls.py
│   │
│   ├── migrations/
│   └── tests/
│
├── rm_workflow_testkit/                   # optional, mirrors drf_base_testkit's pytest-plugin pattern
│   └── plugin.py
│
└── dist/                                  # built wheels
```

`drf_base` also gains (separate small PR, per §6.2):

```text
drf-base/drf_base_app/
├── models/base.py           # + RMPublicIdModel, RMSoftDeleteModel
└── tenancy/
    └── sync.py               # + TenantMirrorRegistry, §12
```

`import-linter` contract:

```toml
[tool.importlinter]
root_package = "rm_workflow"

[[tool.importlinter.contracts]]
name = "Layered architecture"
type = "layers"
layers = [
    "rm_workflow.api",
    "rm_workflow.services",
    "rm_workflow.workspaces | rm_workflow.workflows | rm_workflow.stages | rm_workflow.tenants",
]
```

## 15. Remaining open questions

1. **`platform_core.tenancy` / `TenantRouter`** (§4.3) — doesn't exist yet, and
   that's fine — it's pluggable later with one known exception
   (`created_by`/`updated_by`'s hard FK to `User`, needs either cross-DB
   replication or loosening the FK, whenever the router actually lands). No
   need to block implementation on this now.

---

**Next step:** nothing left is a blocker — the last open item (§15) is
explicitly "fine to defer." Ready to build the actual `rm_workflow` app —
models, serializers, viewsets, migrations, and tests — plus the small
`drf-base` PR for `RMPublicIdModel`, `RMSoftDeleteModel`, and
`TenantMirrorRegistry` — whenever you give the go-ahead.
