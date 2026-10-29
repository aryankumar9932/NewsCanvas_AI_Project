import json, uuid
from datetime import datetime, timezone
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy import text
from sqlalchemy.orm import Session
from .config import settings
from .database import Base, engine, get_db
from .models import Generation
from .schemas import AnalyzeRequest, GenerateRequest, SummaryRequest, UrlRequest
from .services import analyze_text, fetch_article, make_prompt, summarize, normalize_text, generate_image
BASE_DIR=Path(__file__).resolve().parent.parent
GENERATED_DIR=BASE_DIR/"generated"
Base.metadata.create_all(bind=engine)
app=FastAPI(title="NewsCanvas AI API",version="1.0.0",description="News summarization and illustrative artwork API")
app.add_middleware(CORSMiddleware,allow_origins=[x.strip() for x in settings.cors_origins.split(",") if x.strip()],allow_credentials=False,allow_methods=["GET","POST","DELETE","PUT"],allow_headers=["*"])
def serialize(r):
    return {"id":r.id,"headline":r.headline,"article_text":r.article_text,"summary":r.summary,"analysis":json.loads(r.analysis_json),"image_prompt":r.image_prompt,"provider":r.provider,"status":r.status,"image_url":f"/api/v1/images/{r.image_path}" if r.image_path else None,"created_at":r.created_at.isoformat() if r.created_at else None}
@app.get("/health")
def health(): return {"status":"ok","service":"newscanvas-api"}
@app.get("/api/v1/health/ready")
def ready(db:Session=Depends(get_db)):
    try: db.execute(text("SELECT 1")); return {"status":"ready","database":"ok","image_provider":settings.image_provider,"summarization_mode":settings.summarization_mode}
    except Exception as exc: raise HTTPException(503,"Database readiness check failed.") from exc
@app.post("/api/v1/analyze")
def analyze(p:AnalyzeRequest):
    headline=normalize_text(p.headline); analysis=analyze_text(headline,p.article_text)
    try: sm=summarize(p.article_text,p.summary_length) if p.article_text else None
    except RuntimeError as exc: raise HTTPException(502,str(exc)) from exc
    summary=sm["summary"] if sm else None
    return {"headline":headline,"summary":summary,"summary_meta":sm,"analysis":analysis,"image_prompt":make_prompt(headline,summary,analysis,p.style)}
@app.post("/api/v1/summaries")
def summary(p:SummaryRequest):
    try: return summarize(normalize_text(p.text),p.length)
    except RuntimeError as exc: raise HTTPException(502,str(exc)) from exc
@app.post("/api/v1/articles/fetch")
async def article_fetch(p:UrlRequest):
    try: t=await fetch_article(str(p.url)); return {"article_text":t,"characters":len(t)}
    except ValueError as exc: raise HTTPException(400,str(exc)) from exc
    except Exception as exc: raise HTTPException(400,"Could not safely retrieve article; paste text manually.") from exc
@app.post("/api/v1/generations")
async def create(p:GenerateRequest,db:Session=Depends(get_db)):
    headline=normalize_text(p.headline); article=normalize_text(p.article_text or ""); analysis=analyze_text(headline,article)
    try: sm=summarize(article,p.summary_length) if article else None
    except RuntimeError as exc: raise HTTPException(502,str(exc)) from exc
    prompt=normalize_text(p.image_prompt or make_prompt(headline,sm["summary"] if sm else None,analysis,p.style))
    theme = analysis.get("topic")
    try: image_name,provider,image_notice=await generate_image(prompt,headline,p.style,GENERATED_DIR,p.aspect_ratio,theme)
    except RuntimeError as exc: raise HTTPException(502,str(exc)) from exc
    r=Generation(id=str(uuid.uuid4()),headline=headline,article_text=article or None,summary=sm["summary"] if sm else None,analysis_json=json.dumps(analysis),image_prompt=prompt,provider=provider,status="completed",image_path=image_name,created_at=datetime.now(timezone.utc))
    db.add(r); db.commit(); db.refresh(r); out=serialize(r); out["summary_meta"]=sm; out["image_notice"]=image_notice or ("Demo artwork - not real model inference." if provider=="demo-svg" else "AI-generated illustration; verify against source."); return out
@app.get("/api/v1/generations")
def listing(q:str=Query(default="",max_length=200),limit:int=Query(default=50,ge=1,le=100),db:Session=Depends(get_db)):
    query=db.query(Generation)
    if q.strip(): query=query.filter(Generation.headline.ilike(f"%{q.strip()}%"))
    return [serialize(r) for r in query.order_by(Generation.created_at.desc()).limit(limit).all()]
@app.get("/api/v1/generations/{rid}")
def detail(rid:str,db:Session=Depends(get_db)):
    r=db.get(Generation,rid)
    if not r: raise HTTPException(404,"Generation not found.")
    return serialize(r)
@app.delete("/api/v1/generations/{rid}")
def delete(rid:str,db:Session=Depends(get_db)):
    r=db.get(Generation,rid)
    if not r: raise HTTPException(404,"Generation not found.")
    if r.image_path:
        try: (GENERATED_DIR/r.image_path).unlink(missing_ok=True)
        except OSError: pass
    db.delete(r); db.commit(); return {"deleted":True,"id":rid}
@app.get("/api/v1/images/{filename}")
def image_file(filename:str):
    if Path(filename).name!=filename: raise HTTPException(400,"Invalid filename.")
    path=GENERATED_DIR/filename
    if not path.is_file(): raise HTTPException(404,"Image not found.")
    media="image/svg+xml" if path.suffix==".svg" else "image/png" if path.suffix==".png" else "image/jpeg" if path.suffix==".jpg" else "image/webp"
    return FileResponse(path,media_type=media,filename=filename)
@app.get("/api/v1/exports/{rid}")
def export(rid:str,format:str=Query(default="markdown",pattern="^(markdown|json)$"),db:Session=Depends(get_db)):
    r=db.get(Generation,rid)
    if not r: raise HTTPException(404,"Generation not found.")
    data=serialize(r)
    if format=="json": return JSONResponse(data,headers={"Content-Disposition":f'attachment; filename="newscanvas-{rid}.json"'})
    md=f"# {r.headline}\n\n## Summary\n{r.summary or 'No article summary.'}\n\n## Image prompt\n{r.image_prompt}\n\n## Analysis\n```json\n{json.dumps(data['analysis'],indent=2)}\n```\n\nProvider: {r.provider}\n\nAI-generated or demo artwork may be inaccurate; it is not documentary evidence.\n"
    return Response(md,media_type="text/markdown",headers={"Content-Disposition":f'attachment; filename="newscanvas-{rid}.md"'})
