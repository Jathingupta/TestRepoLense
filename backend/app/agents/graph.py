
import json
import re
from typing import TypedDict

from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from app.core.config import settings


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

def fallback_architecture(repo, scan):
    extensions = set(scan.get("languages", {}))
    parts = []

    if ".py" in extensions:
        parts.append("Python application/services")

    if extensions.intersection({".js", ".jsx", ".ts", ".tsx"}):
        parts.append("JavaScript/TypeScript application")

    if ".java" in extensions:
        parts.append("Java application")

    if ".go" in extensions:
        parts.append("Go services")

    if scan.get("database_tables") or ".sql" in extensions:
        parts.append("SQL/data layer")

    if not parts:
        parts = ["Application source code"]

    return {
        "summary": (
            f"{repo}: {scan['file_count']} files inspected. "
            f"Detected: {', '.join(parts)}."
        ),
        "components": [
            {
                "name": component,
                "description": (
                    "Detected from source types and repository evidence."
                )
            }
            for component in parts
        ],
        "flows": [
            "Module and request flows require runtime verification.",
            "SQL references appear only when static SQL patterns are found."
        ],
        "risks": [
            "Static analysis cannot prove runtime call paths or deployment topology.",
            "Review inferred boundaries with maintainers."
        ]
    }


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

def architecture_agent(state):
    llm = llm_client()
    scan = state["scan"]

    if not llm:
        return {
            "architecture": fallback_architecture(
                state["repository"], scan
            ),
            "llm_used": False
        }

    keys = (
        "languages",
        "repository_tree",
        "manifests",
        "imports",
        "routes",
        "database_tables",
        "classes",
        "functions",
        "dependency_graph"
    )

    evidence = {
        key: scan.get(key)
        for key in keys
    }

    prompt = (
        "Return ONLY valid JSON with these fields:\n"
        "summary: string\n"
        "components: array of objects with name and description\n"
        "flows: array of strings\n"
        "risks: array of strings\n\n"
        "Use only the provided repository evidence. "
        "Never invent cloud infrastructure, databases, authentication "
        "or deployment details. Clearly mark inferences and cite paths.\n\n"
        f"Repository: {state['repository']}\n\n"
        f"Evidence:\n{json.dumps(evidence, ensure_ascii=False)[:18000]}"
    )

    try:
        message = llm.invoke([
            SystemMessage(
                content="You are an evidence-led senior software architect."
            ),
            HumanMessage(content=prompt)
        ])

        raw = (
            message.content
            if isinstance(message.content, str)
            else str(message.content)
        )

        architecture = extract_json(raw)

        if not isinstance(architecture.get("components"), list):
            raise ValueError("Invalid architecture JSON: components missing")

        return {
            "architecture": architecture,
            "llm_used": True
        }

    except Exception as error:
        print(f"Architecture agent failed: {error}")

        return {
            "architecture": fallback_architecture(
                state["repository"], scan
            ),
            "llm_used": False
        }


# --------------------------------------------------
# 6. TECHNICAL DESIGN DOCUMENT GENERATOR
# --------------------------------------------------

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

    lines += [
        f"- `{key}`: {value} files"
        for key, value in scan.get("languages", {}).items()
    ] or ["- Not detected."]

    lines += [
        "## 4. Repository structure",
        "```text",
        scan.get("repository_tree", "Not detected."),
        "```",
        "## 5. Architecture",
        "### Components"
    ]

    lines += [
        f"- **{component.get('name', 'Component')}**: "
        f"{component.get('description', '')}"
        for component in architecture.get("components", [])
    ] or ["- Not detected."]

    lines += ["### Flows"]

    lines += [
        f"- {flow}"
        for flow in architecture.get("flows", [])
    ]

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
            "operations, risks and evidence.\n\n"
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

def diagram(architecture, scan):
    """
    Render repository-local import relationships discovered by the scanner.
    No sequential or inferred edges are added.
    """
    graph_data = scan.get("dependency_graph") or {}
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    # Keep diagrams readable for large repositories.
    visible_nodes = nodes[:30]
    node_ids = {
        node["path"]: f"N{index}"
        for index, node in enumerate(visible_nodes)
        if node.get("path")
    }

    lines = [
        "flowchart LR",
        '    classDef source fill:#e8f1ff,stroke:#3267a8,color:#142b45;',
        '    classDef isolated fill:#f4f4f5,stroke:#71717a,color:#27272a;'
    ]

    for path, node_id in node_ids.items():
        label = path.replace("\\", "/")
        label = re.sub(r"[^A-Za-z0-9_./ -]", "", label)[-65:]
        lines.append(f'    {node_id}["{label}"]')

    rendered_edges = 0
    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")
        if source in node_ids and target in node_ids:
            lines.append(f'    {node_ids[source]} -->|imports| {node_ids[target]}')
            rendered_edges += 1
            if rendered_edges >= 60:
                break

    if not rendered_edges:
        lines.append('    NoEdges["No repository-local import relationships resolved"]')
        lines.append('    NoEdges:::isolated')

    if len(nodes) > len(visible_nodes):
        lines.append(
            f'    More["{len(nodes) - len(visible_nodes)} additional files omitted from this view"]'
        )

    return "\n".join(lines)


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
