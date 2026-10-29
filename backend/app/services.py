import html, ipaddress, re, socket, textwrap, uuid
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse
import httpx
from .config import settings
STOPWORDS = set("a an the and or but if while of to in on for with by from at as is are was were be been being this that these those it its into about after before over under their his her they them we you your new says said according".split())
POSITIVE = set("success successful growth improve improved breakthrough win wins positive launch launched advances strong benefit benefits".split())
NEGATIVE = set("crisis attack attacks killed death disaster conflict war crash failure failed concern threat risk injured damage".split())
def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(text or "")).strip()
def extract_keywords(text: str, limit: int = 8) -> list[str]:
    words = re.findall(r"\b[A-Za-z][A-Za-z'-]{2,}\b", text.lower())
    return [w for w, _ in Counter(w for w in words if w not in STOPWORDS).most_common(limit)]
def extract_entities(text: str) -> dict:
    candidates = re.findall(r"\b(?:[A-Z][a-z]+|[A-Z]{2,})(?:\s+(?:[A-Z][a-z]+|[A-Z]{2,}))*\b", text)
    ignored = {"The", "A", "An", "In", "On", "At", "After", "Before", "New", "More", "This", "That", "These", "Those", "It", "He", "She", "They", "We", "Scientists", "Heavy", "Damage"}
    entities = list(dict.fromkeys(x.strip() for x in candidates if x not in ignored and len(x) > 1))
    return {"entities": entities[:12], "people": [], "organizations": [], "locations": []}
def analyze_text(headline: str, article_text: str | None = None) -> dict:
    combined = normalize_text(f"{headline} {article_text or ''}")
    words = re.findall(r"\b[a-z]+\b", combined.lower())
    pos, neg = sum(w in POSITIVE for w in words), sum(w in NEGATIVE for w in words)
    sentiment = "positive" if pos > neg else "negative" if neg > pos else "mixed/neutral"
    keywords = extract_keywords(combined)
    return {**extract_entities(combined), "keywords": keywords, "sentiment": sentiment,
            "sentiment_method": "transparent lexicon heuristic", "topic": keywords[0].title() if keywords else "General",
            "main_event": normalize_text(headline),
            "context_note": "Lightweight analysis; verify names and interpretation against the source."}
def make_prompt(headline: str, summary: str | None, analysis: dict, style: str) -> str:
    context = summary or headline
    keywords = ", ".join(analysis.get("keywords", [])[:5])
    return f"Create a clearly illustrative {style} representing: {headline}. Context: {context[:500]}. Relevant concepts: {keywords or 'headline subject'}. Editorial composition, thoughtful lighting, no readable text, no fabricated quotations, and no implication this is documentary evidence."
def summarize_demo(text: str, length: str) -> dict:
    clean = normalize_text(text)
    sentences = re.split(r"(?<=[.!?])\s+", clean)
    selected = " ".join(sentences[:{"short":1,"medium":3,"detailed":5}[length]]).strip() or clean
    return {"summary": selected, "provider": "demo-extractive", "is_demo": True,
            "notice": "Demo summary selected from source sentences; no transformer inference was performed."}
def summarize(text: str, length: str) -> dict:
    if settings.summarization_mode.lower() != "transformers": return summarize_demo(text, length)
    try:
        from transformers import pipeline
        global _summarizer
        if "_summarizer" not in globals(): _summarizer = pipeline("summarization", model=settings.summarization_model)
        maximum = {"short":45,"medium":100,"detailed":160}[length]
        result = _summarizer(text[:settings.max_article_chars], max_length=maximum, min_length=min(20, maximum//3), do_sample=False, truncation=True)
        return {"summary":result[0]["summary_text"],"provider":settings.summarization_model,"is_demo":False,"notice":"Model-generated summary; verify against the original article."}
    except Exception as exc: raise RuntimeError(f"Real summarization provider failed: {type(exc).__name__}; check model installation and resources.") from exc
def _check_public_url(url: str):
    parsed = urlparse(url)
    if parsed.scheme not in {"http","https"} or not parsed.hostname: raise ValueError("Only HTTP(S) URLs are supported.")
    if parsed.hostname.lower() in {"localhost","localhost.localdomain"}: raise ValueError("Localhost URLs are not allowed.")
    try: addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme=="https" else 80))
    except socket.gaierror as exc: raise ValueError("Could not resolve article host.") from exc
    for item in addresses:
        if not ipaddress.ip_address(item[4][0]).is_global: raise ValueError("Private or non-public hosts are not allowed.")
