from app.services.scanner import scan_repository


def test_scanner_extracts_python_facts(tmp_path):
    source = "from fastapi import FastAPI\n\napp = FastAPI()\n\n@app.get('/health')\ndef health():\n    return {}\n"
    (tmp_path / "main.py").write_text(source, encoding="utf-8")

    result = scan_repository(tmp_path, 100, 10000, 100000, True)

    assert result["file_count"] == 1
    assert "health" in result["functions"]
    assert result["routes"] == ["/health"]
    assert "dependency_graph" in result


def test_scanner_resolves_python_local_import(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "main.py").write_text(
        "from app.services import billing\n",
        encoding="utf-8",
    )
    (tmp_path / "app" / "services").mkdir()
    (tmp_path / "app" / "services" / "billing.py").write_text(
        "def calculate_total():\n    return 42\n",
        encoding="utf-8",
    )

    result = scan_repository(tmp_path, 100, 10000, 100000, True)
    edges = result["dependency_graph"]["edges"]

    assert any(
        edge["source"] == "app/main.py"
        and edge["target"] == "app/services/billing.py"
        and edge["relation"] == "imports"
        for edge in edges
    )


def test_scanner_resolves_relative_javascript_import(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "App.tsx").write_text(
        "import { helper } from './utils/helper';\nexport default helper;\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "utils").mkdir()
    (tmp_path / "src" / "utils" / "helper.ts").write_text(
        "export function helper() { return true; }\n",
        encoding="utf-8",
    )

    result = scan_repository(tmp_path, 100, 10000, 100000, True)
    edges = result["dependency_graph"]["edges"]

    assert any(
        edge["source"] == "src/App.tsx"
        and edge["target"] == "src/utils/helper.ts"
        for edge in edges
    )
