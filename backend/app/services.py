import html, ipaddress, random, re, socket, textwrap, uuid
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urlparse
import httpx
from .config import settings

STOPWORDS = set("a an the and or but if while of to in on for with by from at as is are was were be been being this that these those it its into about after before over under their his her they them we you your new says said according".split())
POSITIVE = set("success successful growth improve improved breakthrough win wins positive launch launched advances strong benefit benefits".split())
NEGATIVE = set("crisis attack attacks killed death disaster conflict war crash failure failed concern threat risk injured damage".split())

# name -> (trigger words, (bg top, bg bottom, accent)). Used for topic detection AND demo artwork colours.
THEMES = {
    "Weather": ({"flood", "floods", "flooding", "rain", "storm", "cyclone", "tsunami", "water", "river", "monsoon", "drought", "heatwave"}, ("#08203f", "#1d6f8b", "#9be7ff")),
    "Fire": ({"fire", "wildfire", "blaze", "explosion", "burning"}, ("#2b0f0f", "#b0412a", "#ffb347")),
    "Technology": ({"ai", "technology", "tech", "software", "chip", "robot", "internet", "cyber", "data", "app"}, ("#0d1030", "#4a3aa7", "#6ee7ff")),
    "Politics": ({"election", "government", "minister", "parliament", "vote", "policy", "court", "law", "president"}, ("#1a1f2e", "#35507a", "#f2c14e")),
    "Sports": ({"match", "cup", "league", "cricket", "football", "tournament", "champion", "olympic", "olympics", "wins"}, ("#0b2a1a", "#1f7a4d", "#ffe066")),
    "Economy": ({"market", "markets", "economy", "inflation", "stocks", "trade", "bank", "price", "prices", "budget"}, ("#10231f", "#2f7d6d", "#f2b66d")),
    "Science": ({"science", "scientists", "research", "space", "discovery", "climate", "energy", "study", "nasa", "isro"}, ("#101b35", "#245c68", "#f2b66d")),
}
DEFAULT_PALETTE = ("#101b35", "#245c68", "#f2b66d")
IGNORED_ENTITIES = {"The", "A", "An", "In", "On", "At", "After", "Before", "New", "More", "This", "That", "These", "Those", "It", "He", "She", "They", "We",
                    "Scientists", "Heavy", "Damage", "Thousands", "Officials", "Relief", "Residents", "Police", "Reports", "According",
                    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
                    "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"}


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(text or "")).strip()


def extract_keywords(text: str, limit: int = 8) -> list[str]:
    words = re.findall(r"\b[A-Za-z][A-Za-z'-]{2,}\b", text.lower())
    return [w for w, _ in Counter(w for w in words if w not in STOPWORDS).most_common(limit)]


def extract_entities(text: str) -> dict:
    candidates = re.findall(r"\b(?:[A-Z][a-z]+|[A-Z]{2,})(?:\s+(?:[A-Z][a-z]+|[A-Z]{2,}))*\b", text)
    entities = list(dict.fromkeys(x.strip() for x in candidates if x not in IGNORED_ENTITIES and len(x) > 1))
    return {"entities": entities[:12], "people": [], "organizations": [], "locations": []}


def detect_theme(text: str) -> str | None:
    words = set(re.findall(r"[a-z]+", text.lower()))
    best, best_hits = None, 0
    for name, (triggers, _) in THEMES.items():
        hits = len(words & triggers)
        if hits > best_hits:
            best, best_hits = name, hits
    return best


def analyze_text(headline: str, article_text: str | None = None) -> dict:
    combined = normalize_text(f"{headline} {article_text or ''}")
    words = re.findall(r"\b[a-z]+\b", combined.lower())
    pos, neg = sum(w in POSITIVE for w in words), sum(w in NEGATIVE for w in words)
    sentiment = "positive" if pos > neg else "negative" if neg > pos else "mixed/neutral"
    keywords = extract_keywords(combined)
    theme = detect_theme(combined)
    return {**extract_entities(combined), "keywords": keywords, "sentiment": sentiment,
            "sentiment_method": "transparent lexicon heuristic", "topic": theme or (keywords[0].title() if keywords else "General"),
            "main_event": normalize_text(headline),
            "context_note": "Lightweight analysis; verify names and interpretation against the source."}


def make_prompt(headline: str, summary: str | None, analysis: dict, style: str) -> str:
    context = (summary or headline).strip().rstrip(".!?")[:500]
    keywords = ", ".join(analysis.get("keywords", [])[:5])
    return (f"Create a clearly illustrative {style} representing: {headline.rstrip('.!?')}. Context: {context}. "
            f"Relevant concepts: {keywords or 'headline subject'}. Editorial composition, thoughtful lighting, "
            "no readable text, no fabricated quotations, and no implication this is documentary evidence.")


