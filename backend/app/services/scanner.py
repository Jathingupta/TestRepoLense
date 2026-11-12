import ast
import os
import re
from collections import Counter
from pathlib import Path

SKIP = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build", "target", ".next", "coverage"}
EXTS = {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".cs", ".php", ".rb", ".rs", ".sql", ".yaml", ".yml", ".toml", ".ini", ".xml", ".json", ".md", ".sh"}
JS_EXTENSIONS = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")
MANIFESTS = {"package.json", "requirements.txt", "pyproject.toml", "Pipfile", "pom.xml", "build.gradle", "go.mod", "Cargo.toml", "composer.json", "Gemfile", "Dockerfile", "docker-compose.yml", "docker-compose.yaml", "Makefile", ".env.example"}


def facts_py(src):
    out = {"imports": [], "classes": [], "functions": [], "routes": [], "tables": []}
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out["imports"].extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = "." * node.level
            module_name = prefix + (node.module or "")
            out["imports"].append(module_name)
            # "from package import module" and relative sibling imports
            # should be considered as possible local module dependencies.
            if node.module:
                out["imports"].extend(
                    module_name + "." + alias.name
                    for alias in node.names
                    if alias.name != "*"
                )
            elif node.level:
                out["imports"].extend(prefix + alias.name for alias in node.names)
        elif isinstance(node, ast.ClassDef):
            out["classes"].append(node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out["functions"].append(node.name)
            for decorator in node.decorator_list:
                if (isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Attribute)
                    and decorator.args
                    and isinstance(decorator.args[0], ast.Constant)
                    and decorator.func.attr.lower() in {"get", "post", "put", "patch", "delete"}):
                    out["routes"].append(str(decorator.args[0].value))
    return {key: sorted(set(values))[:100] for key, values in out.items()}


def facts_text(path, src):
    out = {"imports": [], "classes": [], "functions": [], "routes": [], "tables": []}
    if path.suffix.lower() in {".js", ".jsx", ".ts", ".tsx"}:
        patterns = [
            r"\bfrom\s*['\"]([^'\"]+)['\"]",
            r"\bimport\s*['\"]([^'\"]+)['\"]",
            r"\bimport\s*\(\s*['\"]([^'\"]+)['\"]\s*\)",
            r"\brequire\s*\(\s*['\"]([^'\"]+)['\"]\s*\)",
        ]
        out["imports"] = sorted({match for pattern in patterns for match in re.findall(pattern, src)})[:150]
        out["classes"] = re.findall(r"\bclass\s+([A-Za-z_$][\w$]*)", src)[:100]
        out["functions"] = re.findall(r"\bfunction\s+([A-Za-z_$][\w$]*)", src)[:100]
        out["routes"] = re.findall(r"\.(?:get|post|put|patch|delete)\(['\"]([^'\"]+)", src, re.I)[:100]
    if path.suffix.lower() == ".sql":
        out["tables"] = re.findall(r"(?i)(?:from|join|into|table)\s+([A-Za-z_][\w.]*)", src)[:100]
    return out


def _candidate_paths(source_path, import_name, language):
    """Return plausible repository-relative targets for a local import."""
    candidates = []
    if language in JS_EXTENSIONS:
        if not import_name.startswith("."):
            return candidates
        base = (Path(source_path).parent / import_name).as_posix()
        candidates.append(base)
        for extension in JS_EXTENSIONS:
            candidates.append(base + extension)
        for extension in JS_EXTENSIONS:
            candidates.append((Path(base) / ("index" + extension)).as_posix())
    elif language == ".py":
        module = import_name
        if module.startswith("."):
            level = len(module) - len(module.lstrip("."))
            suffix = module[level:]
            parent = Path(source_path).parent
            for _ in range(max(level - 1, 0)):
                parent = parent.parent
            base = (parent / suffix.replace(".", "/")).as_posix() if suffix else parent.as_posix()
        else:
            base = module.replace(".", "/")
        if base:
            candidates.extend([base + ".py", (Path(base) / "__init__.py").as_posix()])
    return [Path(item).as_posix() for item in candidates]


