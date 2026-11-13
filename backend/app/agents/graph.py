
import json
import re
from pathlib import Path
from typing import TypedDict

from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from app.core.config import settings
from app.agents.architecture_model import fallback_architecture, validate_architecture, diagram


# --------------------------------------------------
# 1. GRAPH STATE
# --------------------------------------------------

class State(TypedDict, total=False):
    repository: str
    scan: dict
    architecture: dict
    tdd: str
    llm_used: bool


# --------------------------------------------------
# 2. FALLBACK ARCHITECTURE
# --------------------------------------------------



# 3. GROQ LLM CLIENT
# --------------------------------------------------

def llm_client():
    if not settings.groq_api_key:
        return None

    return ChatOpenAI(
        model=settings.groq_model,
        api_key=settings.groq_api_key,
        base_url=settings.groq_base_url,
        temperature=0.1,
        max_tokens=4000
    )


# --------------------------------------------------
# 4. JSON EXTRACTION HELPER
# --------------------------------------------------

def extract_json(raw):
    """
    Extract JSON from an LLM response.
    Handles responses wrapped in Markdown code fences.
    """

    raw = raw.strip()

    # Remove Markdown code fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)

    # Extract the JSON object
    match = re.search(r"\{[\s\S]*\}", raw)

    if not match:
        raise ValueError("No JSON object found in LLM response")

    return json.loads(match.group(0))


# --------------------------------------------------
# 5. ARCHITECTURE AGENT
# --------------------------------------------------

def _architecture_evidence(scan):
    """Provide compact file-level evidence with exact paths for citations."""
    files = []
    for item in scan.get("files", [])[:260]:
        facts = item.get("facts", {})
        files.append({
            "path": item.get("path"), "language": item.get("language"),
            "imports": facts.get("imports", [])[:20],
            "routes": facts.get("routes", [])[:12],
            "tables": facts.get("tables", [])[:12],
            "classes": facts.get("classes", [])[:12],
            "functions": facts.get("functions", [])[:20],
        })
    manifests = {}
    for path, raw in (scan.get("manifests") or {}).items():
        if Path(path).name == "package.json":
            try:
                data = json.loads(raw)
                manifests[path] = {
                    "name": data.get("name"),
                    "dependencies": data.get("dependencies", {}),
                    "devDependencies": data.get("devDependencies", {}),
                }
            except (TypeError, json.JSONDecodeError):
                manifests[path] = {"parse_error": True}
        else:
            manifests[path] = raw[:3000]
    graph = scan.get("dependency_graph") or {}
    return {"files": files, "manifests": manifests,
            "resolved_import_edges": graph.get("edges", [])[:400],
            "unresolved_local_imports": graph.get("unresolved_local_imports", [])[:80],
            "repository_tree": scan.get("repository_tree", "")[:4000]}


