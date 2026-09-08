"""
ARCHAEO-OSIRIS // ANA SUNUCU
FastAPI tabanlı, ekosistemi ayağa kaldıran ve tüm endpoint'leri sunan sunucu.
"""
import asyncio
import base64
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

import cv2
import httpx
import numpy as np
from pydantic import BaseModel
from fastapi import FastAPI, File, Form, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from core.ecosystem import ArcheoEcosystem
from core.agent_base import LayerType
from agents.authenticity_engine import OtantisiteMotoru
from scanner.surface_scanner import SurfaceGridScanner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)


def _to_jsonable(obj):
    """NumPy tiplerini (int32, float64, ndarray vb.) düz Python tiplerine çevirir."""
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


# ── Global nesneler ────────────────────────────────────────────────────────
ecosystem: Optional[ArcheoEcosystem] = None
otantisite = OtantisiteMotoru()
scanner = SurfaceGridScanner()

CURRENT_VIDEO_PATH: Optional[str] = None
CURRENT_FILTER = "ORIGINAL"

os.makedirs("temp_uploads", exist_ok=True)
os.makedirs("processed_output", exist_ok=True)


# ── Lifespan: ekosistemi başlat/durdur ─────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global ecosystem
    ecosystem = ArcheoEcosystem(
        youtube_api_key=os.getenv("YOUTUBE_API_KEY")
    )
    await ecosystem.start()
    logger.info("✅ Ekosistem aktif")
    yield
    await ecosystem.stop()
    logger.info("⏹ Ekosistem durduruldu")


