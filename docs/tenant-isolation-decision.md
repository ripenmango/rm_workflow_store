# Tenant Isolation ("TenantRouter") — Design & Decision Document (v0.1)

**Purpose of this doc:** unlike the `rm_workflow` design doc, this isn't a build
plan yet — it's the input you asked for to **decide** whether to build tenant
isolation (schema-per-tenant / DB-per-tenant) now, or defer it. It lays out what
actually has to be built, in how many pieces, at what risk, and what each path
costs you if you pick it now vs. later. Section 9 is the actual decision
framework; everything before it is the grounding you need to use it.

**Where this doc should live long-term:** every repo I have access to
(`drf-base`, `rm_auth_project`) references a `platform_core.tenancy` package
and a `workflow-platform-architecture.md` doc as the real home for this design
— neither exists in any repo shared with me, so this is a fresh write-up, not a
transcription of something already decided. Once `platform_core` exists (or if
you'd rather this live in `rm_auth_project` since `Tenant` lives there), move
this doc there — it's saved in `rm_workflow_store/docs/` for now purely because
that's where I have write access and where the question came from.

---

## 1. Why this matters (the business framing, stated plainly)

The pitch, per your earlier note, is: *enterprise customers may not want to
share infrastructure with other tenants.* That's a real, common enterprise
requirement, but it's worth being precise about what it actually means in
practice, because "isolation" isn't one thing — vendors sell (and enterprise
security/procurement teams ask for) several different levels of it, and they
cost very different amounts to build:

| What an enterprise buyer usually means | What it technically requires |
|---|---|
| "Our data is logically separated, you can't accidentally query across tenants" | Already true today (§4, `rm_auth`'s existing `tenant_id`-filtering convention) — this is **Tier A**, and it's not a selling point that requires new infrastructure, it's already the baseline. |
| "Our data lives in its own namespace, a bug in your app can't leak into it" | **Tier B: schema-per-tenant** — same database server, different Postgres schema per tenant. |
| "Our data is physically on separate infrastructure, possibly for compliance/residency" | **Tier C: database-per-tenant** (sometimes even server-per-tenant/region-per-tenant). |

The important, decision-relevant fact: **most enterprise security
questionnaires and contracts are satisfied by Tier B**, not Tier C. Tier C is
usually reserved for the largest accounts, or specific regulatory drivers (data
residency law requiring a specific country/region, HIPAA/FedRAMP-style
segregation requirements, or a contractual demand for physically separate
infrastructure). That distinction matters a lot for "build now vs. later" —
they're not the same amount of work, and you may not need the more expensive
one yet.

## 2. Terminology precision — "TenantRouter" was doing double duty

In the earlier docs I used "TenantRouter" loosely to mean "the thing that makes
Tier B/C work." That's imprecise enough to matter for a real decision, so
here's the correction:

- **Tier B (schema-per-tenant) is *not* implemented with Django's
  `DATABASE_ROUTERS` mechanism at all.** It's implemented by dynamically
  changing the Postgres **`search_path`** on a connection before running a
  query (`SET search_path TO tenant_acme, public;`), so the *same* Django
  connection to the *same* database transparently sees a different set of
  tables depending on which schema is active. This is what the mature
  open-source library `django-tenants` (formerly `django-tenant-schemas`)
  does, via middleware that sets the schema for the duration of a request.
- **Tier C (database-per-tenant) is what an actual Django `DATABASE_ROUTERS`
  class is for** — a router's `db_for_read`/`db_for_write` return a different
  database *alias* (a genuinely separate connection, potentially a separate
  physical server) depending on the current tenant.

So "build the TenantRouter" really means two different, independently
adoptable pieces of work, not one:

```text
Tier A (today)      →  no new code — tenant_id CharField + query filtering
Tier B (schema)     →  search_path–switching middleware (buy: django-tenants, or build)
Tier C (database)   →  a real Django DATABASE_ROUTERS class (must build/adapt — no drop-in for your layered/modular-monolith shape)
```

## 3. What each tier actually requires

### 3.1 Tier A — already done, described here only for contrast
Every tenant-scoped model has `tenant_id = CharField(...)`; every
repository/service method takes `tenant_id` and filters by it
(`rm_auth`'s `role-creation-and-tenant-model.md` §4 documents this in detail —
unique constraints scoped to `(tenant_id, name)`, no cross-tenant query path
anywhere). No new infrastructure — this is the floor everything else builds on.

### 3.2 Tier B — schema-per-tenant
- A `search_path`-switching request middleware, resolving the current schema
  from `request.tenant_id` (same source `TenantResolutionMiddleware` already
  populates today).
- Django app split into **shared apps** (migrated once, into the `public`
  schema — e.g. `rm_auth`'s `Tenant` row itself, and, importantly, `User` — see
  §4) and **tenant apps** (migrated once *per tenant schema* — `rm_workflow`'s
  `Workspace`/`Workflow`/`WorkflowVersion`/`Stage`).
- A **provisioning step**: creating a new tenant now means creating a new
  Postgres schema and running tenant-app migrations against it, in addition to
  the `Tenant` row itself — this slots directly into the existing
  `seed_roles` bootstrap command (`role-creation-and-tenant-model.md` §3.1),
  which would grow a "create schema + migrate" step before it creates the
  `Tenant` row.
- **Build vs. buy:** `django-tenants` already solves the middleware, the
  shared/tenant app split, and per-schema migration commands. Building this
  from scratch means re-implementing a library that's been handling exactly
  this for years — worth treating as a genuine buy-vs-build decision (§5), not
  assuming custom code is the only option.

### 3.3 Tier C — database-per-tenant
- A `TenantRegistry` (in `platform_core.tenancy` or wherever this lands) that
  maps `tenant_id → database alias`, with each alias's connection
  parameters resolvable at runtime (not just hardcoded in `settings.DATABASES`
  at process start, since new tenants get provisioned without a redeploy).
- A `TenantRouter(object)` implementing `db_for_read`, `db_for_write`,
  `allow_relation`, and `allow_migrate`, reading the active tenant from the
  same request-scoped context as Tier B.
- Dynamic database registration — Django's `settings.DATABASES` is normally
  static at process boot; onboarding a new Tier C tenant without restarting
  every process needs either a periodic settings-refresh mechanism or a
  connection-pool-per-tenant abstraction layered on top of Django's
  connection handling. This is the part with no mature drop-in library for a
  layered/modular-monolith shape like yours — it's the genuinely custom,
  higher-risk piece.
- Provisioning a Tier C tenant means standing up an actual new database
  (potentially on new infrastructure), running full migrations against it, and
  registering it in the `TenantRegistry` — meaningfully heavier ops than Tier
  B's "create a schema" step.

## 4. The `created_by`/`updated_by` landmine, precisely, per tier

This is worth restating with the precision this doc is for, since it changes
materially by tier — the earlier docs treated it as one landmine, but it's
really only sharp in one of the three tiers:

- **Tier A:** no issue — one database, the FK always resolves.
- **Tier B (schema-per-tenant): mostly no issue.** Postgres allows foreign keys
  **across schemas within the same database** — a tenant-schema `Workflow` row
  can FK to a `public`-schema `User` row without any special handling, as long
  as `User` is one of the shared/`public`-schema apps (which it should be —
  keeping `User`/`Tenant` in the shared schema and only tenant-scoped business
  data in per-tenant schemas is the standard `django-tenants` pattern, and it's
  also consistent with how `rm_auth` already models things: one central login
  per user, not per-schema duplicated accounts). This is a genuinely good
  reason to prefer Tier B over jumping straight to Tier C if logical isolation
  is the actual requirement.
- **Tier C (database-per-tenant): the real landmine.** A hard FK genuinely
  cannot cross two separate physical databases in Postgres. If `User`
  is Tier A/shared (one physical DB) but a `Workflow` row is Tier C (its own
  physical DB), `created_by` can't be a real FK constraint anymore for that
  tenant's rows. Two ways out, same two options as before, now precisely
  scoped to Tier C only:
  1. Replicate `User`/`Tenant` into every Tier C tenant's database (a sync
     story, likely the same signal-based mirroring pattern already designed
     for `rm_workflow`'s local `Tenant` in the other doc — reusable
     infrastructure, not a one-off).
  2. Loosen `created_by`/`updated_by` from a hard FK to a plain id field for
     any model that might live outside the shared database — a change to
     `RMAuditModel` in `drf_base`, needed only if you actually adopt Tier C.

## 5. Build vs. buy for Tier B

Worth treating as a real decision rather than assuming custom code, since a
mature library exists:

