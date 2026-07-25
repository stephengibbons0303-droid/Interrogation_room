# Tech debt

Findings surfaced by the review gate that were not worth fixing inline, kept here
so they are not lost.

## Engine-trace endpoint exposes engine internals to the learner

- **Where:** `backend/sessions.py` — `GET /interviews/{id}/trace` (and the dev
  route `frontend/app/dev/trace/[id]`).
- **What:** the endpoint is guarded only by `_owned`, so any authenticated learner
  can fetch their own interview's decision trace — tactics, pressure/exculpation,
  Chen's arc, the one-shot flags. The README states the pedagogy is **hidden**
  ("The learner perceives a high-stakes conversation, not a lesson"), and this
  hands them the whole machine.
- **Why not fixed now:** it's dev/observability tooling and the intended user is
  the developer playing their own session. A proper fix is a role gate
  (`User.role in {"admin", "developer"}`), but no admin/developer role is
  provisioned yet, so adding the gate today would block everyone and break the
  tool. This needs a product decision on roles first.
- **Before any real deployment:** role-gate the endpoint (and the `/dev/trace`
  route), or strip it from production builds. The code comment on `get_trace`
  flags the same thing.
- Surfaced 2026-07-25 by `/code-review` (medium) on the live-engine-trace change.