def summarize_demo(text: str, length: str) -> dict:
    clean = normalize_text(text)
    sentences = re.split(r"(?<=[.!?])\s+", clean)
    selected = " ".join(sentences[:{"short": 1, "medium": 3, "detailed": 5}[length]]).strip() or clean
    return {"summary": selected, "provider": "demo-extractive", "is_demo": True,
            "notice": "Demo summary selected from source sentences; no transformer inference was performed."}


def summarize(text: str, length: str) -> dict:
    if settings.summarization_mode.lower() != "transformers":
        return summarize_demo(text, length)
    try:
        from transformers import pipeline
        global _summarizer
        if "_summarizer" not in globals():
            _summarizer = pipeline("summarization", model=settings.summarization_model)
        maximum = {"short": 45, "medium": 100, "detailed": 160}[length]
        result = _summarizer(text[:settings.max_article_chars], max_length=maximum, min_length=min(20, maximum // 3), do_sample=False, truncation=True)
        return {"summary": result[0]["summary_text"], "provider": settings.summarization_model, "is_demo": False,
                "notice": "Model-generated summary; verify against the original article."}
    except Exception as exc:
        raise RuntimeError(f"Real summarization provider failed: {type(exc).__name__}; check model installation and resources.") from exc


# ---------------------------------------------------------------- article fetching
def _check_public_url(url: str):
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only HTTP(S) URLs are supported.")
    if parsed.hostname.lower() in {"localhost", "localhost.localdomain"}:
        raise ValueError("Localhost URLs are not allowed.")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise ValueError("Could not resolve article host.") from exc
    for item in addresses:
        if not ipaddress.ip_address(item[4][0]).is_global:
            raise ValueError("Private or non-public hosts are not allowed.")


class _Extractor(HTMLParser):
    """Collects <p>/<h1> text (article body) and, as a fallback, all visible text."""
    SKIP = {"script", "style", "nav", "footer", "header", "noscript", "aside", "form"}
    def __init__(self):
        super().__init__(); self.body, self.all, self.skip, self.in_body = [], [], 0, 0
    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP: self.skip += 1
        if tag in {"p", "h1"} and not self.skip: self.in_body += 1
    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip: self.skip -= 1
        if tag in {"p", "h1"} and self.in_body: self.in_body -= 1
    def handle_data(self, data):
        if self.skip: return
        self.all.append(data)
        if self.in_body: self.body.append(data)


async def fetch_article(url: str) -> str:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; NewsCanvasAI/1.0)"}
    async with httpx.AsyncClient(timeout=8, follow_redirects=False, headers=headers) as client:
        current = url
        for _ in range(4):  # follow at most 3 redirects, re-validating every hop against the public-host check
            _check_public_url(current)
            response = await client.get(current)
            if response.is_redirect:
                location = response.headers.get("location")
                if not location: raise ValueError("Redirect without a target; paste article text instead.")
                current = str(httpx.URL(current).join(location))
                continue
            break
        else:
            raise ValueError("Too many redirects; paste article text instead.")
        response.raise_for_status()
        if "text/html" not in response.headers.get("content-type", ""): raise ValueError("URL did not return HTML.")
        if len(response.content) > 2_000_000: raise ValueError("Page exceeds the 2 MB retrieval limit.")
        parser = _Extractor(); parser.feed(response.text)
        body = normalize_text(" ".join(parser.body))
        result = body if len(body) >= 200 else normalize_text(" ".join(parser.all))
        if len(result) < 100: raise ValueError("Not enough readable text found; paste the article manually.")
        return result[:settings.max_article_chars]


# ---------------------------------------------------------------- image generation
ASPECTS = {"1:1": (900, 900), "4:3": (1200, 900), "3:2": (1200, 800), "16:9": (1200, 675)}


def demo_svg(headline: str, style: str, output_dir: Path, aspect_ratio: str = "16:9", theme: str | None = None) -> str:
    """Headline-themed placeholder artwork. Every coordinate is relative to the chosen canvas size."""
    w, h = ASPECTS.get(aspect_ratio, ASPECTS["16:9"])
    top, bottom, accent = THEMES[theme][1] if theme in THEMES else DEFAULT_PALETTE
    output_dir.mkdir(parents=True, exist_ok=True); name = f"{uuid.uuid4().hex}.svg"
    fs = 28 if w >= 1200 else 26
    wrapped = textwrap.wrap(normalize_text(headline), width=max(14, int((w - 130) / (fs * 0.56))))
    lines = wrapped[:3]
    if len(wrapped) > 3: lines[-1] = lines[-1].rstrip(".,;: ") + "…"
    text_top = h - 60 - (len(lines) - 1) * (fs + 8)
    p = lambda fx, fy: f"{fx * w:.0f} {fy * h:.0f}"
    if theme == "Weather":
        y = int(h * 0.74)
        land = f'<path d="M0 {y} Q {w*.125:.0f} {y-34} {w*.25:.0f} {y} T {w*.5:.0f} {y} T {w*.75:.0f} {y} T {w} {y} V {h} H 0 Z" fill="#06142b" opacity=".85"/>'
    else:
        land = f'<path d="M{p(0,.77)} L{p(.22,.49)} L{p(.36,.71)} L{p(.58,.37)} L{p(1,.83)} L{p(1,1)} L{p(0,1)}Z" fill="#0b1326" opacity=".8"/>'
    head = "".join(f'<tspan x="65" y="{text_top + i * (fs + 8)}">{html.escape(l)}</tspan>' for i, l in enumerate(lines))
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
           f'<defs><linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop stop-color="{top}"/><stop offset="1" stop-color="{bottom}"/></linearGradient></defs>'
           f'<rect width="{w}" height="{h}" fill="url(#bg)"/><circle cx="{w*.78:.0f}" cy="{h*.28:.0f}" r="{min(w,h)*.1:.0f}" fill="{accent}"/>{land}'
           f'<text x="65" y="70" font-family="Arial" font-size="20" fill="white">DEMO ARTWORK - NOT AI INFERENCE</text>'
           f'<text x="65" y="{text_top - fs - 10}" font-family="Arial" font-size="17" fill="#b9d4dc">{html.escape((theme or "General").upper())} · {html.escape(style.upper())}</text>'
           f'<text font-family="Arial" font-size="{fs}" font-weight="bold" fill="white">{head}</text></svg>')
    (output_dir / name).write_text(svg, encoding="utf-8")
    return name


