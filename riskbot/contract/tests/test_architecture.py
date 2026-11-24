"""Dependency rules, enforced on every file under riskbot/.

* Each component may import only ``riskbot.contract`` and its own package.
* ``riskbot.app`` (composition root) may import anything.
* The contract imports nothing from other components.
* Core math packages may not import I/O, network, web or LLM libraries.
"""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]  # .../riskbot
COMPONENTS = {
    "contract": "riskbot.contract",
    "core/market": "riskbot.core.market",
    "core/balance_sheet": "riskbot.core.balance_sheet",
    "core/climate": "riskbot.core.climate",
    "qualitative": "riskbot.qualitative",
    "services": "riskbot.services",
    "orchestration": "riskbot.orchestration",
    "api": "riskbot.api",
    "mcp_server": "riskbot.mcp_server",
}
CORE_FORBIDDEN = {"requests", "httpx", "urllib", "socket", "yfinance", "anthropic", "sqlite3", "fastapi",
                  "langgraph", "mcp", "subprocess", "riskbot.services", "riskbot.orchestration"}


def _component(path: Path) -> str | None:
    rel = path.relative_to(ROOT).as_posix()
    for folder, pkg in sorted(COMPONENTS.items(), key=lambda kv: -len(kv[0])):
        if rel.startswith(folder + "/"):
            return pkg
    return None


def _module_name(path: Path) -> str:
    parts = ["riskbot", *path.relative_to(ROOT).with_suffix("").parts]
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    mod = _module_name(path)
    pkg = mod if path.name == "__init__.py" else mod.rsplit(".", 1)[0]
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = pkg.split(".")
                base = base[: len(base) - (node.level - 1)]
                name = ".".join(base + ([node.module] if node.module else []))
            else:
                name = node.module or ""
            out.append(name)
    return out


FILES = [p for p in ROOT.rglob("*.py") if "node_modules" not in p.parts]


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_dependency_rules(path):
    comp = _component(path)
    if comp is None:  # riskbot/__init__.py, riskbot/app.py, top-level tests: unrestricted
        return
    for name in _imports(path):
        if name.startswith("riskbot"):
            ok = name.startswith("riskbot.contract") or name.startswith(comp)
            assert ok, f"{path.relative_to(ROOT)} imports {name}: components may only import riskbot.contract"
        if comp.startswith("riskbot.core") or comp == "riskbot.contract":
            top = name.split(".")[0]
            bad = {f for f in CORE_FORBIDDEN if name == f or name.startswith(f + ".") or top == f}
            assert not bad, f"{path.relative_to(ROOT)} imports forbidden {name} (pure math / contract only)"
