from app.agents.architecture_model import diagram, validate_architecture


def sample_scan():
    return {
        "files": [
            {"path": "app/screens/BookRide.tsx"},
            {"path": "app/services/ride.ts"},
            {"path": "app/api/ride.ts"},
            {"path": "lib/db.ts"},
        ],
        "dependency_graph": {"edges": []},
    }


def sample_model():
    return {
        "summary": "Ride booking architecture",
        "layers": [
            {"id": "presentation", "name": "Presentation"},
            {"id": "application", "name": "Application"},
        ],
        "components": [
            {"id": "booking_screen", "name": "Book Ride screen",
             "layer": "presentation", "description": "Collects ride details",
             "evidence_paths": ["app/screens/BookRide.tsx"]},
            {"id": "ride_service", "name": "Ride service",
             "layer": "application", "description": "Creates ride requests",
             "evidence_paths": ["app/services/ride.ts"]},
        ],
        "relationships": [
            {"source": "booking_screen", "target": "ride_service",
             "type": "calls", "label": "requests ride",
             "evidence_paths": ["app/screens/BookRide.tsx", "app/services/ride.ts"],
             "confidence": "inferred"},
            {"source": "booking_screen", "target": "missing_component",
             "type": "calls", "evidence_paths": ["app/screens/BookRide.tsx"]},
            {"source": "ride_service", "target": "booking_screen",
             "type": "calls", "evidence_paths": ["not/a/real/file.ts"]},
        ],
        "flows": [
            {"name": "Book ride", "steps": ["booking_screen", "ride_service"],
             "evidence_paths": ["app/screens/BookRide.tsx"]},
        ],
        "risks": [],
    }


def test_validate_architecture_discards_unknown_paths_and_component_ids():
    validated = validate_architecture(sample_model(), sample_scan())

    assert len(validated["components"]) == 2
    assert len(validated["relationships"]) == 1
    assert validated["relationships"][0]["confidence"] == "inferred"
    assert validated["flows"][0]["steps"] == ["booking_screen", "ride_service"]


def test_diagram_uses_semantic_components_and_relationships():
    validated = validate_architecture(sample_model(), sample_scan())
    output = diagram(validated, sample_scan())

    assert "Presentation" in output
    assert "Book Ride screen" in output
    assert "Ride service" in output
    assert "requests ride (inferred)" in output
    assert "imports:" not in output
    assert "flow:" not in output
    assert "LIMIT" in output


def test_validate_architecture_requires_evidence_for_components():
    model = sample_model()
    model["components"].append({
        "id": "made_up", "name": "Invented cloud service",
        "layer": "application", "evidence_paths": ["missing/file.py"]
    })

    validated = validate_architecture(model, sample_scan())
    assert "made_up" not in {item["id"] for item in validated["components"]}



def test_diagram_limits_relationship_edges_for_readability():
    model = sample_model()
    for index in range(20):
        model["components"].append({
            "id": f"service_{index}",
            "name": f"Service {index}",
            "layer": "application",
            "description": "Another service",
            "evidence_paths": ["app/api/ride.ts"],
        })
        model["relationships"].append({
            "source": "booking_screen",
            "target": f"service_{index}",
            "type": "calls",
            "label": f"relationship {index}",
            "evidence_paths": ["app/screens/BookRide.tsx", "app/api/ride.ts"],
            "confidence": "high",
        })

    validated = validate_architecture(model, sample_scan())
    output = diagram(validated, sample_scan())

    assert output.count("-->") == 16
    assert "simplified subset" in output
