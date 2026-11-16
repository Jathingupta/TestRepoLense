
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
    """Parse a JSON object from a model response, including fenced responses."""
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("The model returned an empty response")

    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    start = cleaned.find("{")
    if start < 0:
        raise ValueError("No JSON object found in model response")

    # raw_decode avoids the greedy-brace matching that can accidentally include
    # explanatory text after the JSON object.
    try:
        value, _ = json.JSONDecoder().raw_decode(cleaned[start:])
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Invalid JSON at character {error.pos}: {error.msg}"
        ) from error

    if not isinstance(value, dict):
        raise ValueError("Architecture response must be a JSON object")
    return value


def _message_text(message):
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


def _response_diagnostics(message, raw):
    metadata = getattr(message, "response_metadata", {}) or {}
    usage = getattr(message, "usage_metadata", {}) or {}
    finish_reason = metadata.get("finish_reason", "unknown")
    excerpt = raw[:240].replace("\n", " ")
    return (
        f"finish_reason={finish_reason}, chars={len(raw)}, "
        f"usage={usage or 'unavailable'}, excerpt={excerpt!r}"
    )


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
            "api_handlers": facts.get("api_handlers", [])[:10],
            "api_calls": facts.get("api_calls", [])[:12],
            "tables": facts.get("tables", [])[:20],
            "database_operations": facts.get("database_operations", [])[:12],
            "integrations": facts.get("integrations", [])[:12],
            "environment_variables": facts.get("environment_variables", [])[:12],
            "ui_actions": facts.get("ui_actions", [])[:12],
            "evidence_snippets": facts.get("evidence_snippets", [])[:12],
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
    evidence_text = json.dumps(evidence, ensure_ascii=False)
    # Keep the prompt bounded; the scanner's full inventory remains available
    # to the report generator even when the LLM receives a compact evidence view.
    evidence_text = evidence_text[:18000]
    prompt = (
        "Act as a senior software architect. Return one valid JSON object only. "
        "Do not use Markdown fences, comments, trailing commas, or text outside JSON. "
        "The response must be complete and must match this schema "
        "(examples are placeholders, not repository facts):\n"
        f"{json.dumps(schema, ensure_ascii=False)}\n\n"
        "Create a product- and behavior-oriented architecture, NOT a folder, file, class, "
        "or object inventory. Infer the application's actual business capabilities from the "
        "combined evidence: screens and user actions, API handlers and methods, outgoing API calls, "
        "database operations/table names, authentication/payment/maps integrations, and source "
        "snippets. Name components by their responsibility (for example 'Ride creation endpoint' "
        "or 'Driver discovery/map experience'), not by directory names or generic labels such as "
        "'module_1', 'utilities', or 'components'. Explain each component in terms of inputs, "
        "work performed, outputs, and downstream dependencies when evidence supports those details. "
        "Identify end-to-end user workflows by connecting UI actions to API handlers, service logic, "
        "external providers and persistence. Do not claim a runtime call merely because an import "
        "exists: distinguish direct code evidence from inferred sequence. "
        "A package manifest proves a dependency is declared, not that it is actively integrated. "
        "External integrations must cite source files showing imports, initialization or API usage. "
        "Every component must cite exact evidence_paths from evidence.files or evidence.manifests. "
        "Every relationship must cite at least one path belonging to each connected component. "
        "Every flow must cite exact scanned paths and include only components in the supported sequence. "
        "Imports prove module dependency, not runtime calls. Label inferred runtime behavior with "
        "confidence='inferred'. Never invent paths, APIs, providers, databases, infrastructure or "
        "business flows. Omit relationships that cannot be supported. Prefer fewer specific, "
        "well-explained components over many generic categories.\n\n"
        f"Repository: {state['repository']}\nEvidence:\n{evidence_text}"
    )
    messages = [
        SystemMessage(content=(
            "Produce precise evidence-led software architecture. Never hallucinate repository "
            "components or relationships. Output valid JSON only."
        )),
        HumanMessage(content=prompt)
    ]

    try:
        # Groq's OpenAI-compatible JSON mode reduces malformed model responses.
        json_llm = llm.bind(response_format={"type": "json_object"})
        message = json_llm.invoke(messages)
        raw = _message_text(message)

        try:
            parsed = extract_json(raw)
        except ValueError as parse_error:
            diagnostics = _response_diagnostics(message, raw)
            print(
                "Architecture agent JSON parse failed; requesting one correction. "
                f"{parse_error}; {diagnostics}"
            )
            repair_messages = messages + [
                message,
                HumanMessage(content=(
                    "Your previous response was not valid JSON. Correct the response and "
                    "return the complete architecture as one valid JSON object only. "
                    "Do not add Markdown or explanations. Preserve the required schema, "
                    "use only the supplied evidence, and ensure all strings are correctly "
                    "escaped and all arrays/objects are closed."
                ))
            ]
            repaired_message = json_llm.invoke(repair_messages)
            repaired_raw = _message_text(repaired_message)
            try:
                parsed = extract_json(repaired_raw)
            except ValueError as repair_error:
                print(
                    "Architecture agent JSON correction failed; using evidence-based fallback. "
                    f"{repair_error}; {_response_diagnostics(repaired_message, repaired_raw)}"
                )
                raise

        architecture = validate_architecture(parsed, scan)
        if not architecture["components"]:
            raise ValueError("LLM returned no components tied to scanned source paths")
        return {"architecture": architecture, "llm_used": True}
    except Exception as error:
        print(f"Architecture agent failed; using evidence-based fallback: {error}")
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


