from app.services.scanner import scan_repository
def test_scanner(tmp_path):
    (tmp_path/"main.py").write_text("from fastapi import FastAPI\\n@app.get('/health')\\ndef health(): return {}")
    result=scan_repository(tmp_path,100,10000,100000,True)
    assert result["file_count"]==1
    assert "health" in result["functions"]
