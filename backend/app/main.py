import json,re,uuid,subprocess
from pathlib import Path
from fastapi import FastAPI,HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from app.core.config import settings
from app.models import AnalyzeRequest,AnalyzeResponse
from app.services.repository import clone_repository,RepositoryError
from app.services.scanner import scan_repository
from app.agents.graph import run_agents
from app.services.render import render_pdf,render_svg
GENERATED=Path(__file__).resolve().parents[1]/"generated"; GENERATED.mkdir(exist_ok=True)
app=FastAPI(title="RepoLens API",version="1.0.0")
app.add_middleware(CORSMiddleware,allow_origins=settings.allowed_origins,allow_credentials=False,allow_methods=["GET","POST"],allow_headers=["Content-Type"])
@app.get("/api/health")
def health(): return {"status":"ok","llm_configured":bool(settings.groq_api_key)}
@app.post("/api/analyze",response_model=AnalyzeResponse)
def analyze(req:AnalyzeRequest):
    temp=None; aid=uuid.uuid4().hex
    try:
        temp,repo=clone_repository(req.repo_url,req.branch,req.access_token,settings.clone_timeout_seconds)
        remote=subprocess.run(["git","-C",str(repo),"remote","get-url","origin"],capture_output=True,text=True,timeout=5)
        name=remote.stdout.strip().rstrip("/").split("/")[-1].removesuffix(".git") if remote.returncode==0 else repo.name
        scan=scan_repository(repo,settings.max_files,settings.max_file_bytes,settings.max_total_bytes,req.include_tests)
        result=run_agents(name,scan); folder=GENERATED/aid; folder.mkdir(parents=True)
        (folder/"architecture.mmd").write_text(result["architecture_mermaid"],encoding="utf-8")
        (folder/"technical-design.md").write_text(result["technical_design"],encoding="utf-8")
        render_pdf(result["technical_design"],folder/"technical-design.pdf")
        svg=render_svg(result["architecture_mermaid"],folder/"architecture.svg")
        safe={k:v for k,v in scan.items() if k!="code_evidence"}
        analysis={"repository":name,"architecture":result["architecture"],"scan":safe,"llm_used":result["llm_used"]}
        (folder/"analysis.json").write_text(json.dumps(analysis,indent=2,ensure_ascii=False),encoding="utf-8")
        return AnalyzeResponse(analysis_id=aid,repository=name,summary=result["architecture"].get("summary","Analysis complete."),
        architecture_mermaid=result["architecture_mermaid"],technical_design_markdown=result["technical_design"],analysis=analysis,llm_used=result["llm_used"],
        downloads={"markdown":f"/api/reports/{aid}/technical-design.md","pdf":f"/api/reports/{aid}/technical-design.pdf","mermaid":f"/api/reports/{aid}/architecture.mmd","svg":f"/api/reports/{aid}/architecture.svg" if svg else "","json":f"/api/reports/{aid}/analysis.json"})
    except RepositoryError as e: raise HTTPException(status_code=400,detail=str(e))
    except Exception as e: raise HTTPException(status_code=500,detail=f"Analysis failed: {type(e).__name__}: {e}")
    finally:
        if temp: temp.cleanup()
ALLOWED={"technical-design.md","technical-design.pdf","architecture.mmd","architecture.svg","analysis.json"}
@app.get("/api/reports/{analysis_id}/{filename}")
def download(analysis_id:str,filename:str):
    if not re.fullmatch(r"[a-f0-9]{32}",analysis_id) or filename not in ALLOWED: raise HTTPException(status_code=404,detail="Report not found")
    path=GENERATED/analysis_id/filename
    if not path.is_file(): raise HTTPException(status_code=404,detail="Report not found")
    return FileResponse(path,filename=filename)
