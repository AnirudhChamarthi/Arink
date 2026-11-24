# Riskbot MCP server (`riskbot.mcp_server`)

An [MCP](https://modelcontextprotocol.io) server that lets agents such as Claude Desktop and Claude Code
run Riskbot analyses. It is a thin adapter over the contract's `RunService` port (CONTRACT.md 4.6 and 6.2):
every tool maps to one service method, and no risk logic lives here.

```python
from riskbot.mcp_server import create_server   # create_server(service: RunService) -> MCPServer
```

The composition root wires a concrete `RunService` and serves it over stdio:

```bash
python -m riskbot.app mcp [--db riskbot-v2.db]
```

## Tools

All tools take contract types as arguments (`Dataset`, `QuestionPlan`, `QuestionId`, ...), so the published
JSON Schema is complete, and return contract models as structured output. Tools returning a list or the
`Dataset` union are wrapped as `{"result": ...}`, because MCP structured content must be a JSON object.

| Tool | Arguments | Returns | `RunService` | Annotations |
|---|---|---|---|---|
| `list_questions` | none | `{"result": list[QuestionInfo]}` | `questions` | read-only |
| `list_models` | `question?` | `{"result": list[ModelSpec]}` | `list_models` | read-only |
| `get_sample_dataset` | `question` | `{"result": Dataset}` (synthetic) | `sample_dataset` | read-only |
| `validate_dataset` | `dataset` | `{"result": list[DataQualityFinding]}` | `validate` | read-only |
| `calculate` | `model_id, dataset, params?, seed?` | `ModelOutput` | `calc` | read-only |
| `start_run` | `question, dataset, plan?, seed?, wait?` | `RunRecord` | `start_run` | **state-changing** |
| `run_status` | `run_id` | `RunRecord` | `get_run` | read-only |
| `run_result` | `run_id` | `RunResult` | `get_result` | read-only |
| `get_trace` | `trace_id` | `Trace` | `get_trace` | read-only |
| `get_report` | `run_id` | `Report` | `get_report` | read-only |

*read-only* = `readOnlyHint=True, idempotentHint=True, openWorldHint=False`.
`start_run` = `readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False`
(each call creates a new run, nothing is overwritten or deleted).

**`start_run` defaults to `wait=True`**, unlike the REST API (`POST /v2/runs` returns 202 at once).
Agents almost always want the result next, so the call blocks until the run is `awaiting_review` or `failed`.
With `wait=false` it returns immediately and the agent polls `run_status`. The SDK runs tools in a worker
thread, so a long run does not block the server's event loop.

**No review or sign-off tool.** Approving or rejecting a run is human-only by design. The server
instructions tell the model to send the user to the web UI or REST API (`POST /v2/runs/{id}/review`) for that.

## Resources

| URI | MIME type | Content | `RunService` |
|---|---|---|---|
| `riskbot://models` | `application/json` | every `ModelSpec` as a JSON array | `list_models` |
| `riskbot://traces/{trace_id}` | `text/markdown` | the trace rendered as Markdown (below) | `get_trace` |
| `riskbot://reports/{run_id}` | `text/markdown` | `Report.markdown` | `get_report` |

A trace renders as: the title, trace id and model; assumptions; inputs; numbered steps, each with the formula as
display maths (`$$ ... $$`), the substitution, the value with its unit, a Markdown table for per-row detail, and a
note; final results; warnings; and the input hash. Numbers are printed with up to 10 significant digits, without
float noise. See `rendering.py`.

## Prompts

| Prompt | Question | Argument |
|---|---|---|
| `assess_market_risk` | `q1_market` | `dataset_hint?` |
| `assess_balance_sheet` | `q2_balance_sheet` | `dataset_hint?` |
| `assess_transition_risk` | `q3_transition` | `dataset_hint?` |

Each prompt returns one user message that tells the model which tools to call, in order: sample or build the
dataset, `validate_dataset`, `start_run`, `run_result`, `get_trace` for the numbers it cites, then `get_report`.
It also says what to report for that question and repeats the reporting rules. `dataset_hint` is a free-text
description of the user's data. Without it, the model is told to use the synthetic sample and to say that the
data is synthetic.

## Server instructions (summary)

- Quote numbers only from tool results or resources. Never compute or estimate new numbers.
- Every number has a `trace_id` (and step): cite it, and open the working with `get_trace`.
- Datasets with `synthetic=true` (all samples) must be described as synthetic.
- The qualitative assessment is judgment and must be presented that way.
- Review and sign-off are human-only. There is no tool for them.

## Errors

| Source | Client sees |
|---|---|
| `RiskbotError` from the service or the adapter (`NotFound`, `ValidationFailed`, `Conflict`, `LimitExceeded`) | tool result with `is_error=true` and text `"<code>: <message>"`, e.g. `not_found: unknown run 'run-9'` |
| pydantic `ValidationError` raised while building a request | `validation_failed: <field paths and messages>` |
| any other exception | `internal: unexpected server error (details in the server log)`, logged with traceback on the server only |
| arguments that do not match the input schema | rejected by the SDK before the tool runs: `is_error=true`, `Error executing tool <name>: <pydantic summary>` |
| resource reads | JSON-RPC error with the same `"<code>: <message>"` text (`not_found` maps to invalid params `-32602`) |

Before calling the service, the adapter also checks:
- `catalog.LIMITS`: positions and history days (market), balance-sheet items (assets, loan pools, deposits,
  wholesale lines and hedges), holdings (climate), and the plan size (product of grid dimensions plus extras)
  against `max_variations`;
- that the dataset `kind` matches the question, and that `plan.question` matches `question` (`validation_failed`).

## Client configuration

Run the commands below from the repository root, with the `riskbot` package importable (installed with
`pip install -e .`, or with `PYTHONPATH` set to the repository root).

### Claude Desktop

Add the server to `claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/`, Windows:
`%APPDATA%\Claude\`):

```json
{
  "mcpServers": {
    "riskbot": {
      "command": "python",
      "args": ["-m", "riskbot.app", "mcp", "--db", "/absolute/path/riskbot-v2.db"],
      "cwd": "/absolute/path/to/arink",
      "env": { "PYTHONPATH": "/absolute/path/to/arink" }
    }
  }
}
```

### Claude Code

```bash
claude mcp add riskbot -- python -m riskbot.app mcp --db /absolute/path/riskbot-v2.db
```

To share the server with the project, put a `.mcp.json` in the repository root:

```json
{
  "mcpServers": {
    "riskbot": { "command": "python", "args": ["-m", "riskbot.app", "mcp"] }
  }
}
```

Then try the prompt `/mcp__riskbot__assess_market_risk` or ask: *"Use riskbot to assess the market risk of the
sample portfolio and cite trace ids."*

## Files

| File | Purpose |
|---|---|
| `__init__.py` | exports `create_server` |
| `server.py` | tools, resources and prompts registration, error mapping, annotations |
| `guidance.py` | server instructions and prompt text |
| `rendering.py` | trace to Markdown |
| `limits.py` | `catalog.LIMITS` checks |
| `tests/` | in-process `mcp.Client` tests against `contract.fakes.FakeRunService` |

## Tests

```bash
python3 -m pytest riskbot/mcp_server
python3 -m pytest riskbot/contract/tests/test_architecture.py -k mcp_server
```

## Known limitations

- `get_trace` and `riskbot://traces/...` serve traces stored with a run's result. Traces from `calculate`
  come back inline in its `ModelOutput` and cannot be looked up by id afterwards, because the store indexes
  traces only when a run result is saved.
- `use_llm` is not exposed by `start_run`, because CONTRACT.md 6.2 lists no such argument. MCP runs never use
  an LLM drafter.
- `list_runs` and `audit_log` are not exposed, because CONTRACT.md 6.2 does not list them.
- Schema-level argument errors carry the SDK's message format rather than `"<code>: <message>"`.
- `max_variations` is checked against an upper bound (the cartesian product before the planner removes
  duplicates), so a plan right at the limit may be rejected here even though the planner would accept it.
