"""
ARCHAEO-OSIRIS // HARİTA KATMANLARI YAPILANDIRMASI
Osiris'in LayerPanel mantığında, arkeoloji odaklı özel katmanlar.
Her katmanın ajan bağlantısı, rengi, ikonu ve veri kaynağı tanımlı.
"""
from dataclasses import dataclass, field
from core.agent_base import LayerType


@dataclass
class MapLayer:
    id: str
    name: str
    name_tr: str
    layer_type: LayerType
    color: str              # Hex renk
    icon: str               # Lucide icon adı
    z_index: int
    enabled: bool = True
    opacity: float = 0.85
    min_zoom: int = 5
    max_zoom: int = 22
    cluster_radius: int = 50
    description: str = ""
    data_sources: list[str] = field(default_factory=list)
    refresh_interval_sec: int = 300


# ── Tüm harita katmanları tanımı ──────────────────────────────────────────
ARCHAEO_LAYERS: list[MapLayer] = [
    MapLayer(
        id="academic",
        name="Academic Sources",
        name_tr="Akademik Kaynaklar",
        layer_type=LayerType.ACADEMIC,
        color="#4fc3f7",
        icon="BookOpen",
        z_index=10,
        description="Üniversite makaleleri, tezler, akademik yayınlar. OpenAlex + Semantic Scholar",
        data_sources=[
            "https://api.openalex.org/works",
            "https://api.semanticscholar.org/graph/v1/paper/search",
            "https://tez.yok.gov.tr",
        ],
        refresh_interval_sec=600,
    ),
    MapLayer(
        id="museum",
        name="Museums & Collections",
        name_tr="Müzeler & Koleksiyonlar",
        layer_type=LayerType.MUSEUM,
        color="#f06292",
        icon="Landmark",
        z_index=20,
        description="Dünya müzeleri, dijital koleksiyonlar. Met Museum, Europeana, British Museum",
        data_sources=[
            "https://collectionapi.metmuseum.org/public/collection/v1",
            "https://api.europeana.eu/record/v2",
        ],
        refresh_interval_sec=900,
    ),
    MapLayer(
        id="fieldwork",
        name="Active Excavations",
        name_tr="Aktif Kazılar & Projeler",
        layer_type=LayerType.FIELDWORK,
        color="#81c784",
        icon="Shovel",
        z_index=30,
        description="Devam eden ve yarım kalan arkeoloji kazıları. Open Context, ADS",
        data_sources=[
            "https://opencontext.org/search/",
            "https://archaeologydataservice.ac.uk",
        ],
        refresh_interval_sec=1800,
    ),
    MapLayer(
        id="treasure_forum",
        name="Treasure Hunter Forums",
        name_tr="Define Avcısı Forumları",
        layer_type=LayerType.TREASURE_FORUM,
        color="#ffb74d",
        icon="MessageSquare",
        z_index=40,
        description="Define forumları, Reddit, arkeoloji toplulukları. Gerçek forum verileri.",
        data_sources=[
            "https://www.arkeofili.com",
            "https://reddit.com/r/metaldetecting",
            "https://reddit.com/r/archaeology",
        ],
        refresh_interval_sec=300,
        opacity=0.7,
    ),
    MapLayer(
        id="symbol_analysis",
        name="Symbol & Mark Analysis",
        name_tr="Sembol & İşaret Analizi",
        layer_type=LayerType.SYMBOL_ANALYSIS,
        color="#ce93d8",
        icon="Pentagon",
        z_index=50,
        description="Kaya resimleri, define işaretleri, oyuk sembolleri. Wikipedia + Bradshaw Foundation",
        data_sources=[
            "https://en.wikipedia.org/wiki/Rock_art_in_Turkey",
            "https://www.bradshawfoundation.com",
        ],
        refresh_interval_sec=1200,
    ),
    MapLayer(
        id="artifact_visual",
        name="Artifact Face Recognition",
        name_tr="Eser Görsel Tanıma (Heykel/Lahit)",
        layer_type=LayerType.ARTIFACT_VISUAL,
        color="#ffe082",
        icon="Scan",
        z_index=60,
        description="Heykeller, lahitler, kabartmalar üzerindeki yüz yapıları. Wikimedia Commons + Met",
        data_sources=[
            "https://commons.wikimedia.org",
            "https://collectionapi.metmuseum.org",
        ],
        refresh_interval_sec=900,
    ),
    MapLayer(
        id="antique_dealer",
        name="Antique Market & Looted Art",
        name_tr="Antikacılar & Kayıp Eserler",
        layer_type=LayerType.ANTIQUE_DEALER,
        color="#ef9a9a",
        icon="ShoppingBag",
        z_index=70,
        description="Antika piyasası, kayıp/çalıntı eser takibi. INTERPOL, Art Loss Register",
        data_sources=[
            "https://www.interpol.int/Crimes/Cultural-heritage-crime",
            "https://www.lostart.de",
        ],
        refresh_interval_sec=3600,
    ),
    MapLayer(
        id="video_media",
        name="Video & Documentary Archive",
        name_tr="Video & Belgesel Arşivi",
        layer_type=LayerType.VIDEO_MEDIA,
        color="#80cbc4",
        icon="Video",
        z_index=80,
        description="YouTube belgeseller, Internet Archive videoları, saha kayıtları",
        data_sources=[
            "https://archive.org/advancedsearch.php",
            "https://www.googleapis.com/youtube/v3/search",
        ],
        refresh_interval_sec=600,
    ),
    MapLayer(
        id="surface_scan",
        name="Surface Scan Layer",
        name_tr="Yüzey Tarama Katmanı",
        layer_type=LayerType.SURFACE_SCAN,
        color="#a5d6a7",
        icon="Layers",
        z_index=90,
        description="Yüklenen fotoğraf/video → 3D ızgara, DStretch filtre, oyuk tespiti",
        data_sources=["local_upload"],
        refresh_interval_sec=0,
    ),
    MapLayer(
        id="fake_detector",
        name="Authenticity Verification",
        name_tr="Otantiklik & Sahte Tespit",
        layer_type=LayerType.FAKE_DETECTOR,
        color="#ff7043",
        icon="ShieldCheck",
        z_index=100,
        description="ELA analizi, AI üretim riski, EXIF kontrolü, sıkıştırma anomalisi",
        data_sources=["local_analysis"],
        refresh_interval_sec=0,
    ),
]


def layer_config_json() -> dict:
    """Frontend için katman konfigürasyonu JSON'u"""
    return {
        "layers": [
            {
                "id": l.id,
                "name": l.name,
                "name_tr": l.name_tr,
                "agent": l.layer_type.value,
                "color": l.color,
                "icon": l.icon,
                "z_index": l.z_index,
                "enabled": l.enabled,
                "opacity": l.opacity,
                "cluster_radius": l.cluster_radius,
                "description": l.description,
                "data_sources": l.data_sources,
                "refresh_sec": l.refresh_interval_sec,
            }
            for l in ARCHAEO_LAYERS
        ]
    }