def build_dependency_graph(files):
    """Resolve only repository-local imports; unresolved third-party imports are not edges."""
    paths = {item["path"] for item in files}
    nodes = [
        {
            "id": item["path"],
            "path": item["path"],
            "language": item["language"],
            "symbols": {
                "classes": item["facts"].get("classes", []),
                "functions": item["facts"].get("functions", []),
            },
        }
        for item in files
    ]
    edges = []
    unresolved = []
    for item in files:
        source = item["path"]
        language = item["language"]
        for import_name in item["facts"].get("imports", []):
            targets = _candidate_paths(source, import_name, language)
            target = next((candidate for candidate in targets if candidate in paths), None)
            if target:
                edges.append({
                    "source": source,
                    "target": target,
                    "relation": "imports",
                    "evidence": import_name,
                    "confidence": "high",
                })
            elif import_name.startswith(".") or (language == ".py" and import_name and import_name.split(".")[0] in {Path(p).parts[0] for p in paths}):
                unresolved.append({"source": source, "import": import_name, "reason": "No matching repository file found"})
    # Stable, duplicate-free output makes reports and tests deterministic.
    unique_edges = {(e["source"], e["target"], e["evidence"]): e for e in edges}
    return {
        "nodes": nodes,
        "edges": sorted(unique_edges.values(), key=lambda e: (e["source"], e["target"], e["evidence"])),
        "unresolved_local_imports": unresolved[:300],
        "relationship_scope": "Resolved repository-local imports only; this is not a complete runtime call graph.",
    }


def scan_repository(repo, max_files, max_file_bytes, max_total_bytes, include_tests):
    found = []
    manifests = {}
    langs = Counter()
    imports, routes, tables, classes, functions = set(), set(), set(), set(), set()
    total = 0
    tree = []

    for current, dirs, names in os.walk(repo):
        dirs[:] = [directory for directory in dirs if directory not in SKIP]
        rel = Path(current).relative_to(repo)
        if len(rel.parts) < 5:
            tree.append((str(rel) if str(rel) != "." else ".") + "/")
        for name in sorted(names):
            path = Path(current) / name
            relpath = path.relative_to(repo).as_posix()
            if not include_tests and re.search(r"(^|/)(tests?|__tests__)/", relpath, re.I):
                continue
            if name in MANIFESTS or name.endswith((".csproj", ".sln")):
                try:
                    manifests[relpath] = path.read_text(encoding="utf-8", errors="replace")[:18000]
                except OSError:
                    pass
            if path.suffix.lower() not in EXTS and name not in {"Dockerfile", "Makefile"}:
                continue
            if len(found) >= max_files or total >= max_total_bytes:
                break
            try:
                size = path.stat().st_size
                if size > max_file_bytes:
                    continue
                src = path.read_bytes()[:max_file_bytes].decode("utf-8", errors="replace")
            except OSError:
                continue
            if "\x00" in src:
                continue
            total += size
            ext = path.suffix.lower() or name
            langs[ext] += 1
            facts = facts_py(src) if ext == ".py" else facts_text(path, src)
            imports.update(facts["imports"])
            routes.update(facts["routes"])
            tables.update(facts["tables"])
            classes.update(facts["classes"])
            functions.update(facts["functions"])
            found.append({"path": relpath, "language": ext, "bytes": size, "facts": facts})

    dependency_graph = build_dependency_graph(found)
    return {
        "file_count": len(found),
        "total_bytes_scanned": total,
        "truncated": len(found) >= max_files or total >= max_total_bytes,
        "languages": dict(langs.most_common()),
        "repository_tree": "\n".join(tree[:200]),
        "files": found,
        "manifests": manifests,
        "imports": sorted(imports)[:150],
        "routes": sorted(routes)[:120],
        "database_tables": sorted(tables)[:120],
        "classes": sorted(classes)[:150],
        "functions": sorted(functions)[:200],
        "dependency_graph": dependency_graph,
    }
