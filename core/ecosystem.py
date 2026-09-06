"""
ARCHAEO-OSIRIS // EKOSİSTEM ORKESTRATÖRİ
Tüm katman ajanlarını başlatır, izler, koordine eder.
Ajanlar arası bilgi paylaşımı - bir ajan bulduğunu diğerine iletir.
"""
import asyncio
import json
import logging
from collections import deque
from datetime import datetime
from typing import Optional

from core.agent_base import BaseArcheoAgent, LayerType, ScanResult
from agents.layer_agents import (
    AcademicAgent,
    MuseumAgent,
    FieldworkAgent,
    TreasureForumAgent,
    SymbolAnalysisAgent,
    ArtifactVisualAgent,
    AntiqueDealerAgent,
    VideoMediaAgent,
)

logger = logging.getLogger(__name__)


class EcosystemEventBus:
    """Ajanlar arası iletişim veri yolu"""
    def __init__(self, maxlen: int = 1000):
        self._queue: deque[ScanResult] = deque(maxlen=maxlen)
        self._subscribers: list = []

    def publish(self, result: ScanResult):
        self._queue.append(result)
        for sub in self._subscribers:
            try:
                sub(result)
            except Exception as e:
                logger.warning(f"EventBus subscriber hatası: {e}")

    def subscribe(self, fn):
        self._subscribers.append(fn)

    def recent(self, n: int = 50) -> list[ScanResult]:
        items = list(self._queue)
        return items[-n:]

    def by_layer(self, layer: LayerType) -> list[ScanResult]:
        return [r for r in self._queue if r.layer == layer]

    def top_by_relevance(self, n: int = 20) -> list[ScanResult]:
        return sorted(self._queue, key=lambda r: r.relevance_score, reverse=True)[:n]

    def alerts(self, threshold: float = 0.8) -> list[ScanResult]:
        """Yüksek relevans veya düşük güven → alarm"""
        result = []
        for r in self._queue:
            if r.relevance_score >= threshold or r.fake_probability >= 0.5:
                result.append(r)
        return result[-20:]


class ArcheoEcosystem:
    """
    Tüm sistemi ayağa kaldırır ve yönetir.
    Her ajan bağımsız döngüde çalışır, EventBus üzerinden haberleşir.
    """
    def __init__(self, youtube_api_key: Optional[str] = None):
        self.bus = EcosystemEventBus(maxlen=2000)
        self._tasks: list[asyncio.Task] = []
        self._agents: list[BaseArcheoAgent] = []

        # Tüm ajanları oluştur
        self._agents = [
            AcademicAgent(),
            MuseumAgent(),
            FieldworkAgent(),
            TreasureForumAgent(),
            SymbolAnalysisAgent(),
            ArtifactVisualAgent(),
            AntiqueDealerAgent(),
            VideoMediaAgent(youtube_api_key=youtube_api_key),
        ]

        # Her ajanın sonucunu EventBus'a gönder + çapraz öğrenme
        for agent in self._agents:
            agent.register_callback(self._on_result)

        logger.info(f"Ekosistem hazır: {len(self._agents)} ajan yüklendi.")

    async def _on_result(self, result: ScanResult):
        """
        Bir ajan sonuç ürettiğinde:
        1. EventBus'a yayımla
        2. Koordinat varsa diğer ajanları uyar
        3. Yüksek güven → diğer ajanlar da aynı kaynağı analiz etsin
        """
        self.bus.publish(result)

        # Çapraz-ajan güçlendirme: koordinat bulan bulguyu ilgili ajanlara bildir
        if result.coordinates and result.relevance_score > 0.7:
            lat, lon = result.coordinates
            logger.info(
                f"[EKOSİSTEM] Koordinat paylaşımı: {lat:.4f},{lon:.4f} "
                f"← {result.layer.value} → diğer ajanlara iletildi"
            )
            # Diğer ajanların memory'sine bu koordinat bilgisini ekle
            for agent in self._agents:
                if agent.layer_type != result.layer:
                    agent.memory.successful_patterns.append({
                        "coord": result.coordinates,
                        "source": result.source_url,
                        "keywords": result.keywords,
                        "from_layer": result.layer.value,
                    })

    async def start(self):
        """Tüm ajanları başlat"""
        logger.info("Ekosistem başlatılıyor...")
        for agent in self._agents:
            task = asyncio.create_task(agent.run_forever(), name=agent.name)
            self._tasks.append(task)
        logger.info(f"{len(self._tasks)} ajan görevi oluşturuldu.")

    async def stop(self):
        """Tüm ajanları durdur"""
        for agent in self._agents:
            agent.stop()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        logger.info("Ekosistem durduruldu.")

    def status_report(self) -> dict:
        """Tüm sistem durumu"""
        return {
            "timestamp": datetime.now().isoformat(),
            "total_results": len(list(self.bus._queue)),
            "agents": [a.get_status_dict() for a in self._agents],
            "top_findings": [
                {
                    "layer": r.layer.value,
                    "title": r.title,
                    "relevance": round(r.relevance_score, 2),
                    "fake_prob": round(r.fake_probability, 2),
                    "url": r.source_url,
                    "coords": r.coordinates,
                }
                for r in self.bus.top_by_relevance(10)
            ],
            "alerts": [
                {
                    "layer": r.layer.value,
                    "title": r.title,
                    "relevance": round(r.relevance_score, 2),
                    "fake_prob": round(r.fake_probability, 2),
                    "flags": getattr(r, 'flags', []),
                    "url": r.source_url,
                }
                for r in self.bus.alerts()
            ],
        }

    def layer_summary(self, layer: LayerType) -> dict:
        results = self.bus.by_layer(layer)
        if not results:
            return {"layer": layer.value, "count": 0, "results": []}
        return {
            "layer": layer.value,
            "count": len(results),
            "avg_relevance": round(sum(r.relevance_score for r in results) / len(results), 2),
            "avg_trust": round(
                sum(1.0 - r.fake_probability for r in results) / len(results) * 100, 1
            ),
            "results": [
                {
                    "title": r.title,
                    "url": r.source_url,
                    "relevance": round(r.relevance_score, 2),
                    "fake_probability": round(r.fake_probability, 2),
                    "keywords": r.keywords,
                    "coords": r.coordinates,
                    "media": r.media_urls[:2],
                    "timestamp": r.timestamp,
                }
                for r in results[-20:]
            ],
        }
