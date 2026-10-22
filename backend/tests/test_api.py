import os
os.environ["DATABASE_URL"]="sqlite:///./test_newscanvas.db"
os.environ["IMAGE_PROVIDER"]="demo"
os.environ["SUMMARIZATION_MODE"]="demo"
from fastapi.testclient import TestClient
from app.main import app
from app.services import normalize_text, extract_keywords
client=TestClient(app)
def test_health(): assert client.get("/health").status_code==200
def test_text_helpers():
    assert normalize_text(" Hello\n world ")=="Hello world"
    assert "technology" in extract_keywords("Technology technology news today")
def test_analyze():
    r=client.post("/api/v1/analyze",json={"headline":"Technology launch brings strong growth"})
    assert r.status_code==200 and "image_prompt" in r.json()
def test_summary_demo():
    r=client.post("/api/v1/summaries",json={"text":"This is a sufficiently long article sentence. Another sentence provides context.","length":"short"})
    assert r.status_code==200 and r.json()["is_demo"] is True
def test_generation_crud():
    r=client.post("/api/v1/generations",json={"headline":"Science team announces a new discovery","article_text":"A science team announced a new discovery. The work may help researchers understand the topic.","summary_length":"short","style":"editorial illustration","aspect_ratio":"16:9"})
    assert r.status_code==200, r.text
    item=r.json()
    assert item["provider"]=="demo-svg"
    assert client.get("/api/v1/generations/"+item["id"]).status_code==200
    assert client.get("/api/v1/exports/"+item["id"]+"?format=json").status_code==200
    assert client.delete("/api/v1/generations/"+item["id"]).status_code==200