def _save_image(response: httpx.Response, output_dir: Path) -> str:
    ctype = response.headers.get("content-type", "")
    if not ctype.startswith("image/") or not response.content:
        raise RuntimeError("Provider did not return image bytes.")
    ext = ".png" if "png" in ctype else ".jpg" if "jpeg" in ctype or "jpg" in ctype else ".webp"
    output_dir.mkdir(parents=True, exist_ok=True); name = f"{uuid.uuid4().hex}{ext}"
    (output_dir / name).write_bytes(response.content)
    return name


async def _real_image(provider: str, prompt: str, aspect_ratio: str, output_dir: Path) -> tuple[str, str]:
    w, h = ASPECTS.get(aspect_ratio, ASPECTS["16:9"])
    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            if provider == "pollinations":
                url = settings.pollinations_url.rstrip("/") + "/" + quote(prompt[:800], safe="")
                headers = {"Accept": "image/*"}
                if settings.pollinations_token: headers["Authorization"] = f"Bearer {settings.pollinations_token}"
                response = await client.get(url, params={"width": w, "height": h, "nologo": "true", "model": settings.pollinations_model, "seed": random.randint(1, 10**6)}, headers=headers)
                label = "pollinations"
            else:
                if not settings.hf_inference_url: raise RuntimeError("HF_INFERENCE_URL is required for hosted inference.")
                headers = {"Accept": "image/*"}
                if settings.hf_api_token: headers["Authorization"] = f"Bearer {settings.hf_api_token}"
                response = await client.post(settings.hf_inference_url, json={"inputs": prompt}, headers=headers)
                label = "huggingface-endpoint"
            response.raise_for_status()
            return _save_image(response, output_dir), label
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Image provider request failed: {type(exc).__name__}; check endpoint, token, quota, and network.") from exc


async def generate_image(prompt: str, headline: str, style: str, output_dir: Path, aspect_ratio: str = "16:9", theme: str | None = None) -> tuple[str, str, str | None]:
    """Returns (filename, provider label, optional notice). Falls back to demo SVG when a real provider fails (IMAGE_FALLBACK_TO_DEMO)."""
    provider = settings.image_provider.lower()
    if provider == "demo":
        return demo_svg(headline, style, output_dir, aspect_ratio, theme), "demo-svg", None
    if provider not in {"huggingface", "pollinations"}:
        raise RuntimeError("Unsupported IMAGE_PROVIDER; use demo, pollinations or huggingface.")
    try:
        name, label = await _real_image(provider, prompt, aspect_ratio, output_dir)
        return name, label, None
    except RuntimeError as exc:
        if not settings.image_fallback_to_demo: raise
        return demo_svg(headline, style, output_dir, aspect_ratio, theme), "demo-svg", f"{exc} Showing demo artwork instead."