def _md_table(headers, rows):
    def cell(value):
        return str(value if value not in (None, "") else "—").replace("|", "\\|").replace("\n", " ")
    output = [
        "| " + " | ".join(cell(value) for value in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    output.extend("| " + " | ".join(cell(value) for value in row) + " |" for row in rows)
    return output


def make_tdd(repo, scan, architecture):
    files = {item.get("path"): item for item in scan.get("files", [])}
    lines = [
        "# Technical Design Document",
        "## 1. Executive summary",
        architecture.get("summary", "Architecture summary not available from static analysis."),
        "## 2. Scope and method",
        (f"Static inspection covered {scan.get('file_count', 0)} files and "
         f"{scan.get('total_bytes_scanned', 0)} bytes. Source code was not executed. "
         "Relationships are labelled as static evidence or inference."),
        "## 3. Technology stack",
        *technology_stack_lines(scan),
        "## 4. Repository structure",
        "Repository tree:",
        scan.get("repository_tree", "Not detected."),
        "## 5. Architecture",
        "### Components",
    ]

    component_rows = [[
        item.get("name"), item.get("layer"), item.get("description"),
        ", ".join(item.get("evidence_paths", [])),
    ] for item in architecture.get("components", [])]
    lines.extend(_md_table(
        ["Component", "Layer", "Responsibility", "Evidence files"], component_rows
    ) if component_rows else ["- No components met the evidence threshold."])

    lines.append("### Relationships")
    relationship_rows = [[
        item.get("source"), item.get("target"), item.get("label", item.get("type")),
        item.get("confidence", "unknown"), ", ".join(item.get("evidence_paths", [])),
    ] for item in architecture.get("relationships", [])]
    lines.extend(_md_table(
        ["Source", "Target", "Relationship", "Confidence", "Evidence files"], relationship_rows
    ) if relationship_rows else ["- No cross-component relationships met the evidence threshold."])

    lines.append("### User and system workflows")
    flow_rows = [[
        flow.get("name"), flow.get("description"), " → ".join(flow.get("steps", [])),
        ", ".join(flow.get("evidence_paths", [])),
    ] for flow in architecture.get("flows", [])]
    lines.extend(_md_table(
        ["Workflow", "Description", "Steps", "Evidence files"], flow_rows
    ) if flow_rows else ["- No end-to-end flow met the evidence threshold."])

    dependency_graph = scan.get("dependency_graph", {})
    lines += [
        "## 6. Module dependency relationships",
        dependency_graph.get("relationship_scope", "Repository-local relationships were not available."),
    ]
    dependency_edges = dependency_graph.get("edges", [])
    lines.extend([
        f"- {edge['source']} imports {edge['target']} (import: {edge['evidence']})."
        for edge in dependency_edges[:100]
    ] or ["- No repository-local import relationships were resolved."])

    unresolved = dependency_graph.get("unresolved_local_imports", [])
    if unresolved:
        lines += ["### Unresolved local module imports"]
        lines.extend([
            f"- {item['source']}: {item['import']} ({item.get('reason', 'unresolved')})"
            for item in unresolved[:50]
        ])

    lines += ["## 7. API surface"]
    endpoint_rows = [[
        endpoint.get("method"), endpoint.get("route"), endpoint.get("path"),
        ", ".join(endpoint.get("request_fields", [])) or "Not statically identified",
        ", ".join(endpoint.get("response_patterns", [])) or "Not statically identified",
    ] for endpoint in scan.get("api_endpoints", [])]
    lines.extend(_md_table(
        ["Method", "Route", "Source file", "Detected request fields", "Response pattern"],
        endpoint_rows
    ) if endpoint_rows else ["- API handlers were not detected from static analysis."])

    lines += ["## 8. Data layer"]
    data_rows = []
    for table in scan.get("database_tables", []):
        evidence = []
        operations = set()
        for path, item in files.items():
            facts = item.get("facts", {})
            if table in facts.get("tables", []):
                evidence.append(path)
                operations.update(facts.get("database_operations", []))
        data_rows.append([table, ", ".join(sorted(operations)) or "Not identified",
                          ", ".join(evidence) or "Evidence path not available"])
    lines.extend(_md_table(
        ["Table or entity", "Detected database operations", "Evidence files"], data_rows
    ) if data_rows else ["- No database table names were confidently identified."])
    lines.append("Column-level schema details are included only when explicit schema or migration evidence is detected.")

    lines += ["## 9. External integrations"]
    integration_rows = []
    for integration in scan.get("integrations", []):
        evidence = [
            path for path, item in files.items()
            if integration in item.get("facts", {}).get("integrations", [])
        ]
        integration_rows.append([integration, ", ".join(evidence)])
    lines.extend(_md_table(
        ["Integration", "Source evidence"], integration_rows
    ) if integration_rows else ["- No external integrations were detected in source files."])

    lines += ["## 10. External package imports"]
    package_imports = scan.get("external_imports", [])
    lines.extend([f"- {item}" for item in package_imports[:100]]
                 or ["- No external package imports were identified."])
    if scan.get("asset_imports"):
        lines += ["### Asset imports (not external packages)"]
        lines.extend([f"- {item}" for item in scan["asset_imports"][:60]])

    lines += [
        "## 11. Code inventory",
        "- Classes: " + (", ".join(scan.get("classes", [])[:60]) or "Not detected"),
        "- Functions: " + (", ".join(scan.get("functions", [])[:80]) or "Not detected"),
        "## 12. Configuration and deployment",
    ]
    lines.extend([f"- {item}" for item in scan.get("manifests", {})]
                 or ["- No common manifests detected."])
    lines += [
        "- Environment variables referenced in source: "
        + (", ".join(scan.get("environment_variables", [])) or "Not detected"),
        "Deployment topology: Not detected from static analysis.",
        "## 13. Security and operations",
        "- Static analysis does not prove that authentication, authorization, secrets handling, logging, monitoring or backups are correctly configured.",
        "- Review dependency vulnerabilities and ensure credentials are stored outside source control.",
        "## 14. Risks and limitations",
    ]
    lines.extend([f"- {risk}" for risk in architecture.get("risks", [])]
                 or ["- No additional source-backed risks were identified by the architecture model."])
    lines += [
        "- Static scanning may miss dynamic imports, indirect calls, runtime routes and infrastructure outside the repository.",
        "- A resolved import is evidence of module dependency, not proof of runtime execution.",
        "## 15. Metrics",
        f"- Files inspected: {scan.get('file_count', 0)}",
        f"- Scan truncated: {scan.get('truncated', False)}",
    ]
    return "\n".join(lines)


# --------------------------------------------------
# 7. DOCUMENTATION AGENT
# --------------------------------------------------

def documentation_agent(state):
    # Build report sections deterministically from validated architecture and
    # scanner evidence. LLM-generated prose previously omitted structured API
    # and data details and could silently drop Markdown tables.
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
