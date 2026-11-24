# Contract requests from orchestration

None block this component; it is implemented against contract 2.0.0 as is.

## 1. Standard audit event vocabulary (non-blocking)

**What.** `AuditEvent.event` is a free string. Orchestration emits `run_created`, `status_changed`
(`detail.from`, `detail.to`, `detail.error`), `variations_failed`, `llm_draft_accepted`,
`llm_draft_rejected`, `llm_draft_failed`, `review_submitted`, `factor_edited`, `signed_off`,
`report_built` (details in `README.md`).

**Why.** The web UI and MCP adapters will render the audit log; without a listed vocabulary they must
guess or hard-code names from this package.

**Proposed diff.** Add to CONTRACT.md section 5 a table of these event names and detail keys (or a
`Literal` on `AuditEvent.event`).

## 2. Final status written after the report (clarification)

CONTRACT.md 4.4 lists `apply_edits -> signoff -> report`. Orchestration writes `approved`/`rejected`
at the end of `report`, after the report has been built and its headline verified, so a run is never
approved with a report that cannot be built. Propose a sentence in 4.4 saying so.