| | Build custom (`platform_core.tenancy`, from scratch) | Adopt `django-tenants` |
|---|---|---|
| Middleware, shared/tenant app split, migration commands | All custom, all untested against production edge cases | Battle-tested, used in production by many multi-tenant SaaS products |
| Fit with your existing layered architecture (`rm_auth`'s api→services→repositories→models, `import-linter` contracts) | Full control to match exactly | Needs adapting — `django-tenants` has its own opinions about `SHARED_APPS`/`TENANT_APPS` settings shape; integrating it under your layering convention takes some glue, but it's glue, not a rewrite |
| Ongoing maintenance | You own every bug, including ones the library already fixed years ago | Community-maintained; you take dependency risk instead (project health, release cadence) |
| Time to a working Tier B | Weeks, and likely a few production surprises the first time a real tenant migration runs mid-traffic | Days, since the hard parts (search_path switching correctness, migration-per-schema tooling) are already solved |
| Differentiation value | None — isolation *mechanism* isn't customer-visible; only the *outcome* (my data is isolated) is | Same outcome, faster |

**My honest read:** for Tier B specifically, building custom buys you nothing
the customer can see, and costs real time re-solving problems `django-tenants`
already solved. Tier C is different — there's no equivalent mature library for
true DB-per-tenant with dynamic tenant provisioning in a modular monolith, so
that piece is more legitimately custom work regardless of path.

## 6. Effort/risk by path

| Path | What you get | Rough effort | Risk |
|---|---|---|---|
| **A — do nothing now** | Nothing new; Tier A (already-true logical isolation) is what you sell today | None | Low — but see §11 for hygiene to maintain so this stays cheap to add later |
| **B — adopt `django-tenants` now** | Real Tier B (schema-per-tenant) — likely enough for most enterprise security questionnaires | Small-to-medium: settings restructuring (`SHARED_APPS`/`TENANT_APPS`), middleware wiring, provisioning step added to `seed_roles`, `created_by`/`updated_by` need no change (§4) | Low-to-medium — mostly integration risk (fitting it under your existing layering/import-linter conventions), not novel-mechanism risk |
| **C — build full custom `platform_core.tenancy` (Tier B + Tier C) now** | Both tiers, fully custom, matched exactly to your architecture | Large: `TenantRegistry`, `TenantRouter`, dynamic connection registration, provisioning tooling for real database creation, `RMAuditModel` FK decision (§4) | Higher — the dynamic-connection-registration piece (§3.3) has no drop-in solution; this is the part that could easily eat weeks and surface production edge cases (connection pool exhaustion, migration-mid-traffic, etc.) |

## 7. What changes in existing apps, per path

- **Path A:** nothing changes anywhere. `rm_workflow` proceeds exactly as
  designed in the other doc.
- **Path B:** `rm_auth` and `rm_workflow` both need their `INSTALLED_APPS`
  entries reclassified as shared vs. tenant apps; `seed_roles` gains a
  "provision schema + migrate" step before creating the `Tenant` row;
  `TenantResolutionMiddleware` gets a companion (or is extended) to also set
  `search_path`. No changes to `RMAuditModel`.
- **Path C:** everything in Path B, plus: `drf_base` needs the
  `RMAuditModel` FK decision made (§4) for any tenant that might land on Tier
  C, `platform_core.tenancy` needs to exist as a real package, and both
  `rm_auth` and `rm_workflow` need to depend on it for tenant resolution.

## 8. Provisioning a new tenant, concretely — ties into what already exists

Whichever path you pick, this connects directly to the `seed_roles`/
`create_role`/`create_user` bootstrap commands `rm_auth` already has
(`role-creation-and-tenant-model.md` §3). Today, `seed_roles` does:
`Tenant.objects.get_or_create(...)` → create admin role/persona → create admin
user, all in one transaction. Under Tier B, this needs one new step *before*
the transaction (schema doesn't exist inside a transaction the way rows do):
create the tenant's Postgres schema, run tenant-app migrations against it,
*then* run the existing `seed_roles` logic pointed at that schema. Under Tier
C, same shape, but "create the schema" becomes "provision a new database and
register it in the `TenantRegistry`" — a meaningfully heavier operational
step, likely worth its own dedicated command rather than folding into
`seed_roles` at all.

## 9. Decision framework — the actual questions to answer

This is the part meant to help you decide, not just more architecture:

1. **Do you have a specific enterprise prospect or customer asking for this in
   the next 1–2 quarters?** If yes, that's a real forcing function; if it's
   purely "enterprises will probably want this eventually," it's speculative
   and Path A (defer, keep hygiene per §11) is the YAGNI-consistent call —
   same principle you've applied to `rm_workflow`'s schema throughout.
2. **When they ask for isolation, do you actually know which tier they mean?**
   Worth checking directly against whatever security questionnaire or
   contract language is driving the request — "logically separated" (already
   true, Tier A) and "separate database" (Tier C) get asked for in very
   different words, and conflating them risks either overselling (promising
   Tier C, building Tier B) or overbuilding (building Tier C when Tier B would
   have closed the deal).
3. **Is Tier B alone commercially sufficient for the deals you're chasing?**
   Given §5's build-vs-buy read, Tier B via `django-tenants` is comparatively
   cheap — if it's enough, it's a much smaller bet than Tier C.
4. **How much runway does `rm_workflow` have before this becomes expensive to
   retrofit?** Per §11, if you maintain the hygiene (no cross-tenant joins,
   `tenant_id` on everything, no hardcoded `.using("default")`), adding Tier
   B/C later is additive, not a rewrite — so "we're mid-build on `rm_workflow`
   right now" is not by itself a reason to rush this.

## 10. My recommendation (input to your decision, not a mandate)

Given no confirmed enterprise deal is currently blocked on this (nothing in
our conversation so far suggests one is): **Path A now, revisit Path B when a
real deal or prospect asks for isolation stronger than "logically separated
by `tenant_id`."** When that happens, lead with `django-tenants` (Path B)
rather than custom-building — it's very likely sufficient for what's actually
being asked, cheaper, and lower-risk than Path C. Reserve Path C for a
specific, named requirement (a customer's compliance team explicitly requiring
physically separate infrastructure) rather than building it speculatively —
that's the one piece here with real, hard-to-de-risk custom work (§3.3), so
it's the last thing you want to have built for a hypothetical.

That said — you know your pipeline and what's actually being asked for in
sales conversations, which I don't have visibility into. If there's a
specific deal already contingent on this, that changes the answer to Path B
now, immediately.

## 11. If you defer (Path A) — hygiene to maintain so it stays cheap later

None of this is new work — it's just discipline to keep applying as
`rm_workflow` gets built, so that adding Tier B/C later is additive rather than
a retrofit:

- Keep `tenant_id` as a plain `CharField` everywhere, never an FK to `Tenant`
  (already the plan, per the other doc).
- Never write a cross-tenant query or join anywhere in `rm_workflow` or future
  apps — every repository method should take `tenant_id` and filter by it,
  the same discipline `rm_auth` already documented for itself.
- Never hardcode `.using("default")` or any specific database alias in
  application code — let everything go through the default connection
  unqualified, so a future router (Tier C) or schema-switch (Tier B) can
  intercept transparently.
- When `RMAuditModel`'s `created_by`/`updated_by` FK decision (§4) eventually
  needs making, make it once, deliberately, in `drf_base` — not per-app, and
  not implicitly by whichever app happens to need Tier C first.

## 12. If you proceed (Path B) — rough phased plan

1. Spike `django-tenants` against a copy of `rm_auth` + `rm_workflow` in
   isolation — confirm it fits the `import-linter`-enforced layering before
   committing, since that's the one real integration risk (§5).
2. Reclassify `rm_auth`'s `Tenant`/`User` as shared apps; `rm_workflow`'s
   `Workspace`/`Workflow`/`WorkflowVersion`/`Stage` as tenant apps.
3. Add the schema-provisioning step ahead of `seed_roles` (§8).
4. Migrate `TenantResolutionMiddleware` to also drive schema selection (or
   confirm `django-tenants`' own middleware supersedes it — avoid running two
   competing tenant-resolution mechanisms).
5. Ship to one real (or synthetic enterprise-shaped) tenant on its own schema
   before generalizing — validate the provisioning flow end-to-end before it's
   load-bearing for a real customer.

---

**Next step:** this doc is meant to end in a decision, not more design — once
you've worked through §9, tell me which path, and I'll turn whichever one you
pick into an actual implementation plan at the same level of detail as the
`rm_workflow` doc.
