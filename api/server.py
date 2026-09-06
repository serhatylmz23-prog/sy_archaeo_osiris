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
import numpy as np
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
                    "summary": result.summary,
                    "relevance": result.relevance_score,
                    "fake_probability": result.fake_probability,
                    "keywords": result.keywords,
                    "media": result.media_urls[:3],
                    "coords": result.coordinates,
                })
            else:
                results.append({"type": "link", "source": link, "error": "Bağlantı kurulamadı"})

    return {"status": "success", "count": len(results), "results": results}


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