async def fetch_article(url: str) -> str:
    _check_public_url(url)
    async with httpx.AsyncClient(timeout=8, follow_redirects=False, headers={"User-Agent":"NewsCanvasAI/1.0"}) as client:
        response = await client.get(url); response.raise_for_status()
        if 300 <= response.status_code < 400: raise ValueError("Redirects are not followed; paste article text instead.")
        if "text/html" not in response.headers.get("content-type",""): raise ValueError("URL did not return HTML.")
        if len(response.content)>2_000_000: raise ValueError("Page exceeds the 2 MB retrieval limit.")
        from html.parser import HTMLParser
        class Extractor(HTMLParser):
            def __init__(self): super().__init__(); self.parts=[]; self.skip=0
            def handle_starttag(self,tag,attrs):
                if tag in {"script","style","nav","footer","header","noscript"}: self.skip+=1
            def handle_endtag(self,tag):
                if tag in {"script","style","nav","footer","header","noscript"} and self.skip: self.skip-=1
            def handle_data(self,data):
                if not self.skip: self.parts.append(data)
        parser=Extractor(); parser.feed(response.text)
        result=normalize_text(" ".join(parser.parts))
        if len(result)<100: raise ValueError("Not enough readable text found; paste the article manually.")
        return result[:settings.max_article_chars]
ASPECTS = {"1:1": (900, 900), "4:3": (1200, 900), "3:2": (1200, 800), "16:9": (1200, 675)}
def demo_svg(headline: str, style: str, output_dir: Path, aspect_ratio: str = "16:9") -> str:
    w, h = ASPECTS.get(aspect_ratio, ASPECTS["16:9"])
    output_dir.mkdir(parents=True, exist_ok=True); name=f"{uuid.uuid4().hex}.svg"
    safe=html.escape(textwrap.shorten(headline,width=72,placeholder="…"))
    svg='''<svg xmlns="http://www.w3.org/2000/svg" width="W_" height="H_" viewBox="0 0 W_ H_"><defs><linearGradient id="bg"><stop stop-color="#101b35"/><stop offset="1" stop-color="#245c68"/></linearGradient></defs><rect width="W_" height="H_" fill="url(#bg)"/><circle cx="930" cy="190" r="115" fill="#f2b66d"/><path d="M0 520 L260 330 L430 480 L700 250 L1200 560 L1200 675 L0 675Z" fill="#0b1326" opacity=".8" transform="translate(0 HOFF_)"/><text x="65" y="85" font-family="Arial" font-size="20" fill="white">DEMO ARTWORK - NOT AI INFERENCE</text><text x="65" y="YS_" font-family="Arial" font-size="17" fill="#b9d4dc">STYLE_PLACEHOLDER</text><text x="65" y="YH_" font-family="Arial" font-size="28" font-weight="bold" fill="white">HEADLINE_PLACEHOLDER</text></svg>'''
    svg=svg.replace("STYLE_PLACEHOLDER",html.escape(style.upper())).replace("HEADLINE_PLACEHOLDER",safe)
    svg=svg.replace("W_",str(w)).replace("H_",str(h)).replace("HOFF_",str(h-675)).replace("YS_",str(h-125)).replace("YH_",str(h-75))
    (output_dir/name).write_text(svg,encoding="utf-8")
    return name
async def generate_image(prompt: str, headline: str, style: str, output_dir: Path, aspect_ratio: str = "16:9") -> tuple[str,str]:
    if settings.image_provider.lower()=="demo": return demo_svg(headline,style,output_dir,aspect_ratio),"demo-svg"
    if settings.image_provider.lower()!="huggingface": raise RuntimeError("Unsupported IMAGE_PROVIDER; use demo or huggingface.")
    if not settings.hf_inference_url: raise RuntimeError("HF_INFERENCE_URL is required for hosted inference.")
    headers={"Accept":"image/*"}
    if settings.hf_api_token: headers["Authorization"]=f"Bearer {settings.hf_api_token}"
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response=await client.post(settings.hf_inference_url,json={"inputs":prompt},headers=headers); response.raise_for_status()
            ctype=response.headers.get("content-type","")
            if not ctype.startswith("image/") or not response.content: raise RuntimeError("Provider did not return image bytes.")
            ext=".png" if "png" in ctype else ".jpg" if "jpeg" in ctype else ".webp"
            output_dir.mkdir(parents=True,exist_ok=True); name=f"{uuid.uuid4().hex}{ext}"; (output_dir/name).write_bytes(response.content)
            return name,"huggingface-endpoint"
    except httpx.HTTPError as exc: raise RuntimeError(f"Image provider request failed: {type(exc).__name__}; check endpoint, token, quota, and model.") from exc
