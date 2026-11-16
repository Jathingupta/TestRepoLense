from types import SimpleNamespace

import pytest

from app.agents import graph


def test_extract_json_handles_fenced_json_and_braces_in_strings():
    parsed = graph.extract_json(
        '```json\n{"summary": "A {small} system", "components": []}\n```'
    )

    assert parsed["summary"] == "A {small} system"


def test_extract_json_reports_malformed_json():
    with pytest.raises(ValueError, match="Invalid JSON"):
        graph.extract_json('{"summary": "broken" "components": []}')


def test_architecture_agent_retries_malformed_json(monkeypatch):
    scan = {
        "files": [{"path": "app/screens/Home.tsx", "language": ".tsx", "facts": {
            "imports": [], "routes": [], "tables": [], "classes": [], "functions": []
        }}],
        "manifests": {},
        "repository_tree": "app/screens/",
        "dependency_graph": {"edges": [], "unresolved_local_imports": []},
        "file_count": 1,
    }
    valid_response = (
        '{"summary":"A small app","layers":[{"id":"presentation",'
        '"name":"Presentation","description":"User interface"}],'
        '"components":[{"id":"home","name":"Home screen","layer":"presentation",'
        '"type":"screen","description":"Main screen",'
        '"evidence_paths":["app/screens/Home.tsx"]}],'
        '"relationships":[],"flows":[],"risks":[]}'
    )

    class FakeLLM:
        def __init__(self):
            self.calls = 0

        def bind(self, **kwargs):
            assert kwargs == {"response_format": {"type": "json_object"}}
            return self

        def invoke(self, messages):
            self.calls += 1
            raw = '{"summary": "malformed" "components": []}' if self.calls == 1 else valid_response
            return SimpleNamespace(
                content=raw,
                response_metadata={"finish_reason": "stop"},
                usage_metadata={},
            )

    fake_llm = FakeLLM()
    monkeypatch.setattr(graph, "llm_client", lambda: fake_llm)

    result = graph.architecture_agent({"repository": "sample", "scan": scan})

    assert result["llm_used"] is True
    assert result["architecture"]["components"][0]["id"] == "home"
    assert fake_llm.calls == 2