def architecture_agent(state):
    llm = llm_client()
    scan = state["scan"]
    if not llm:
        return {"architecture": fallback_architecture(state["repository"], scan),
                "llm_used": False}

    schema = {
        "summary": "string",
        "layers": [{"id": "presentation", "name": "Presentation",
                    "description": "Layer responsibility"}],
        "components": [{
            "id": "ride_api", "name": "Ride API", "layer": "application",
            "type": "api|service|screen|database|external_service|state_store",
            "description": "Component responsibility",
            "evidence_paths": ["exact/path/from/evidence"],
            "external": False
        }],
        "relationships": [{
            "source": "component_id", "target": "component_id",
            "type": "calls|imports|reads_from|writes_to|authenticates_with|integrates_with",
            "label": "short relationship label",
            "evidence_paths": ["exact/path/from/evidence"],
            "confidence": "high|medium|inferred",
            "basis": "Concrete evidence and whether runtime behavior is inferred"
        }],
        "flows": [{
            "name": "Ride booking",
            "description": "Only when end-to-end steps are supported",
            "steps": ["component_id", "component_id"],
            "evidence_paths": ["exact/path/from/evidence"]
        }],
        "risks": ["Evidence-backed risk or limitation"]
    }
    evidence = _architecture_evidence(scan)
    prompt = (
        "Act as a senior software architect. Return ONLY valid JSON matching this schema "
        "(examples are placeholders, not repository facts):\n"
        f"{json.dumps(schema, ensure_ascii=False)}\n\n"
        "Create a meaningful layered system architecture, NOT a folder or file inventory. "
        "Identify screens/routing, state, application services, API handlers, persistence, "
        "and external integrations only when supported by source-code usage. "
        "A package manifest proves a dependency is declared, not that it is actively integrated. " "External integrations must cite source files showing imports, initialization or API usage. " "Every component must cite exact evidence_paths from evidence.files or evidence.manifests. "
        "Every relationship must cite at least one path belonging to each connected component. Every flow must cite exact scanned paths and include only components in the supported sequence. Imports prove module "
        "dependency, not runtime calls. Label inferred runtime behavior with confidence='inferred'. "
        "Never invent paths, APIs, providers, databases, infrastructure or business flows. "
        "Omit relationships that cannot be supported. Use clear component names and concise "
        "responsibilities.\n\n"
        f"Repository: {state['repository']}\n"
        f"Evidence:\n{json.dumps(evidence, ensure_ascii=False)[:24000]}"
    )
    try:
        message = llm.invoke([
            SystemMessage(content="Produce precise evidence-led software architecture. Never hallucinate repository components or relationships."),
            HumanMessage(content=prompt)
        ])
        raw = message.content if isinstance(message.content, str) else str(message.content)
        architecture = validate_architecture(extract_json(raw), scan)
        if not architecture["components"]:
            raise ValueError("LLM returned no components tied to scanned source paths")
        return {"architecture": architecture, "llm_used": True}
    except Exception as error:
        print(f"Architecture agent failed: {error}")
        return {"architecture": fallback_architecture(state["repository"], scan),
                "llm_used": False}

# 6. TECHNICAL DESIGN DOCUMENT GENERATOR
# --------------------------------------------------


def technology_stack_lines(scan):
    """Extract technologies and versions from dependency manifests."""
    technologies = []
    manifests = scan.get("manifests", {}) or {}
    package_data = {}
    for path, raw in manifests.items():
        if Path(path).name == "package.json":
            try:
                package_data = json.loads(raw)
                break
            except (TypeError, json.JSONDecodeError):
                continue

    def add(name, version, role):
        technologies.append(
            f"- **{name}** ({version or 'version not specified'}) — {role}"
        )

    if package_data:
        add("Node.js", (package_data.get("engines") or {}).get("node"),
            "JavaScript runtime ecosystem")
        deps = {}
        for group in ("dependencies", "devDependencies", "peerDependencies"):
            deps.update(package_data.get(group) or {})
        roles = {
            "expo": "cross-platform application framework",
            "expo-router": "file-based navigation and routing",
            "react": "UI library",
            "react-native": "native mobile UI framework",
            "typescript": "typed JavaScript language tooling",
            "@clerk/clerk-expo": "authentication SDK",
            "@stripe/stripe-react-native": "mobile payment SDK",
            "@neondatabase/serverless": "serverless PostgreSQL client",
            "zustand": "client-side state management",
            "react-native-maps": "native maps integration",
            "nativewind": "utility-first styling for React Native",
            "tailwindcss": "utility-first CSS framework",
            "axios": "HTTP client",
            "zod": "runtime schema validation",
            "express": "HTTP server framework",
        }
        for name, version in sorted(deps.items()):
            if name in roles:
                add(name, version, roles[name])
        for name, version in sorted(deps.items()):
            if name not in roles and len(technologies) < 24:
                add(name, version, "declared dependency; role not classified")

    if not technologies:
        for path, raw in manifests.items():
            if Path(path).name == "requirements.txt":
                for line in raw.splitlines():
                    match = re.match(r"\s*([A-Za-z0-9_.-]+)\s*(?:==|>=|~=)\s*([^;\s]+)", line)
                    if match:
                        add(match.group(1), match.group(2), "Python package from requirements")
    return technologies or [
        "- No supported dependency manifest could be parsed.",
        "- File-extension counts are reported separately in Inventory."
    ]


