from pydantic import BaseModel, Field, HttpUrl
class AnalyzeRequest(BaseModel):
    repo_url: HttpUrl
    branch: str | None = Field(default=None, max_length=200)
    access_token: str | None = Field(default=None, max_length=500)
    include_tests: bool = False
class AnalyzeResponse(BaseModel):
    analysis_id: str
    repository: str
    summary: str
    architecture_mermaid: str
    technical_design_markdown: str
    analysis: dict
    downloads: dict[str, str]
    llm_used: bool
