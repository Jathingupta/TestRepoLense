import re
from pathlib import Path


def _id(value):
    return "N_" + re.sub(r"[^A-Za-z0-9_]", "_", str(value))


def _valid_paths(values, known):
    if not isinstance(values, list):
        return []
    return list(dict.fromkeys(p for p in values if isinstance(p, str) and p in known))


def validate_architecture(model, scan):
    """Validate all model references against paths and IDs in the scan."""
    known = {item.get("path") for item in scan.get("files", [])}
    layers, layer_ids = [], set()
    for i, item in enumerate(model.get("layers") or [], 1):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        lid = re.sub(r"[^A-Za-z0-9_]", "_", str(item.get("id") or f"layer_{i}"))
        if name and lid not in layer_ids:
            layers.append({"id": lid, "name": name[:80],
                           "description": str(item.get("description") or "")[:300]})
            layer_ids.add(lid)
    if not layers:
        layers = [{"id": "application", "name": "Application",
                   "description": "Components identified from repository evidence."}]
        layer_ids = {"application"}

    components, ids = [], set()
    for i, item in enumerate(model.get("components") or [], 1):
        if not isinstance(item, dict):
            continue
        cid = re.sub(r"[^A-Za-z0-9_]", "_", str(item.get("id") or f"component_{i}"))
        paths = _valid_paths(item.get("evidence_paths"), known)
        layer = str(item.get("layer") or layers[0]["id"])
        name = str(item.get("name") or "").strip()
        is_external = bool(item.get("external", False))
        code_extensions = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
                           ".java", ".go", ".cs", ".php", ".rb", ".rs", ".sql"}
        if (not cid or cid in ids or not name or layer not in layer_ids or not paths):
            continue
        # A package manifest alone proves declaration, not active integration.
        if is_external and not any(Path(path).suffix.lower() in code_extensions for path in paths):
            continue
        components.append({
            "id": cid, "name": name[:100], "layer": layer,
            "type": str(item.get("type") or "component")[:50],
            "description": str(item.get("description") or "")[:350],
            "evidence_paths": paths[:8], "external": is_external
        })
        ids.add(cid)

    relationships, seen = [], set()
    for item in model.get("relationships") or []:
        if not isinstance(item, dict):
            continue
        source, target = item.get("source"), item.get("target")
        paths = _valid_paths(item.get("evidence_paths"), known)
        key = (source, target, item.get("type"))
        source_component = next((c for c in components if c["id"] == source), None)
        target_component = next((c for c in components if c["id"] == target), None)
        if (source_component is None or target_component is None or source == target
                or not paths or key in seen):
            continue
        # The cited files must belong to both ends of the claimed relationship.
        if not (set(paths) & set(source_component["evidence_paths"])):
            continue
        if not (set(paths) & set(target_component["evidence_paths"])):
            continue
        seen.add(key)
        relationships.append({
            "source": source, "target": target,
            "type": str(item.get("type") or "depends_on")[:40],
            "label": str(item.get("label") or item.get("type") or "depends on")[:50],
            "evidence_paths": paths[:6],
            "confidence": item.get("confidence") if item.get("confidence") in {"high", "medium", "inferred"} else "inferred",
            "basis": str(item.get("basis") or "Inferred from cited source files.")[:250]
        })

    flows = []
    for item in model.get("flows") or []:
        if not isinstance(item, dict):
            continue
        steps = [s for s in item.get("steps", []) if s in ids]
        paths = _valid_paths(item.get("evidence_paths"), known)
        if len(steps) > 1 and paths:
            flows.append({"name": str(item.get("name") or "Application flow")[:80],
                          "description": str(item.get("description") or "")[:250],
                          "steps": steps[:10], "evidence_paths": paths[:6]})
    return {
        "summary": str(model.get("summary") or "Architecture synthesized from repository evidence.")[:800],
        "layers": layers, "components": components,
        "relationships": relationships, "flows": flows,
        "risks": [str(x)[:300] for x in (model.get("risks") or [])[:15]]
    }


