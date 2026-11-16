# RepoLens — Repository Architecture Analyst

React/Vite frontend, FastAPI backend, LangGraph agents, Groq LLM, Python AST/static scanning, Mermaid diagrams and ReportLab PDF export.

## Requirements
Python 3.11+, Node.js 20+, Git on PATH. Install backend dependencies with `pip install -r requirements.txt`; Groq API key is optional; deterministic fallback works without it.

## Backend
```bash
cd backend
python -m venv .venv
# Windows: .venv\\Scripts\\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
# Copy .env.example to .env and set GROQ_API_KEY
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
API docs: http://127.0.0.1:8000/docs

## Frontend
```bash
cd frontend
npm install
npm run dev
```
Open http://localhost:5173.

Paste an HTTPS Git URL. For private repositories, provide a read-only token. The token is used only during clone and is not saved to reports.

## Outputs
architecture-report.docx (primary editable Word report), architecture.mmd, optional architecture.svg and embedded Word diagram (require Mermaid CLI), technical-design.md, technical-design.pdf, analysis.json.

## Security and limitations
Repository code is never executed. Static inspection cannot prove all runtime relationships. Only HTTP(S) Git URLs are supported. Add authentication, HTTPS, rate limiting, isolated workers, resource limits, egress controls and secret management before public deployment.
"# TestRepoLense" 
