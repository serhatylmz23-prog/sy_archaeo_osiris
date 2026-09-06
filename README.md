# ARCHAEO-OSIRIS v2.0
## Arkeoloji Odaklı Canlı İstihbarat Ekosistemi

---

## Proje Yapısı

```
archaeo_osiris/
│
├── main.py                    ← Giriş noktası (uvicorn)
├── requirements.txt
│
├── core/
│   ├── agent_base.py          ← Tüm ajanların temel sınıfı
│   └── ecosystem.py           ← Ekosistem orkestratörü & EventBus
│
├── agents/
│   ├── layer_agents.py        ← 8 katman ajanı (gerçek veri)
│   └── authenticity_engine.py ← Sahte tespit motoru (ELA, pHash, AI risk)
│
├── layers/
│   └── map_layers.py          ← Harita katmanı konfigürasyonları
│
├── scanner/
│   └── surface_scanner.py     ← Yüzey tarayıcı (3D ızgara, DStretch, tespit)
│
├── api/
│   └── server.py              ← FastAPI sunucu, tüm endpoint'ler
│
├── tools/
│   ├── run_agents.py          ← Ajan simülasyon test aracı
│   └── test_scanner.py        ← Tek görüntü/video tarama test aracı
│
└── .vscode/
    ├── launch.json            ← F5 ile çalıştır
    └── settings.json
```

---

## Harita Katmanları & Ajanlar

| Katman | Ajan | Gerçek Veri Kaynağı |
|--------|------|---------------------|
| Akademik | AcademicAgent | OpenAlex API, Semantic Scholar |
| Müze | MuseumAgent | Met Museum Open API, Europeana |
| Aktif Kazılar | FieldworkAgent | Open Context API |
| Define Forumları | TreasureForumAgent | arkeofili.com, Reddit |
| Sembol Analizi | SymbolAnalysisAgent | Wikipedia API, Bradshaw Foundation |
| Eser Görsel | ArtifactVisualAgent | Wikimedia Commons API |
| Antikacı | AntiqueDealerAgent | INTERPOL, Art Loss Register |
| Video Medya | VideoMediaAgent | Internet Archive, YouTube API |
| Yüzey Tarama | SurfaceGridScanner | Yerel yükleme (OpenCV) |
| Sahte Tespit | OtantisiteMotoru | ELA + DCT + EXIF analizi |

---

## Kurulum

```bash
# 1. Sanal ortam
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # Linux/Mac

# 2. Bağımlılıklar
pip install -r requirements.txt

# 3. Ortam değişkenleri (.env dosyası oluştur)
YOUTUBE_API_KEY=AIza...          # İsteğe bağlı
ANTHROPIC_API_KEY=sk-ant-...     # Gelecek geliştirme

# 4. VSCode'da F5 veya terminal
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

---

## API Endpoint'leri

```
GET  /api/health                    → Sistem sağlık kontrolü
GET  /api/ecosystem/status          → Tüm ajan durumu
GET  /api/ecosystem/feed?limit=30   → Canlı sonuç akışı
GET  /api/ecosystem/alerts          → Yüksek relevans / sahte uyarıları
GET  /api/ecosystem/layer/{katman}  → Katman bazlı sonuçlar
     katmanlar: akademik, müze, saha, forum, sembol, görsel, antikacı, medya

POST /api/pipeline/analyze          → Medya yükle + analiz et
     form: files[], links, filter_mode (ORIGINAL|YDS|LAB|THERMAL|EDGE)

GET  /api/video/stream              → MJPEG canlı video akışı
WS   /ws/live-feed                  → WebSocket gerçek zamanlı ajan beslemesi
```

---

## Ajan Mimarisi

Her ajan:
1. `discover_sources()` → Yeni URL'ler bul
2. `analyze_source(url)` → Analiz et → `ScanResult` döndür
3. `self_improve()` → Başarılı bulgulardan öğren, tarama sıklığını ayarla
4. EventBus üzerinden diğer ajanlara koordinat paylaş

```
AcademicAgent ──┐
MuseumAgent ────┤
FieldworkAgent ─┤
ForumAgent ─────┤──→ EventBus ──→ UI / WebSocket
SymbolAgent ────┤         ↕
ArtifactAgent ──┤    Çapraz-öğrenme
AntiqueAgent ───┤    (koordinat paylaşımı)
VideoAgent ─────┘
```

---

## Otantiklik Motoru

Her yüklenen görüntü için:
- **ELA (Error Level Analysis)**: Sıkıştırma tutarsızlıkları → montaj tespiti
- **DCT Frekans Analizi**: AI üretimi tespiti (GAN/Diffusion kalıpları)
- **pHash**: Perceptual hash → kopya/manipülasyon takibi
- **EXIF Metadata**: Cihaz, tarih, GPS kontrolü
- **Güven Skoru**: 0-100 arası sayısal doğruluk değeri

---

## Yüzey Tarayıcı Filtreleri

| Filtre | Açıklama |
|--------|----------|
| ORIGINAL | Doğal renk + 3D ızgara + neon hedef |
| YDS | DStretch YCrCb → aşıboyası, pigment |
| LAB | DStretch LAB → derinlik, karbonat |
| THERMAL | Termal renk haritası (INFERNO) |
| EDGE | Canny + Sobel kenar füzyonu |