def fallback_architecture(repo, scan):
    """Conservative fallback: directory-level modules connected only by resolved imports."""
    files = scan.get("files", [])
    groups, path_owner = {}, {}
    source_exts = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
                   ".java", ".go", ".cs", ".php", ".rb", ".rs"}
    for item in files:
        path = item.get("path", "")
        if Path(path).suffix.lower() not in source_exts:
            continue
        parts = [part.lower() for part in Path(path).parts]
        if any(part in {"api", "routes"} or "(api)" in part for part in parts):
            area = "API and route handlers"
        elif any(part in {"screens", "pages", "views"} for part in parts):
            area = "Screens and navigation"
        elif any(part in {"components", "ui", "widgets"} for part in parts):
            area = "Reusable UI components"
        elif any(part in {"services", "lib", "utils", "hooks"} for part in parts):
            area = "Application services and utilities"
        elif any(part in {"store", "state"} for part in parts):
            area = "Client state"
        elif any(part in {"models", "repositories", "db", "database", "schemas"} for part in parts):
            area = "Data and persistence"
        else:
            area = Path(path).parts[0] if len(Path(path).parts) > 1 else "root modules"
        groups.setdefault(area, []).append(path)
    components = []
    for i, (name, paths) in enumerate(sorted(groups.items()), 1):
        cid = f"module_{i}"
        components.append({"id": cid, "name": name, "layer": "application",
                           "type": "source module group",
                           "description": f"{len(paths)} source files under {name}.",
                           "evidence_paths": paths[:8], "external": False})
        for path in paths:
            path_owner[path] = cid
    relations, seen = [], set()
    for edge in (scan.get("dependency_graph") or {}).get("edges", []):
        a, b = path_owner.get(edge.get("source")), path_owner.get(edge.get("target"))
        if a and b and a != b and (a, b) not in seen:
            seen.add((a, b))
            relations.append({"source": a, "target": b, "type": "imports",
                              "label": "imports", "evidence_paths": [edge["source"], edge["target"]],
                              "confidence": "high"})
    return {
        "summary": f"{repo}: {scan.get('file_count', 0)} files inspected. Fallback architecture groups source modules by directory; runtime behavior was not executed.",
        "layers": [{"id": "application", "name": "Application modules",
                    "description": "Source modules grouped by repository directory."}],
        "components": components, "relationships": relations, "flows": [],
        "risks": ["Fallback mode cannot infer business workflows or runtime call paths."]
    }


def diagram(architecture, scan):
    """Render a compact overview; detailed evidence remains in report tables."""
    layers = architecture.get("layers", [])
    components = architecture.get("components", [])
    relationships = architecture.get("relationships", [])
    if not components:
        return 'flowchart LR\n    EMPTY["No components with scanned source evidence were identified."]'

    lines = [
        "flowchart LR",
        "    classDef component fill:#eaf2ff,stroke:#4778b8,color:#172b4d;",
        "    classDef external fill:#f3e8ff,stroke:#8b5cf6,color:#3b0764;"
    ]
    valid_ids = {component["id"] for component in components}
    for layer in layers:
        members = [component for component in components if component["layer"] == layer["id"]]
        if not members:
            continue
        lines.append(f'    subgraph {_id(layer["id"])}["{_label(layer["name"])}"]')
        for component in members:
            description = _label(component.get("description", ""))
            if len(description) > 78:
                description = description[:75] + "..."
            label = _label(component["name"])
            if description:
                label += "<br/><small>" + description + "</small>"
            style = "external" if component.get("external") else "component"
            lines.append(f'        {_id(component["id"])}["{label}"]:::{style}')
        lines.append("    end")

    # Prefer source-backed relationships and avoid drawing duplicate pairs.
    ranked = sorted(
        relationships,
        key=lambda relation: (
            {"high": 0, "medium": 1, "inferred": 2}.get(relation.get("confidence"), 3),
            relation.get("source", ""),
            relation.get("target", ""),
        )
    )
    drawn_pairs = set()
    for relation in ranked:
        source, target = relation.get("source"), relation.get("target")
        if source not in valid_ids or target not in valid_ids or source == target:
            continue
        if (source, target) in drawn_pairs or len(drawn_pairs) >= 16:
            continue
        drawn_pairs.add((source, target))
        label = _label(relation.get("label") or relation.get("type") or "depends on")
        if relation.get("confidence") == "inferred":
            label += " (inferred)"
        lines.append(f'    {_id(source)} -->|{label}| {_id(target)}')

    if not drawn_pairs:
        lines.append('    NOTE["No cross-component relationships met the evidence threshold."]')
    elif len(relationships) > len(drawn_pairs):
        lines.append('    NOTE["Diagram shows a simplified subset; see relationship table for full evidence."]')
    lines.append('    LIMIT["Inferred runtime relationships are labelled; static import edges are not runtime proof."]')
    return "\n".join(lines)


def _label(value):
    return (str(value or "").replace("&", "&amp;").replace('"', "'")
            .replace("<", "&lt;").replace(">", "&gt;")
            .replace("|", "/").replace("\n", " ")[:160])
