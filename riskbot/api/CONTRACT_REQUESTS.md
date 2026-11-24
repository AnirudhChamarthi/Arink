# Contract requests from `riskbot/api`

None of these block the component; each is worked around locally.

## 1. Document `cors_origins` in the `riskbot.api` entry point (CONTRACT.md section 2)

**What.** The entry point table says `create_app(service: RunService) -> fastapi.FastAPI`; the API
implements `create_app(service, *, cors_origins: list[str] | None = None)`.
**Why.** Deployments other than the Vite dev server need another origin. The extra argument is
keyword-only with a default, so existing callers are unaffected.
**Proposed diff.**
```diff
-| `riskbot.api` | `create_app(service: RunService) -> fastapi.FastAPI` |
+| `riskbot.api` | `create_app(service: RunService, *, cors_origins: list[str] \| None = None) -> fastapi.FastAPI` |
```

## 2. Document the HTTP-only error mappings (CONTRACT.md 4.5)

**What.** Errors that do not come from a `RiskbotError` have no contract code. The API maps:
request validation -> 422 `validation_failed`; body > 10 MB -> 413 `limit_exceeded`; unknown route ->
404 `not_found`; wrong method -> 405 `validation_failed`; anything else -> 500 `internal`.
**Why.** So the web UI and other clients can rely on these mappings. If the integrator prefers it, a
`method_not_allowed` code could be added to `ErrorBody.code`.
**Proposed diff (4.5).** Add: "Request validation errors are 422 `validation_failed` with
`details.errors = [{loc, msg, type}]`; bodies above 10 MB are 413 `limit_exceeded`; unexpected
exceptions are 500 `internal` with no internal detail."

## 3. `FakeRunService` records no audit events

**What.** `FakeRunService.audit_log` always returns `[]` because the fake never calls `append_audit`.
**Why.** Adapter tests and web fixtures cannot show a realistic audit trail. The API tests work around it
by appending an event to `service.store` directly.
**Proposed change.** Have `FakeRunService.start_run` / `submit_review` append `AuditEvent`s for each
status transition (`created`, `awaiting_review`, `approved`/`rejected`).
