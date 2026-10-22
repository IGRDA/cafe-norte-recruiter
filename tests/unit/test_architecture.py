"""The import rules of src/cafe_norte/README.md, checked from the imports of the source files."""

import ast
from pathlib import Path

import pytest

from tests.support import ROOT

SRC = ROOT / "src" / "cafe_norte"
MODULES = {
    "domain",
    "model",
    "knowledge",
    "observability",
    "persistence",
    "conversation",
    "voice",
    "api",
}
ANY = "*"

# module -> {other module: allowed submodules ("*" for all)}. errors.py is always allowed.
ALLOWED: dict[str, dict[str, set[str]]] = {
    "domain": {},
    "model": {},
    "knowledge": {"domain": {"contracts"}},
    "observability": {"domain": {"contracts"}},
    "persistence": {"domain": {ANY}, "observability": {"contracts"}},
    "conversation": {
        "domain": {ANY},
        "model": {"contracts"},
        "knowledge": {"contracts"},
        "persistence": {"contracts"},
        "observability": {"contracts", "redaction"},  # tool arguments are journaled redacted
    },
    "voice": {
        "domain": {"contracts"},
        "conversation": {"contracts"},
        "observability": {"contracts"},
    },
    "api": {
        "domain": {ANY},
        "conversation": {"contracts"},
        "persistence": {"contracts", "export"},  # the export document is a published record
        "voice": {"contracts"},
        "observability": {"contracts"},
    },
}

# Third-party packages that belong to another module's adapters.
FORBIDDEN_THIRD_PARTY: dict[str, set[str]] = {
    "domain": {"fastapi", "starlette", "httpx", "psycopg", "pipecat", "fastembed"},
    "model": {"fastapi", "starlette", "psycopg", "pipecat", "fastembed"},
    "knowledge": {"fastapi", "starlette", "httpx", "psycopg", "pipecat"},
    "observability": {"fastapi", "starlette", "psycopg", "pipecat"},
    "persistence": {"fastapi", "starlette", "httpx", "pipecat"},
    "conversation": {"fastapi", "starlette", "httpx", "psycopg", "pipecat"},
    "voice": {"fastapi", "starlette", "psycopg"},
    "api": {"psycopg", "pipecat", "httpx"},
}


def imports_of(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
    return names


def violations(module: str, root: Path = SRC) -> list[str]:
    found: list[str] = []
    for path in sorted((root / module).rglob("*.py")):
        for name in sorted(imports_of(path)):
            parts = name.split(".")
            where = f"{path.relative_to(root)} imports {name}"
            if parts[0] in FORBIDDEN_THIRD_PARTY[module]:
                found.append(where)
                continue
            if parts[0] != "cafe_norte" or len(parts) < 2:
                continue
            target = parts[1]
            if target in {"errors", module}:
                continue
            allowed = ALLOWED[module].get(target)
            submodule = parts[2] if len(parts) > 2 else ""
            if allowed is None or (ANY not in allowed and submodule not in allowed):
                found.append(where)
    return found


@pytest.mark.parametrize("module", sorted(MODULES))
def test_module_imports_respect_the_dependency_rules(module: str) -> None:
    assert violations(module) == []


def test_the_check_catches_forbidden_imports(tmp_path: Path) -> None:
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "knowledge" / "bad.py").write_text(
        "from cafe_norte.conversation.runtime import Runtime\n"
        "from cafe_norte.domain.fields import capture\n"
        "from cafe_norte.domain.contracts import ConfigId\n"
        "from cafe_norte.errors import ServiceError\n"
        "import psycopg\n"
    )
    assert violations("knowledge", tmp_path) == [
        "knowledge/bad.py imports cafe_norte.conversation.runtime",
        "knowledge/bad.py imports cafe_norte.domain.fields",
        "knowledge/bad.py imports psycopg",
    ]


TESTS = ROOT / "tests"


def cross_test_imports(root: Path = TESTS) -> list[str]:
    """Test modules that import another test module: shared helpers belong in tests/support."""
    found: list[str] = []
    for path in sorted(root.rglob("test_*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [f"{node.module}.{alias.name}" for alias in node.names]
            for name in names:
                parts = name.split(".")
                if parts[0] == "tests" and any(p.startswith("test_") for p in parts[1:]):
                    found.append(f"{path.relative_to(root)} imports {name}")
    return found


def test_no_test_module_imports_another() -> None:
    assert cross_test_imports() == []


def test_the_check_catches_a_test_importing_a_test(tmp_path: Path) -> None:
    (tmp_path / "test_a.py").write_text(
        "from tests.test_b import helper\nfrom tests.support.harness import Harness\n"
    )
    assert cross_test_imports(tmp_path) == ["test_a.py imports tests.test_b.helper"]


# What a unit test may not touch: a store, the runtime, the handlers, the app, the composition
# root, I/O adapters, or the support built on them.
NOT_UNIT = (
    "cafe_norte.persistence.memory",
    "cafe_norte.persistence.postgres.store",
    "cafe_norte.conversation.runtime",
    "cafe_norte.conversation.handlers",
    "cafe_norte.voice.session",
    "cafe_norte.api",
    "cafe_norte.main",
    "tests.support.app",
    "tests.support.harness",
    "tests.support.http",
    "tests.support.tools",
    "tests.support.voice",
    "fastapi",
    "httpx",
    "psycopg",
    "pipecat",
)


def impure_unit_imports(root: Path = TESTS / "unit") -> list[str]:
    return [
        f"{path.relative_to(root)} imports {name}"
        for path in sorted(root.rglob("*.py"))
        for name in sorted(imports_of(path))
        if any(name == banned or name.startswith(banned + ".") for banned in NOT_UNIT)
    ]


def test_unit_tests_import_only_pure_code() -> None:
    assert impure_unit_imports() == []


def test_the_check_catches_a_unit_test_using_a_store(tmp_path: Path) -> None:
    (tmp_path / "test_a.py").write_text(
        "from cafe_norte.persistence.memory import MemoryStore\n"
        "from cafe_norte.domain import fields\n"
    )
    assert impure_unit_imports(tmp_path) == ["test_a.py imports cafe_norte.persistence.memory"]