def make_tdd(repo, scan, architecture):

    lines = [
        "# Technical Design Document",
        "## 1. Executive summary",
        architecture.get("summary", ""),
        "## 2. Scope and method",
        (
            f"Static inspection covered {scan['file_count']} files "
            f"and {scan['total_bytes_scanned']} bytes. "
            "Source code was not executed."
        ),
        "## 3. Technology stack"
    ]

    lines += technology_stack_lines(scan)

    lines += [
        "## 4. Repository structure",
        "```text",
        scan.get("repository_tree", "Not detected."),
        "```",
        "## 5. Architecture",
        "### Components"
    ]

    for layer in architecture.get("layers", []):
        lines.append(f"### {layer.get('name', 'Architecture layer')}")
        if layer.get("description"):
            lines.append(layer["description"])
        members = [item for item in architecture.get("components", [])
                   if item.get("layer") == layer.get("id")]
        lines += [
            f"- **{item.get('name', 'Component')}** ({item.get('type', 'component')}): "
            f"{item.get('description', '')} "
            f"(evidence: {', '.join(item.get('evidence_paths', []))})"
            for item in members
        ]

    lines += ["### Relationships"]
    lines += [
        f"- **{item.get('source')} → {item.get('target')}** "
        f"({item.get('label', item.get('type'))}; confidence: {item.get('confidence')}). "
        f"Evidence: {', '.join(item.get('evidence_paths', []))}. {item.get('basis', '')}"
        for item in architecture.get("relationships", [])
    ] or ["- No cross-component relationships met the evidence threshold."]

    lines += ["### Flows"]
    lines += [
        f"- **{flow.get('name', 'Application flow')}**: "
        f"{flow.get('description', '')} "
        f"Steps: {' → '.join(flow.get('steps', []))}. "
        f"Evidence: {', '.join(flow.get('evidence_paths', []))}."
        for flow in architecture.get("flows", [])
    ] or ["- No end-to-end flow met the evidence threshold."]

    dependency_graph = scan.get("dependency_graph", {})
    lines += [
        "## 6. Module dependency relationships",
        dependency_graph.get(
            "relationship_scope",
            "Repository-local relationships were not available."
        ),
    ]
    dependency_edges = dependency_graph.get("edges", [])
    if dependency_edges:
        lines += [
            f"- `{edge['source']}` imports `{edge['target']}` "
            f"(evidence: `{edge['evidence']}`)."
            for edge in dependency_edges[:100]
        ]
    else:
        lines.append("- No repository-local import relationships were resolved.")
    unresolved = dependency_graph.get("unresolved_local_imports", [])
    if unresolved:
        lines.append("### Unresolved local import candidates")
        lines += [
            f"- `{item['source']}`: `{item['import']}`"
            for item in unresolved[:50]
        ]

    sections = [
        ("7. API surface", "routes"),
        ("8. Data layer", "database_tables"),
        ("9. External imports", "imports")
    ]

    for title, key in sections:
        lines += ["## " + title]

        lines += [
            f"- `{item}`"
            for item in scan.get(key, [])[:80]
        ]

        if not scan.get(key):
            lines.append("- Not detected from static analysis.")

    lines += [
        "## 10. Code inventory",
        "- Classes: " + (
            ", ".join(scan.get("classes", [])[:60])
            or "Not detected"
        ),
        "- Functions: " + (
            ", ".join(scan.get("functions", [])[:80])
            or "Not detected"
        ),
        "## 11. Configuration and deployment"
    ]

    lines += [
        f"- `{item}`"
        for item in scan.get("manifests", {})
    ] or ["- No common manifests detected."]

    lines += [
        "Deployment topology: Not detected from static analysis.",
        "## 12. Security and operations",
        "- Review authentication, authorization, logging, monitoring, backups and dependency vulnerabilities.",
        "- Rotate credentials accidentally committed to source control.",
        "## 13. Risks and limitations"
    ]

    lines += [
        f"- {risk}"
        for risk in architecture.get("risks", [])
    ]

    lines += [
        "- Static scanning may miss dynamic imports, runtime routes and external infrastructure.",
        "## 14. Metrics",
        f"- Files inspected: {scan['file_count']}",
        f"- Scan truncated: {scan['truncated']}"
    ]

    return "\n".join(lines)