app = FastAPI(
    title="Archaeo-Osiris Intelligence Platform",
    description="Arkeoloji odaklı çok katmanlı canlı istihbarat ekosistemi",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY")
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION", "eastus")
AZURE_SPEECH_VOICE = os.getenv("AZURE_SPEECH_VOICE", "tr-TR-AhuNeural")

_azure_token_cache = {"token": None, "expires": 0.0}


async def get_azure_token() -> Optional[str]:
    now = asyncio.get_event_loop().time()
    if _azure_token_cache["token"] and now < _azure_token_cache["expires"]:
        return _azure_token_cache["token"]
    url = f"https://{AZURE_SPEECH_REGION}.api.cognitive.microsoft.com/sts/v1.0/issueToken"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(url, headers={"Ocp-Apim-Subscription-Key": AZURE_SPEECH_KEY})
        if r.status_code != 200:
            logger.error(f"Azure token hatası: {r.status_code} {r.text}")
            return None
        _azure_token_cache["token"] = r.text
        _azure_token_cache["expires"] = now + 540  # ~9 dk geçerli
        return r.text


def _escape_ssml(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace('"', "&quot;").replace("'", "&apos;"))


async def synthesize_speech(text: str) -> Optional[bytes]:
    token = await get_azure_token()
    if not token:
        return None
    url = f"https://{AZURE_SPEECH_REGION}.tts.speech.microsoft.com/cognitiveservices/v1"
    ssml = (
        f"<speak version='1.0' xml:lang='tr-TR'>"
        f"<voice xml:lang='tr-TR' xml:gender='Female' name='{AZURE_SPEECH_VOICE}'>"
        f"{_escape_ssml(text)}</voice></speak>"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": "audio-16khz-128kbitrate-mono-mp3",
        "User-Agent": "ArchaeoOsiris-Kasif",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(url, headers=headers, content=ssml.encode("utf-8"))
        if r.status_code != 200:
            logger.error(f"Azure TTS hatası: {r.status_code} {r.text[:300]}")
            return None
        return r.content


class SpeakRequest(BaseModel):
    text: str


@app.post("/api/kasif/speak")
async def kasif_speak(payload: SpeakRequest):
    if not AZURE_SPEECH_KEY:
        return JSONResponse(status_code=503, content={"error": "AZURE_SPEECH_KEY tanımlı değil"})
    audio = await synthesize_speech(payload.text)
    if audio is None:
        return JSONResponse(status_code=502, content={"error": "Azure Speech sentezi başarısız"})
    from fastapi import Response
    return Response(content=audio, media_type="audio/mpeg")


# ── Video akışı ────────────────────────────────────────────────────────────
def generate_video_frames():
    global CURRENT_VIDEO_PATH, CURRENT_FILTER
    if not CURRENT_VIDEO_PATH or not os.path.exists(CURRENT_VIDEO_PATH):
        return
    cap = cv2.VideoCapture(CURRENT_VIDEO_PATH)
    while True:
        ret, frame = cap.read()
        if not ret:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            continue
        processed, _ = scanner.render_surface_effects(frame, mode=CURRENT_FILTER)
        _, buffer = cv2.imencode('.jpg', processed, [cv2.IMWRITE_JPEG_QUALITY, 80])
        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')


@app.get("/api/video/stream")
def video_stream():
    return StreamingResponse(
        generate_video_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


# ── Medya analiz pipeline ──────────────────────────────────────────────────
@app.post("/api/pipeline/analyze")
async def pipeline_analyze(
    files: list[UploadFile] = File(default=[]),
    links: str = Form(default=""),
    filter_mode: str = Form("ORIGINAL"),
):
    global CURRENT_VIDEO_PATH, CURRENT_FILTER
    CURRENT_FILTER = filter_mode
    results = []

    for uploaded in files:
        contents = await uploaded.read()
        filename = uploaded.filename.lower()
        save_path = os.path.join("temp_uploads", uploaded.filename)
        with open(save_path, "wb") as f:
            f.write(contents)

        if filename.endswith(('.mp4', '.mov', '.avi', '.mkv', '.webm')):
            CURRENT_VIDEO_PATH = save_path
            # Video'dan örnek kare al, otantisite kontrolü yap
            cap = cv2.VideoCapture(save_path)
            ret, sample_frame = cap.read()
            cap.release()
            auth_report = otantisite.analyze_frame(sample_frame) if ret else None

            results.append({
                "type": "video",
                "source": uploaded.filename,
                "stream_url": "/api/video/stream",
                "authenticity": auth_report.to_dict() if auth_report else {},
                "message": "Canlı 3D tarama akışı hazır. Yüzey ızgarası ve neon hedef halkası aktif.",
            })
        else:
            # Görsel analiz
            arr = np.frombuffer(contents, np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)

            if frame is None:
                results.append({"type": "error", "source": uploaded.filename, "message": "Görüntü decode edilemedi"})
                continue

            annotated, detections = scanner.render_surface_effects(frame, mode=filter_mode)
            auth = otantisite.analyze_image_bytes(contents, filename=uploaded.filename)

            _, buf = cv2.imencode('.jpg', annotated)
            img_b64 = base64.b64encode(buf).decode('utf-8')

            results.append({
                "type": "image",
                "source": uploaded.filename,
                "image_b64": img_b64,
                "detections": detections,
                "cavity_count": len(detections),
                "authenticity": auth.to_dict(),
                            callouts = []
            h, w = frame.shape[:2]
            for i, det in enumerate(detections):
                cx, cy = det.get("center", det.get("bbox_center", [w // 2, h // 2]))
                r = det.get("radius", det.get("size", 60))
                x1, y1 = max(0, int(cx - r * 2)), max(0, int(cy - r * 2))
                x2, y2 = min(w, int(cx + r * 2)), min(h, int(cy + r * 2))
                crop = frame[y1:y2, x1:x2]
                if crop.size == 0:
                    continue
                crop_big = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
                _, cbuf = cv2.imencode('.jpg', crop_big, [cv2.IMWRITE_JPEG_QUALITY, 90])
                trust = det.get("trust_score", det.get("confidence", 0.5))
                status = "Doğrulandı" if trust >= 0.8 else ("İncelenmeli" if trust >= 0.5 else "Düşük Güven")
                callouts.append({
                    "id": det.get("id", f"BULGU-{i+1:02d}"),
                    "type": det.get("type", "bilinmiyor"),
                    "trust_score": round(float(trust), 2),
                    "status": status,
                    "crop_b64": base64.b64encode(cbuf).decode('utf-8'),
                })
                "filter_applied": filter_mode,
            })

    # Link OSINT analizi - ekosistem ajanlarından biri tarafından işlenir
    if links.strip() and ecosystem:
        from agents.layer_agents import TreasureForumAgent, safe_get
        from bs4 import BeautifulSoup

        temp_agent = TreasureForumAgent()
        for link in links.split("\n"):
            link = link.strip()
            if not link:
                continue
            result = await temp_agent.analyze_source(link)
            if result:
                results.append({
                    "type": "link",
                    "source": link,
                    "title": result.title,
                    "callouts": callouts,
                    "summary": result.summary,
                    "relevance": result.relevance_score,
                    "fake_probability": result.fake_probability,
                    "keywords": result.keywords,
                    "media": result.media_urls[:3],
                    "coords": result.coordinates,
                })
            else:
                results.append({"type": "link", "source": link, "error": "Bağlantı kurulamadı"})

    return _to_jsonable({"status": "success", "count": len(results), "results": results})


# ── Ekosistem durumu endpoint'leri ────────────────────────────────────────
@app.get("/api/ecosystem/status")
def ecosystem_status():
    if not ecosystem:
        return {"error": "Ekosistem başlatılmadı"}
    return ecosystem.status_report()


@app.get("/api/ecosystem/layer/{layer_name}")
def layer_results(layer_name: str):
    if not ecosystem:
        return {"error": "Ekosistem başlatılmadı"}
    try:
        layer = LayerType(layer_name)
    except ValueError:
        valid = [l.value for l in LayerType]
        return JSONResponse(
            status_code=400,
            content={"error": f"Geçersiz katman. Geçerliler: {valid}"}
        )
    return ecosystem.layer_summary(layer)


@app.get("/api/ecosystem/alerts")
def get_alerts():
    if not ecosystem:
        return {"error": "Ekosistem başlatılmadı"}
    alerts = ecosystem.bus.alerts(threshold=0.75)
    return {
        "count": len(alerts),
        "alerts": [
            {
                "layer": r.layer.value,
                "title": r.title,
                "relevance": round(r.relevance_score, 2),
                "fake_prob": round(r.fake_probability, 2),
                "url": r.source_url,
                "coords": r.coordinates,
                "timestamp": r.timestamp,
            }
            for r in alerts
        ]
    }


@app.get("/api/ecosystem/feed")
def live_feed(limit: int = 30):
    if not ecosystem:
        return {"error": "Ekosistem başlatılmadı"}
    recent = ecosystem.bus.recent(limit)
    return {
        "count": len(recent),
        "feed": [
            {
                "layer": r.layer.value,
                "title": r.title,
                "summary": r.summary[:150],
                "relevance": round(r.relevance_score, 2),
                "fake_prob": round(r.fake_probability, 2),
                "url": r.source_url,
                "keywords": r.keywords[:5],
                "coords": r.coordinates,
                "media": r.media_urls[:1],
                "timestamp": r.timestamp,
            }
            for r in reversed(recent)
        ]
    }


# ── WebSocket - canlı ajan beslemesi ──────────────────────────────────────
@app.websocket("/ws/live-feed")
async def websocket_feed(ws: WebSocket):
    await ws.accept()
    if not ecosystem:
        await ws.send_json({"error": "Ekosistem başlatılmadı"})
        await ws.close()
        return

    # Yeni sonuç gelince WS üzerinden gönder
    import json

    async def send_result(result):
        try:
            await ws.send_json({
                "layer": result.layer.value,
                "title": result.title,
                "summary": result.summary[:150],
                "relevance": round(result.relevance_score, 2),
                "fake_prob": round(result.fake_probability, 2),
                "url": result.source_url,
                "keywords": result.keywords[:5],
                "coords": result.coordinates,
                "timestamp": result.timestamp,
            })
        except:
            pass

    ecosystem.bus.subscribe(send_result)
    try:
        while True:
            await asyncio.sleep(1)
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        pass


@app.get("/api/health")
def health():
    return {
        "status": "aktif",
        "agents": len(ecosystem._agents) if ecosystem else 0,
        "timestamp": __import__("datetime").datetime.now().isoformat(),
    }


# ── Ana arayüz ─────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def index():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()