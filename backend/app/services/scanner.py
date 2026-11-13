import ast
import os
import re
from collections import Counter
from pathlib import Path

SKIP = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build", "target", ".next", "coverage"}
EXTS = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".java", ".go", ".cs", ".php", ".rb", ".rs", ".sql", ".yaml", ".yml", ".toml", ".ini", ".xml", ".json", ".md", ".sh"}
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


def _strip_json_comments(source):
    """Remove // and /* */ comments while preserving comment-like text in strings."""
    result = []
    index = 0
    in_string = False
    escaped = False
    quote = ""
    while index < len(source):
        char = source[index]
        next_char = source[index + 1] if index + 1 < len(source) else ""
        if in_string:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                in_string = False
            index += 1
            continue
        if char in {"'", '"'}:
            in_string = True
            quote = char
            result.append(char)
            index += 1
            continue
        if char == "/" and next_char == "/":
            while index < len(source) and source[index] not in "\r\n":
                index += 1
            continue
        if char == "/" and next_char == "*":
            index += 2
            while index + 1 < len(source) and source[index:index + 2] != "*/":
                index += 1
            index = min(index + 2, len(source))
            result.append(" ")
            continue
        result.append(char)
        index += 1
    return "".join(result)


def _load_ts_configs(manifests):
    """Read repository tsconfig/jsconfig path aliases from already-scanned manifests."""
    configs = []
    for config_path, raw in (manifests or {}).items():
        if Path(config_path).name not in {"tsconfig.json", "jsconfig.json"}:
            continue
        try:
            cleaned = _strip_json_comments(raw)
            cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
            config = json.loads(cleaned)
        except (json.JSONDecodeError, TypeError):
            continue
        compiler = config.get("compilerOptions", {})
        config_dir = Path(config_path).parent
        base_url = compiler.get("baseUrl")
        base_dir = (config_dir / base_url).as_posix() if base_url else config_dir.as_posix()
        paths = compiler.get("paths", {})
        if isinstance(paths, dict):
            configs.append({
                "directory": config_dir.as_posix(),
                "base_dir": Path(base_dir).as_posix(),
                "paths": paths,
            })
    # More deeply nested configs take precedence over parent configs.
    return sorted(configs, key=lambda item: len(Path(item["directory"]).parts), reverse=True)


def _is_within(path, directory):
    directory = directory.rstrip("/")
    return not directory or path == directory or path.startswith(directory + "/")


def _resolve_import_candidates(source_path, import_name, language, ts_configs):
    """Return candidate paths for relative, baseUrl and configured TS/JS alias imports."""
    if language not in JS_EXTENSIONS:
        return _candidate_paths(source_path, import_name, language)

    candidates = []
    source = Path(source_path).as_posix()
    matching_configs = [
        config for config in ts_configs
        if _is_within(source, config["directory"])
    ]

    if import_name.startswith("."):
        bases = [(Path(source_path).parent / import_name).as_posix()]
    else:
        bases = []
        for config in matching_configs:
            for pattern, replacements in config["paths"].items():
                if not isinstance(replacements, list):
                    continue
                if "*" in pattern:
                    prefix, suffix = pattern.split("*", 1)
                    if not import_name.startswith(prefix) or not import_name.endswith(suffix):
                        continue
                    middle = import_name[len(prefix):len(import_name) - len(suffix) if suffix else None]
                    for replacement in replacements:
                        if isinstance(replacement, str):
                            target = replacement.replace("*", middle)
                            bases.append((Path(config["base_dir"]) / target).as_posix())
                elif import_name == pattern:
                    bases.extend(
                        (Path(config["base_dir"]) / target).as_posix()
                        for target in replacements if isinstance(target, str)
                    )
        # TypeScript also permits baseUrl-based imports without an explicit paths alias.
        for config in matching_configs:
            bases.append((Path(config["base_dir"]) / import_name).as_posix())

    for base in bases:
        candidates.append(base)
        for extension in JS_EXTENSIONS:
            candidates.append(base + extension)
        for extension in JS_EXTENSIONS:
            candidates.append((Path(base) / ("index" + extension)).as_posix())
        # CommonJS/TypeScript projects frequently omit JSON extensions in imports.
        candidates.append(base + ".json")

    return list(dict.fromkeys(Path(item).as_posix() for item in candidates))


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


def build_dependency_graph(files, manifests=None):
    """Resolve repository-local imports, including tsconfig/jsconfig path aliases."""
    paths = {item["path"] for item in files}
    ts_configs = _load_ts_configs(manifests or {})
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
            targets = _resolve_import_candidates(source, import_name, language, ts_configs)
            resolved = []
            for candidate in targets:
                if candidate in paths:
                    resolved.append(candidate)
                else:
                    matches = [
                        path for path in paths
                        if path.endswith("/" + candidate)
                    ]
                    if len(matches) == 1:
                        resolved.append(matches[0])
                    elif len(matches) > 1:
                        unresolved.append({
                            "source": source,
                            "import": import_name,
                            "reason": f"Ambiguous local module path: {candidate}",
                        })
            target = next((item for item in resolved if item != source), None)
            if target:
                edges.append({
                    "source": source,
                    "target": target,
                    "relation": "imports",
                    "evidence": import_name,
                    "confidence": "high",
                })
            elif import_name.startswith(".") or (
                language in JS_EXTENSIONS
                and not import_name.startswith(".")
                and any(
                    import_name == pattern
                    or ("*" in pattern and import_name.startswith(pattern.split("*", 1)[0]))
                    for config in ts_configs
                    for pattern in config["paths"]
                )
            ) or (
                language == ".py"
                and import_name
                and any(import_name.split(".")[0] in Path(path).parts for path in paths)
            ):
                unresolved.append({
                    "source": source,
                    "import": import_name,
                    "reason": "No matching repository file found",
                })
    unique_edges = {(e["source"], e["target"], e["evidence"]): e for e in edges}
    return {
        "nodes": nodes,
        "edges": sorted(unique_edges.values(), key=lambda e: (e["source"], e["target"], e["evidence"])),
        "unresolved_local_imports": unresolved[:300],
        "relationship_scope": "Resolved repository-local imports only; this is not a complete runtime call graph.",
        "typescript_configs": [config["directory"] for config in ts_configs],
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

    dependency_graph = build_dependency_graph(found, manifests)
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
