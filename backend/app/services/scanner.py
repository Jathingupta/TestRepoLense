import ast, os, re
from pathlib import Path
from collections import Counter
SKIP={".git","node_modules","venv",".venv","__pycache__","dist","build","target",".next","coverage"}
EXTS={".py",".js",".jsx",".ts",".tsx",".java",".go",".cs",".php",".rb",".rs",".sql",".yaml",".yml",".toml",".ini",".xml",".json",".md",".sh"}
MANIFESTS={"package.json","requirements.txt","pyproject.toml","Pipfile","pom.xml","build.gradle","go.mod","Cargo.toml","composer.json","Gemfile","Dockerfile","docker-compose.yml","docker-compose.yaml","Makefile",".env.example"}
def facts_py(src):
    out={"imports":[],"classes":[],"functions":[],"routes":[],"tables":[]}
    try: tree=ast.parse(src)
    except SyntaxError: return out
    for n in ast.walk(tree):
        if isinstance(n,ast.Import): out["imports"] += [a.name for a in n.names]
        elif isinstance(n,ast.ImportFrom): out["imports"].append(n.module or "")
        elif isinstance(n,ast.ClassDef): out["classes"].append(n.name)
        elif isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):
            out["functions"].append(n.name)
            for d in n.decorator_list:
                if isinstance(d,ast.Call) and isinstance(d.func,ast.Attribute) and d.args and isinstance(d.args[0],ast.Constant) and d.func.attr.lower() in {"get","post","put","patch","delete"}: out["routes"].append(str(d.args[0].value))
    return {k:sorted(set(v))[:100] for k,v in out.items()}
def facts_text(path,src):
    out={"imports":[],"classes":[],"functions":[],"routes":[],"tables":[]}
    if path.suffix.lower() in {".js",".jsx",".ts",".tsx"}:
        out["imports"]=re.findall(r"from\s+['\"]([^'\"]+)['\"]",src)[:100]
        out["classes"]=re.findall(r"\bclass\s+([A-Za-z_$][\w$]*)",src)[:100]
        out["functions"]=re.findall(r"\bfunction\s+([A-Za-z_$][\w$]*)",src)[:100]
        out["routes"]=re.findall(r"\.(?:get|post|put|patch|delete)\(['\"]([^'\"]+)",src,re.I)[:100]
    if path.suffix.lower()==".sql":
        out["tables"]=re.findall(r"(?i)(?:from|join|into|table)\s+([A-Za-z_][\w.]*)",src)[:100]
    return out
def scan_repository(repo,max_files,max_file_bytes,max_total_bytes,include_tests):
    found=[]; manifests={}; langs=Counter(); imports=set(); routes=set(); tables=set(); classes=set(); functions=set(); total=0; tree=[]
    for current,dirs,names in os.walk(repo):
        dirs[:]=[d for d in dirs if d not in SKIP]
        rel=Path(current).relative_to(repo)
        if len(rel.parts)<5: tree.append((str(rel) if str(rel)!="." else ".")+"/")
        for name in sorted(names):
            path=Path(current)/name; relpath=path.relative_to(repo).as_posix()
            if not include_tests and re.search(r"(^|/)(tests?|__tests__)/",relpath,re.I): continue
            if name in MANIFESTS or name.endswith((".csproj",".sln")):
                try: manifests[relpath]=path.read_text(encoding="utf-8",errors="replace")[:18000]
                except OSError: pass
            if path.suffix.lower() not in EXTS and name not in {"Dockerfile","Makefile"}: continue
            if len(found)>=max_files or total>=max_total_bytes: break
            try:
                size=path.stat().st_size
                if size>max_file_bytes: continue
                src=path.read_bytes()[:max_file_bytes].decode("utf-8",errors="replace")
            except OSError: continue
            if "\x00" in src: continue
            total+=size; ext=path.suffix.lower() or name; langs[ext]+=1
            f=facts_py(src) if ext==".py" else facts_text(path,src)
            imports.update(f["imports"]); routes.update(f["routes"]); tables.update(f["tables"]); classes.update(f["classes"]); functions.update(f["functions"])
            found.append({"path":relpath,"language":ext,"bytes":size,"facts":f})
    return {"file_count":len(found),"total_bytes_scanned":total,"truncated":len(found)>=max_files or total>=max_total_bytes,
    "languages":dict(langs.most_common()),"repository_tree":"\n".join(tree[:200]),"files":found,"manifests":manifests,
    "imports":sorted(imports)[:150],"routes":sorted(routes)[:120],"database_tables":sorted(tables)[:120],
    "classes":sorted(classes)[:150],"functions":sorted(functions)[:200]}