# --------------------------------------------------
# 7. DOCUMENTATION AGENT
# --------------------------------------------------

def documentation_agent(state):

    llm = llm_client() if state.get("llm_used") else None

    if llm:
        scan = state["scan"]

        keys = (
            "languages",
            "repository_tree",
            "manifests",
            "routes",
            "database_tables",
            "imports",
            "dependency_graph"
        )

        evidence = {
            key: scan.get(key)
            for key in keys
        }

        prompt = (
            "Write a complete Markdown technical design document "
            "covering summary, scope, technology stack, repository "
            "structure, architecture, components, flows, APIs, data, "
            "dependencies, configuration, security, deployment, "
            "operations, risks and evidence. Include a dedicated module dependency section "
            "using dependency_graph edges and list unresolved local imports separately. "
            "Do not describe import edges as proof of runtime calls.\n\n"
            "Use only the supplied evidence. Mark unknowns as "
            "'Not detected from static analysis'. Never fabricate.\n\n"
            f"Repository: {state['repository']}\n\n"
            f"Architecture:\n{json.dumps(state['architecture'])}\n\n"
            f"Evidence:\n{json.dumps(evidence, ensure_ascii=False)[:18000]}"
        )

        try:
            message = llm.invoke([
                SystemMessage(
                    content="You write precise engineering design documents."
                ),
                HumanMessage(content=prompt)
            ])

            document = (
                message.content
                if isinstance(message.content, str)
                else str(message.content)
            )

            if len(document) > 150:
                return {"tdd": document}

        except Exception as error:
            print(f"Documentation agent failed: {error}")

    return {
        "tdd": make_tdd(
            state["repository"],
            state["scan"],
            state["architecture"]
        )
    }


# --------------------------------------------------
# 8. VALIDATION AGENT
# --------------------------------------------------

def validation_agent(state):

    document = state.get("tdd", "")

    if len(document) < 100:
        document = make_tdd(
            state["repository"],
            state["scan"],
            state["architecture"]
        )

    return {"tdd": document}


# --------------------------------------------------
# 9. ARCHITECTURE DIAGRAM GENERATOR
# --------------------------------------------------



def run_agents(repo, scan):

    graph = StateGraph(State)

    # Node names must not conflict with state keys.
    graph.add_node("architecture_step", architecture_agent)
    graph.add_node("documentation_step", documentation_agent)
    graph.add_node("validation_step", validation_agent)

    graph.set_entry_point("architecture_step")

    graph.add_edge(
        "architecture_step",
        "documentation_step"
    )

    graph.add_edge(
        "documentation_step",
        "validation_step"
    )

    graph.add_edge(
        "validation_step",
        END
    )

    workflow = graph.compile()

    result = workflow.invoke({
        "repository": repo,
        "scan": scan
    })

    return {
        "architecture": result["architecture"],
        "technical_design": result["tdd"],
        "architecture_mermaid": diagram(
            result["architecture"],
            scan
        ),
        "llm_used": result.get("llm_used", False)
    }
