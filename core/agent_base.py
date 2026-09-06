"""
ARCHAEO-OSIRIS // AJAN EKOSİSTEMİ - TEMEL SINIF
Her katman için bağımsız, kendini geliştiren ajan mimarisi
"""
import asyncio
import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class AgentStatus(Enum):
    IDLE = "BEKLEMEDE"
    SCANNING = "TARAMA_YAPILIYOR"
    LEARNING = "ÖĞRENIYOR"
    REPORTING = "RAPORLUYOR"
    ERROR = "HATA"


class LayerType(Enum):
    ACADEMIC = "akademik"          # Üniversiteler, makaleler, tezler
    MUSEUM = "müze"                # Müzeler, koleksiyonlar, kataloglar
    FIELDWORK = "saha"             # Aktif kazılar, projeler, yarım kalanlar
    TREASURE_FORUM = "forum"       # Define avcısı forumları, işaret analizleri
    SYMBOL_ANALYSIS = "sembol"     # Define işaretleri, simgeler, yorumlar
    ARTIFACT_VISUAL = "görsel"     # Heykeller, lahitler, yüz tanıma (eserlerde)
    ANTIQUE_DEALER = "antikacı"    # Antikacılar, müzayedeler, pazar
    VIDEO_MEDIA = "medya"          # Video kayıtları, belgeseller, YouTube
    SURFACE_SCAN = "yüzey"         # Arazi taraması, DStretch, termal
    FAKE_DETECTOR = "doğrulama"    # Sahte içerik tespiti, gerçeklik skoru


@dataclass
class AgentMemory:
    """Her ajanın kendi öğrenme hafızası"""
    discovered_sources: list[str] = field(default_factory=list)
    keyword_weights: dict[str, float] = field(default_factory=dict)
    successful_patterns: list[dict] = field(default_factory=list)
    failed_attempts: list[str] = field(default_factory=list)
    session_count: int = 0
    last_discovery: Optional[str] = None
    confidence_scores: dict[str, float] = field(default_factory=dict)

    def learn_from_result(self, url: str, keywords_found: list[str], relevance: float):
        """Bulgudan öğren - keyword ağırlıklarını güncelle"""
        if relevance > 0.6:
            self.discovered_sources.append(url)
            self.last_discovery = url
            for kw in keywords_found:
                self.keyword_weights[kw] = self.keyword_weights.get(kw, 1.0) + 0.2
        else:
            self.failed_attempts.append(url)
            for kw in keywords_found:
                self.keyword_weights[kw] = max(0.1, self.keyword_weights.get(kw, 1.0) - 0.05)

        self.session_count += 1

    def top_keywords(self, n=10) -> list[str]:
        return sorted(self.keyword_weights, key=self.keyword_weights.get, reverse=True)[:n]


@dataclass
class ScanResult:
    """Bir tarama sonucu"""
    layer: LayerType
    source_url: str
    title: str
    summary: str
    relevance_score: float       # 0.0 - 1.0
    fake_probability: float      # 0.0 = kesinlikle gerçek, 1.0 = kesinlikle sahte
    keywords: list[str]
    media_urls: list[str]
    coordinates: Optional[tuple] = None   # (lat, lon) eğer varsa
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    raw_data: dict = field(default_factory=dict)


class BaseArcheoAgent(ABC):
    """
    Tüm harita katmanı ajanlarının temel sınıfı.
    Her ajan kendi kaynağını tarar, öğrenir ve diğer ajanlarla paylaşır.
    """
    def __init__(self, layer_type: LayerType, name: str):
        self.layer_type = layer_type
        self.name = name
        self.status = AgentStatus.IDLE
        self.memory = AgentMemory()
        self.results: list[ScanResult] = []
        self._callbacks: list[Callable] = []
        self._running = False
        self.scan_interval = 300  # saniye, öğrendikçe değişir
        logger.info(f"[{self.name}] Ajan başlatıldı → Katman: {self.layer_type.value}")

    def register_callback(self, fn: Callable):
        """Sonuç gelince çağrılacak fonksiyon ekle (diğer ajanlar veya UI)"""
        self._callbacks.append(fn)

    async def _emit(self, result: ScanResult):
        """Tüm callback'leri tetikle"""
        self.results.append(result)
        for cb in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(result)
                else:
                    cb(result)
            except Exception as e:
                logger.warning(f"[{self.name}] Callback hatası: {e}")

    @abstractmethod
    async def discover_sources(self) -> list[str]:
        """Yeni kaynak URL'leri bul - her ajan kendi metodolojisini uygular"""
        ...

    @abstractmethod
    async def analyze_source(self, url: str) -> Optional[ScanResult]:
        """Bir kaynağı analiz et ve ScanResult döndür"""
        ...

    async def self_improve(self):
        """
        Öğrenme döngüsü:
        - Başarılı sonuçlardan yeni arama stratejileri türet
        - Tarama sıklığını ayarla
        - Keyword ağırlıklarını güncelle
        """
        good_results = [r for r in self.results if r.relevance_score > 0.7]
        if good_results:
            # İyi sonuçlardan yeni kaynak kalıpları çıkar
            domains = set()
            for r in good_results[-10:]:
                try:
                    from urllib.parse import urlparse
                    domain = urlparse(r.source_url).netloc
                    domains.add(domain)
                except:
                    pass
            logger.info(f"[{self.name}] Öğrenildi: {len(domains)} yeni güvenilir domain")

        # Tarama aralığını ayarla: çok bulgu → daha sık, az bulgu → yavaşla
        if len(good_results) > 5:
            self.scan_interval = max(60, self.scan_interval - 30)
        elif len(good_results) == 0:
            self.scan_interval = min(600, self.scan_interval + 60)

    async def run_forever(self):
        """Sürekli çalışan ajan döngüsü"""
        self._running = True
        logger.info(f"[{self.name}] Sonsuz döngü başladı.")
        while self._running:
            try:
                self.status = AgentStatus.SCANNING
                urls = await self.discover_sources()
                logger.info(f"[{self.name}] {len(urls)} kaynak bulundu.")

                for url in urls:
                    if not self._running:
                        break
                    result = await self.analyze_source(url)
                    if result:
                        self.memory.learn_from_result(
                            url, result.keywords, result.relevance_score
                        )
                        await self._emit(result)

                self.status = AgentStatus.LEARNING
                await self.self_improve()

                self.status = AgentStatus.IDLE
                await asyncio.sleep(self.scan_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.status = AgentStatus.ERROR
                logger.error(f"[{self.name}] Döngü hatası: {e}")
                await asyncio.sleep(30)

        logger.info(f"[{self.name}] Durduruldu.")

    def stop(self):
        self._running = False

    def get_status_dict(self) -> dict:
        return {
            "name": self.name,
            "layer": self.layer_type.value,
            "status": self.status.value,
            "results_count": len(self.results),
            "sources_discovered": len(self.memory.discovered_sources),
            "top_keywords": self.memory.top_keywords(5),
            "scan_interval_sec": self.scan_interval,
            "last_discovery": self.memory.last_discovery,
        }
