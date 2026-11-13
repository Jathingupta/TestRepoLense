
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

def diagram(architecture, scan):
    """Build a compact architecture view from source areas and resolved imports."""
    graph = scan.get("dependency_graph") or {}
    nodes, edges = graph.get("nodes", []), graph.get("edges", [])
    source_exts = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
                   ".java", ".go", ".cs", ".php", ".rb", ".rs"}
    paths = {
        n.get("path") for n in nodes
        if isinstance(n, dict) and n.get("path")
        and Path(n["path"]).suffix.lower() in source_exts
    }

    def area(path):
        p = path.replace("\\", "/").lower()
        if p.startswith("app/") and ("(api)" in p or "+api." in p or "/api/" in p):
            return "API routes"
        if p.startswith(("app/", "pages/", "routes/")):
            return "Screens and routing"
        if p.startswith(("components/", "ui/")):
            return "Reusable UI components"
        if p.startswith(("services/", "lib/", "utils/")):
            return "Services and utilities"
        if p.startswith(("store/", "state/")):
            return "Client state"
        if p.startswith(("models/", "schemas/", "repositories/", "db/", "database/")):
            return "Data and persistence"
        if p.startswith(("backend/", "server/")):
            return "Backend application"
        return "Other source modules"

    groups = {}
    for path in sorted(paths):
        groups.setdefault(area(path), []).append(path)
    ids = {
        "Screens and routing": "UI", "Reusable UI components": "COMP",
        "Services and utilities": "SVC", "Client state": "STATE",
        "API routes": "API", "Data and persistence": "DATA",
        "Backend application": "BACKEND", "Other source modules": "OTHER"
    }
    lines = [
        "flowchart LR",
        "    %% Nodes are source areas; edges aggregate resolved static imports.",
        '    classDef layer fill:#eaf2ff,stroke:#4778b8,color:#172b4d;',
        '    classDef note fill:#f8fafc,stroke:#94a3b8,color:#334155;'
    ]
    for label, members in groups.items():
        examples = "<br/>".join(Path(p).name for p in members[:4])
        if len(members) > 4:
            examples += f"<br/>+{len(members)-4} more"
        lines.append(
            f'    {ids[label]}["{label}<br/>{len(members)} source files<br/><small>{examples}</small>"]:::layer'
        )

    aggregate = {}
    for edge in edges:
        source, target = edge.get("source"), edge.get("target")
        if source not in paths or target not in paths:
            continue
        src, dst = area(source), area(target)
        if src != dst and src in groups and dst in groups:
            aggregate[(src, dst)] = aggregate.get((src, dst), 0) + 1
    for (src, dst), count in sorted(aggregate.items()):
        lines.append(f'    {ids[src]} -->|imports: {count}| {ids[dst]}')
    if not groups:
        lines.append('    EMPTY["No supported source modules found"]')
    lines.append('    NOTE["Arrows represent resolved static imports, not runtime calls"]:::note')
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
