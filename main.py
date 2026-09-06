"""
ARCHAEO-OSIRIS v2.0 // BAŞLANGIÇ NOKTASI
Kullanım:
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload

Ortam değişkenleri (.env):
    YOUTUBE_API_KEY=...      (isteğe bağlı - video katmanı için)
    ANTHROPIC_API_KEY=...    (AI özet motoru için)
"""
from dotenv import load_dotenv

load_dotenv()

import os
from dotenv import load_dotenv

load_dotenv()

# FastAPI app'i api/server.py'den al
from api.server import app  # noqa: F401

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
