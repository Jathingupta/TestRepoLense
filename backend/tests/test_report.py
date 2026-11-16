from docx import Document

from app.agents.graph import make_tdd
from app.services.render import render_docx


def test_report_generates_structured_word_tables(tmp_path):
    scan = {
        "file_count": 2,
        "total_bytes_scanned": 1200,
        "truncated": False,
        "languages": {".ts": 2},
        "repository_tree": "app/",
        "files": [
            {
                "path": "app/(api)/ride/create+api.ts",
                "facts": {
                    "tables": ["rides"],
                    "database_operations": ["INSERT"],
                    "integrations": ["Neon/PostgreSQL"],
                },
            },
            {
                "path": "app/home.tsx",
                "facts": {"tables": [], "integrations": []},
            },
        ],
        "manifests": {},
        "api_endpoints": [{
            "method": "POST",
            "route": "/ride/create",
            "path": "app/(api)/ride/create+api.ts",
            "request_fields": ["pickup", "destination"],
            "response_patterns": ["Response.json"],
        }],
        "api_call_details": [{
            "source": "app/home.tsx",
            "method": "POST",
            "url": "/api/ride/create",
        }],
        "database_tables": ["rides"],
        "integrations": ["Neon/PostgreSQL"],
        "external_imports": ["@neondatabase/serverless"],
        "asset_imports": [],
        "classes": [],
        "functions": ["POST"],
        "environment_variables": ["DATABASE_URL"],
        "dependency_graph": {"edges": [], "unresolved_local_imports": []},
    }
    architecture = {
        "summary": "Ride booking application.",
        "layers": [{"id": "application", "name": "Application"}],
        "components": [{
            "id": "ride_api",
            "name": "Ride creation endpoint",
            "layer": "application",
            "type": "api",
            "description": "Persists a ride request.",
            "evidence_paths": ["app/(api)/ride/create+api.ts"],
        }],
        "relationships": [],
        "flows": [],
        "risks": [],
    }

    markdown = make_tdd("sample", scan, architecture)
    output = tmp_path / "report.docx"
    render_docx(markdown, output, repository="sample")

    document = Document(output)
    assert len(document.tables) >= 4
    assert "POST" in markdown
    assert "/ride/create" in markdown
    assert "rides" in markdown
    assert "Matched by static URL and HTTP method" in markdown
