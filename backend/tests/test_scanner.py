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


def test_scanner_resolves_python_import_from_nested_source_root(tmp_path):
    package = tmp_path / "backend" / "app"
    (package / "services").mkdir(parents=True)
    (package / "main.py").write_text(
        "from app.services import billing\n",
        encoding="utf-8",
    )
    (package / "services" / "billing.py").write_text(
        "def calculate_total():\n    return 42\n",
        encoding="utf-8",
    )

    result = scan_repository(tmp_path, 100, 10000, 100000, True)
    edges = result["dependency_graph"]["edges"]

    assert any(
        edge["source"] == "backend/app/main.py"
        and edge["target"] == "backend/app/services/billing.py"
        for edge in edges
    )



def test_scanner_resolves_typescript_wildcard_alias(tmp_path):
    (tmp_path / "tsconfig.json").write_text(
        '{"compilerOptions":{"baseUrl":".","paths":{"@/*":["src/*"]}}}',
        encoding="utf-8",
    )
    (tmp_path / "src" / "components").mkdir(parents=True)
    (tmp_path / "src" / "screens").mkdir(parents=True)
    (tmp_path / "src" / "screens" / "Home.tsx").write_text(
        "import CustomButton from '@/components/CustomButton';\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "components" / "CustomButton.tsx").write_text(
        "export default function CustomButton() { return null; }\n",
        encoding="utf-8",
    )

    result = scan_repository(tmp_path, 100, 10000, 100000, True)
    edges = result["dependency_graph"]["edges"]

    assert any(
        edge["source"] == "src/screens/Home.tsx"
        and edge["target"] == "src/components/CustomButton.tsx"
        and edge["evidence"] == "@/components/CustomButton"
        for edge in edges
    )


def test_scanner_resolves_typescript_alias_with_jsconfig_and_jsonc(tmp_path):
    (tmp_path / "jsconfig.json").write_text(
        '{\n  // app root alias\n  "compilerOptions": {\n    "baseUrl": ".",\n    "paths": { "@lib/*": ["src/lib/*"], },\n  }\n}',
        encoding="utf-8",
    )
    (tmp_path / "src" / "lib").mkdir(parents=True)
    (tmp_path / "src" / "pages").mkdir(parents=True)
    (tmp_path / "src" / "pages" / "index.tsx").write_text(
        "import { auth } from '@lib/auth';\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "lib" / "auth.ts").write_text(
        "export const auth = {};\n",
        encoding="utf-8",
    )

    result = scan_repository(tmp_path, 100, 10000, 100000, True)
    edges = result["dependency_graph"]["edges"]

    assert any(
        edge["source"] == "src/pages/index.tsx"
        and edge["target"] == "src/lib/auth.ts"
        for edge in edges
    )


def test_scanner_reports_unresolved_configured_alias(tmp_path):
    (tmp_path / "tsconfig.json").write_text(
        '{"compilerOptions":{"baseUrl":".","paths":{"@/*":["src/*"]}}}',
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "App.tsx").write_text(
        "import Missing from '@/components/Missing';\n",
        encoding="utf-8",
    )

    result = scan_repository(tmp_path, 100, 10000, 100000, True)
    unresolved = result["dependency_graph"]["unresolved_local_imports"]

    assert any(
        item["source"] == "src/App.tsx"
        and item["import"] == "@/components/Missing"
        for item in unresolved
    )



def test_scanner_extracts_behavioral_evidence_for_architecture(tmp_path):
    api_dir = tmp_path / "app" / "(api)" / "ride"
    api_dir.mkdir(parents=True)
    (api_dir / "create+api.ts").write_text(
        "import { neon } from '@neondatabase/serverless';\n"
        "import { auth } from '@clerk/clerk-expo';\n"
        "export async function POST(request) {\n"
        "  const sql = neon(process.env.DATABASE_URL);\n"
        "  const rows = await sql('SELECT * FROM rides');\n"
        "  return Response.json(rows);\n"
        "}\n",
        encoding="utf-8",
    )
    (tmp_path / "app" / "home.tsx").write_text(
        "export default function Home() {\n"
        "  const submitRide = async () => fetch('/api/ride/create', { method: 'POST' });\n"
        "  return <Button onPress={submitRide} />;\n"
        "}\n",
        encoding="utf-8",
    )

    result = scan_repository(tmp_path, 100, 10000, 100000, True)
    api = next(item for item in result["files"] if item["path"].endswith("create+api.ts"))
    ui = next(item for item in result["files"] if item["path"] == "app/home.tsx")

    assert "POST" in api["facts"]["api_handlers"]
    assert "/ride/create" in api["facts"]["routes"]
    assert api["facts"]["api_endpoints"][0]["method"] == "POST"
    assert api["facts"]["api_endpoints"][0]["route"] == "/ride/create"
    assert "Neon/PostgreSQL" in api["facts"]["integrations"]
    assert "Clerk authentication" in api["facts"]["integrations"]
    assert "DATABASE_URL" in api["facts"]["environment_variables"]
    assert "rides" in api["facts"]["tables"]
    assert "fetch" in ui["facts"]["api_calls"]
    assert "submitRide" in ui["facts"]["ui_actions"]
    assert ui["facts"]["evidence_snippets"]



def test_scanner_separates_external_local_and_asset_imports(tmp_path):
    (tmp_path / "tsconfig.json").write_text(
        '{"compilerOptions":{"baseUrl":".","paths":{"@/*":["src/*"]}}}',
        encoding="utf-8",
    )
    (tmp_path / "src" / "types").mkdir(parents=True)
    (tmp_path / "src" / "assets").mkdir(parents=True)
    (tmp_path / "src" / "types" / "type.d.ts").write_text(
        "export type User = { id: string };", encoding="utf-8"
    )
    (tmp_path / "src" / "assets" / "logo.png").write_bytes(b"image")
    (tmp_path / "src" / "App.tsx").write_text(
        "import React from 'react';\n"
        "import { useAuth } from '@clerk/clerk-expo';\n"
        "import type { User } from '@/types/type';\n"
        "import logo from '@/assets/logo.png';\n",
        encoding="utf-8",
    )

    result = scan_repository(tmp_path, 100, 10000, 100000, True)

    assert "react" in result["external_imports"]
    assert "@clerk/clerk-expo" in result["external_imports"]
    assert "@/types/type" in result["local_imports"]
    assert "@/assets/logo.png" in result["asset_imports"]
    assert not result["dependency_graph"]["unresolved_local_imports"]


def test_scanner_extracts_sql_table_names_without_package_or_variable_noise(tmp_path):
    (tmp_path / "app").mkdir()
    sql_tick = chr(96)
    source = (
        "const packageName = 'package.json';\n"
        "const auto = true;\n"
        "const sql = neon(process.env.DATABASE_URL);\n"
        + "const rows = await sql(" + sql_tick
        + "SELECT id FROM rides JOIN drivers ON rides.driver_id = drivers.id"
        + sql_tick + ");\n"
    )
    (tmp_path / "app" / "route.ts").write_text(source, encoding="utf-8")

    result = scan_repository(tmp_path, 100, 10000, 100000, True)

    assert "rides" in result["database_tables"]
    assert "drivers" in result["database_tables"]
    assert "package" not in result["database_tables"]
    assert "auto" not in result["database_tables"]
