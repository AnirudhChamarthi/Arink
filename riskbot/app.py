"""Composition root: the only place that knows concrete implementations.

    python -m riskbot.app api   [--host 127.0.0.1] [--port 8000] [--db riskbot-v2.db]
    python -m riskbot.app mcp   [--db riskbot-v2.db]          # stdio, for Claude Desktop / Claude Code
    python -m riskbot.app demo                                 # run all three questions on sample data
    python -m riskbot.app export                               # regenerate contract schemas and fixtures

Every component depends only on ``riskbot.contract``; this module wires them together.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from riskbot.contract.ports import RunService
from riskbot.contract.types import QuestionId

DEFAULT_DB = os.environ.get("RISKBOT_DB", "riskbot-v2.db")


def build_registry() -> Any:
    from riskbot import services
    from riskbot.core import balance_sheet, climate, market

    registry = services.registry()
    for package in (market, balance_sheet, climate):
        for model in package.models():
            registry.register(model)
    return registry


def build_service(
    db_path: str = ":memory:",
    checkpoint_path: str | None = None,
    drafter: Any = None,
) -> RunService:
    """Wire the real components into a RunService."""
    from riskbot import orchestration, qualitative, services
    from riskbot.core import balance_sheet, climate, market

    registry = build_registry()
    if checkpoint_path is None:
        checkpoint_path = ":memory:" if db_path == ":memory:" else db_path + ".checkpoints"
    return orchestration.run_service(
        registry=registry,
        planner=services.planner(),
        executor=services.executor(registry),
        comparator=services.comparator(),
        verifier=services.verifier(),
        store=services.sqlite_store(db_path),
        reporter=services.reporter(),
        assessor=qualitative.assessor(),
        samples={
            QuestionId.Q1: market.sample_dataset,
            QuestionId.Q2: balance_sheet.sample_dataset,
            QuestionId.Q3: climate.sample_dataset,
        },
        drafter=drafter,
        checkpoint_path=checkpoint_path,
    )


def _demo(service: RunService) -> None:
    from riskbot.contract.types import RunRequest

    for q in QuestionId:
        record = service.start_run(RunRequest(question=q, dataset=service.sample_dataset(q)), wait=True)
        print(f"\n== {q.value}: {record.status.value} ({record.n_variations} variations, run {record.run_id})")
        if record.error:
            print("   error:", record.error)
            continue
        report = service.get_report(record.run_id)
        for line in report.headline:
            print("  -", line)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m riskbot.app")
    sub = ap.add_subparsers(dest="cmd", required=True)
    api = sub.add_parser("api", help="serve the REST API")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8000)
    api.add_argument("--db", default=DEFAULT_DB)
    mcp = sub.add_parser("mcp", help="serve MCP over stdio")
    mcp.add_argument("--db", default=DEFAULT_DB)
    sub.add_parser("demo", help="run the three questions on sample data")
    sub.add_parser("export", help="regenerate contract schemas and fixtures")
    args = ap.parse_args(argv)

    if args.cmd == "api":
        import uvicorn

        from riskbot.api import create_app

        uvicorn.run(create_app(build_service(args.db)), host=args.host, port=args.port)
    elif args.cmd == "mcp":
        from riskbot.mcp_server import create_server

        create_server(build_service(args.db)).run()
    elif args.cmd == "demo":
        _demo(build_service())
    elif args.cmd == "export":
        from riskbot.contract import export

        export.main()
    else:  # pragma: no cover
        ap.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
