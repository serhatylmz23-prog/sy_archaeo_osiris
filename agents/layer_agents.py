"""
ARCHAEO-OSIRIS // KATMAN AJANLARI
Her harita katmanı için özelleştirilmiş, gerçek veriye ulaşan ajan sınıfları.
Sahte veri YOK - tüm kaynaklar gerçek public API veya scrape edilebilir sitelerdir.
"""
import asyncio
import json
import re
import logging
from typing import Optional
from urllib.parse import urlparse, urlencode, quote_plus

import httpx
from bs4 import BeautifulSoup

from core.agent_base import BaseArcheoAgent, LayerType, ScanResult, AgentMemory

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# ORTAK HTTP YARDIMCI
# ─────────────────────────────────────────────────────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
}

async def safe_get(url: str, timeout=15) -> Optional[httpx.Response]:
    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=timeout, follow_redirects=True) as c:
            r = await c.get(url)
            if r.status_code == 200:
                return r
    except Exception as e:
        logger.debug(f"HTTP hata [{url}]: {e}")
    return None


def extract_coords(text: str) -> Optional[tuple]:
    """Metinden GPS koordinatı çıkarmaya çalış"""
    patterns = [
        r'(\d{1,2}[.,]\d{4,})[°\s]*[NK]\s*[,/]\s*(\d{1,3}[.,]\d{4,})[°\s]*[ED]',
        r'lat[:\s=]+(-?\d{1,2}[.,]\d+).*?(?:lon|lng)[:\s=]+(-?\d{1,3}[.,]\d+)',
        r'(\d{2}\.\d{4,}),\s*(\d{2,3}\.\d{4,})',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                lat = float(m.group(1).replace(',', '.'))
                lon = float(m.group(2).replace(',', '.'))
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    return (lat, lon)
            except:
                pass
    return None


# ─────────────────────────────────────────────────────────────
# 1. AKADEMİK AJAN — Üniversite, makale, tez
# ─────────────────────────────────────────────────────────────
class AcademicAgent(BaseArcheoAgent):
    """
    Kaynaklar:
    - OpenAlex API (ücretsiz, akademik makaleler)
    - Semantic Scholar API (ücretsiz)
    - Türk üniversite açık erişim depoları
    - tez.yok.gov.tr (YÖK tez veritabanı)
    """
    QUERIES = [
        "archaeology Turkey excavation",
        "Anadolu höyük kazı",
        "tumulus burial mound Turkey",
        "rock inscription Anatolia",
        "treasure hunting symbols Turkey",
        "Hittite burial ritual",
        "prehistoric cave Turkey",
        "Byzantine hidden treasure",
    ]
    OPENALEX = "https://api.openalex.org/works"
    SEMANTIC = "https://api.semanticscholar.org/graph/v1/paper/search"

    def __init__(self):
        super().__init__(LayerType.ACADEMIC, "AkademikAjan")
        self._query_idx = 0

    async def discover_sources(self) -> list[str]:
        query = self.QUERIES[self._query_idx % len(self.QUERIES)]
        self._query_idx += 1
        urls = []

        # OpenAlex
        params = {
            "search": query,
            "filter": "type:article",
            "per-page": "10",
            "select": "id,doi,title,open_access,primary_location",
        }
        r = await safe_get(f"{self.OPENALEX}?{urlencode(params)}")
        if r:
            data = r.json()
            for work in data.get("results", []):
                loc = work.get("primary_location") or {}
                landing = loc.get("landing_page_url")
                if landing:
                    urls.append(landing)
                doi = work.get("doi")
                if doi and "doi.org" in doi:
                    urls.append(doi)

        # Semantic Scholar
        ss_params = {"query": query, "limit": 8, "fields": "url,externalIds"}
        r2 = await safe_get(f"{self.SEMANTIC}?{urlencode(ss_params)}")
        if r2:
            data2 = r2.json()
            for paper in data2.get("data", []):
                u = paper.get("url")
                if u:
                    urls.append(u)

        return list(set(urls))[:15]

    async def analyze_source(self, url: str) -> Optional[ScanResult]:
        r = await safe_get(url)
        if not r:
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        title = soup.title.string.strip() if soup.title else url
        text = soup.get_text(separator=" ").lower()

        kw_list = [
            "kazı", "tumulus", "höyük", "lahit", "arkeoloji", "excavation",
            "burial", "mound", "inscription", "rock art", "kaya resmi",
            "mezar", "sikke", "stela", "hiyeroglif",
        ]
        found = [kw for kw in kw_list if kw in text]
        relevance = min(1.0, len(found) / 5)
        coords = extract_coords(text)

        meta = soup.find("meta", attrs={"name": "description"})
        summary = meta["content"][:300] if meta and meta.get("content") else text[:200]

        return ScanResult(
            layer=LayerType.ACADEMIC,
            source_url=url,
            title=title[:120],
            summary=summary,
            relevance_score=relevance,
            fake_probability=0.05,  # Akademik kaynaklar yüksek güvenilir
            keywords=found,
            media_urls=[],
            coordinates=coords,
        )


# ─────────────────────────────────────────────────────────────
# 2. MÜZE AJANI — Koleksiyonlar, kataloglar, eserler
# ─────────────────────────────────────────────────────────────
class MuseumAgent(BaseArcheoAgent):
    """
    Kaynaklar:
    - Europeana API (Avrupa müzeleri, ücretsiz)
    - The Metropolitan Museum of Art Open Access API
    - Harvard Art Museums API (ücretsiz key)
    - Rijksmuseum API
    - Türk müzelerinin web siteleri
    """
    MET_API = "https://collectionapi.metmuseum.org/public/collection/v1"
    EUROPEANA = "https://api.europeana.eu/record/v2/search.json"

    SEARCH_TERMS = [
        "anatolia bronze age",
        "hittite artifact",
        "byzantine treasure",
        "roman tomb turkey",
        "ancient coin anatolia",
        "relief sculpture turkey",
        "sarcophagus anatolia",
        "greek vase turkey",
    ]

    def __init__(self):
        super().__init__(LayerType.MUSEUM, "MüzeAjanı")
        self._term_idx = 0

    async def discover_sources(self) -> list[str]:
        term = self.SEARCH_TERMS[self._term_idx % len(self.SEARCH_TERMS)]
        self._term_idx += 1
        urls = []

        # Met Museum - ücretsiz, key gerekmez
        search_r = await safe_get(
            f"{self.MET_API}/search?q={quote_plus(term)}&hasImages=true"
        )
        if search_r:
            ids = search_r.json().get("objectIDs") or []
            for oid in ids[:8]:
                urls.append(f"{self.MET_API}/objects/{oid}")

        return urls

    async def analyze_source(self, url: str) -> Optional[ScanResult]:
        r = await safe_get(url)
        if not r:
            return None

        if "metmuseum" in url and url.endswith(url.split("/")[-1]) and url.split("/")[-1].isdigit():
            # Met API JSON yanıtı
            obj = r.json()
            title = obj.get("title", "İsimsiz Eser")
            desc = f"{obj.get('objectName','')} | {obj.get('period','')}, {obj.get('culture','')}"
            media = []
            if obj.get("primaryImage"):
                media.append(obj["primaryImage"])
            media += (obj.get("additionalImages") or [])[:3]

            kw = [
                k for k in ["burial", "tomb", "ritual", "inscription", "relief", "coin", "sarcophagus"]
                if k.lower() in (title + desc).lower()
            ]
            return ScanResult(
                layer=LayerType.MUSEUM,
                source_url=obj.get("objectURL", url),
                title=title[:120],
                summary=desc[:300],
                relevance_score=min(1.0, 0.4 + len(kw) * 0.15),
                fake_probability=0.02,
                keywords=kw,
                media_urls=media,
            )

        # Genel HTML
        soup = BeautifulSoup(r.text, "html.parser")
        title = soup.title.string.strip() if soup.title else url
        imgs = [i["src"] for i in soup.find_all("img", src=True) if not i["src"].startswith("data:")][:4]
        text = soup.get_text().lower()
        kw = [k for k in ["lahit", "kaya", "mezar", "sikke", "heykel", "relief", "stela"] if k in text]

        return ScanResult(
            layer=LayerType.MUSEUM,
            source_url=url,
            title=title[:120],
            summary=text[:200],
            relevance_score=min(1.0, 0.3 + len(kw) * 0.1),
            fake_probability=0.05,
            keywords=kw,
            media_urls=imgs,
        )


# ─────────────────────────────────────────────────────────────
# 3. SAHA / AKTİF KAZI AJANI
# ─────────────────────────────────────────────────────────────
class FieldworkAgent(BaseArcheoAgent):
    """
    Kaynaklar:
    - tDAR (Digital Archaeology Repository) - ücretsiz arama
    - ADS (Archaeology Data Service) UK
    - Open Context API
    - Türk arkeoloji dergisi & bakanlık kazı raporları
    """
    OPENCONTEXT = "https://opencontext.org/search/"
    ADS = "https://archaeologydataservice.ac.uk/archsearch/search.jsf"

    REGIONS = [
        "Turkey", "Anatolia", "Eastern Turkey", "Southeastern Anatolia",
        "Cappadocia", "Lycia", "Pontus",
    ]

    def __init__(self):
        super().__init__(LayerType.FIELDWORK, "SahaAjanı")
        self._region_idx = 0

    async def discover_sources(self) -> list[str]:
        region = self.REGIONS[self._region_idx % len(self.REGIONS)]
        self._region_idx += 1
        urls = []

        # Open Context - ücretsiz JSON API
        params = {"q": f"excavation {region}", "rows": 10, "response": "uri-meta"}
        r = await safe_get(f"{self.OPENCONTEXT}?{urlencode(params)}")
        if r:
            try:
                data = r.json()
                for item in (data.get("oc-api:has-results") or [])[:8]:
                    uri = item.get("id") or item.get("uri")
                    if uri:
                        urls.append(uri)
            except:
                pass

        return list(set(urls))

    async def analyze_source(self, url: str) -> Optional[ScanResult]:
        r = await safe_get(url)
        if not r:
            return None

        try:
            data = r.json()
            title = data.get("label") or data.get("dc-terms:title") or url
            desc = data.get("dc-terms:description") or str(data)[:300]
            context = str(data).lower()
            kw = [k for k in ["burial", "tomb", "cache", "hoard", "surface", "trench", "pit"] if k in context]
            coords = None
            if data.get("geo:lat") and data.get("geo:long"):
                coords = (float(data["geo:lat"]), float(data["geo:long"]))
            return ScanResult(
                layer=LayerType.FIELDWORK,
                source_url=url,
                title=str(title)[:120],
                summary=str(desc)[:300],
                relevance_score=min(1.0, 0.5 + len(kw) * 0.1),
                fake_probability=0.03,
                keywords=kw,
                media_urls=[],
                coordinates=coords,
            )
        except:
            pass

        soup = BeautifulSoup(r.text, "html.parser")
        title = soup.title.string.strip() if soup.title else url
        text = soup.get_text().lower()
        kw = [k for k in ["kazı", "höyük", "tümülüs", "nekropol", "mezarlık"] if k in text]
        return ScanResult(
            layer=LayerType.FIELDWORK,
            source_url=url,
            title=title[:120],
            summary=text[:200],
            relevance_score=min(1.0, 0.3 + len(kw) * 0.15),
            fake_probability=0.04,
            keywords=kw,
            media_urls=[],
        )


# ─────────────────────────────────────────────────────────────
# 4. DEFINE FORUMU AJANI
# ─────────────────────────────────────────────────────────────
class TreasureForumAgent(BaseArcheoAgent):
    """
    Gerçek public define/arkeoloji forumları:
    - arkeofili.com
    - arkeolojikhaber.com
    - defineciler.com (public sayfalar)
    - Reddit r/metaldetecting, r/archaeology
    - Türkçe forum siteleri
    """
    SOURCES = [
        "https://www.arkeofili.com",
        "https://www.arkeolojikhaber.com",
        "https://www.reddit.com/r/metaldetecting/new.json",
        "https://www.reddit.com/r/archaeology/new.json",
        "https://www.reddit.com/r/Treasure/new.json",
    ]

    TREASURE_KEYWORDS = [
        "define", "hazine", "işaret", "nokta", "gömü", "altın", "sikke",
        "kaya işareti", "harita", "tünnel", "mağara", "sütun", "taş",
        "metal dedektör", "metal detector", "hoard", "cache", "buried",
        "treasure map", "secret", "hidden", "symbol",
    ]

    def __init__(self):
        super().__init__(LayerType.TREASURE_FORUM, "ForumAjanı")
        self._src_idx = 0

    async def discover_sources(self) -> list[str]:
        urls = []
        src = self.SOURCES[self._src_idx % len(self.SOURCES)]
        self._src_idx += 1

        if "reddit.com" in src and src.endswith(".json"):
            r = await safe_get(src + "?limit=25&t=week")
            if r:
                try:
                    data = r.json()
                    posts = data["data"]["children"]
                    for post in posts:
                        pd = post["data"]
                        urls.append(f"https://www.reddit.com{pd['permalink']}.json")
                except:
                    pass
        else:
            r = await safe_get(src)
            if r:
                soup = BeautifulSoup(r.text, "html.parser")
                for a in soup.find_all("a", href=True)[:40]:
                    href = a["href"]
                    if href.startswith("http") and src.split("/")[2] in href:
                        urls.append(href)
                    elif href.startswith("/"):
                        urls.append(src.rstrip("/") + href)

        return list(set(urls))[:20]

    async def analyze_source(self, url: str) -> Optional[ScanResult]:
        r = await safe_get(url)
        if not r:
            return None

        title = url
        text = ""
        imgs = []

        if url.endswith(".json") and "reddit" in url:
            try:
                data = r.json()
                post_data = data[0]["data"]["children"][0]["data"]
                title = post_data.get("title", url)
                text = post_data.get("selftext", "").lower()
                if post_data.get("url_overridden_by_dest", "").endswith((".jpg", ".png", ".jpeg")):
                    imgs.append(post_data["url_overridden_by_dest"])
            except:
                pass
        else:
            soup = BeautifulSoup(r.text, "html.parser")
            title = soup.title.string.strip() if soup.title else url
            text = soup.get_text().lower()
            imgs = [i["src"] for i in soup.find_all("img", src=True) if not i["src"].startswith("data:")][:4]

        found = [kw for kw in self.TREASURE_KEYWORDS if kw in text]
        coords = extract_coords(text)
        relevance = min(1.0, len(found) / 4)

        # Forum içerikleri sahteye daha yatkın - dikkatli değerlendir
        fake_prob = 0.3 if relevance < 0.3 else 0.15

        return ScanResult(
            layer=LayerType.TREASURE_FORUM,
            source_url=url,
            title=title[:120],
            summary=text[:250],
            relevance_score=relevance,
            fake_probability=fake_prob,
            keywords=found,
            media_urls=imgs,
            coordinates=coords,
        )


# ─────────────────────────────────────────────────────────────
# 5. SEMBOL ANALİZ AJANI — Define işaretleri
# ─────────────────────────────────────────────────────────────
class SymbolAnalysisAgent(BaseArcheoAgent):
    """
    Define işaretleri, kaya sembolleri, oyuk analizi:
    - Wikipedia makalelerine (rock art, Anatolian symbols)
    - Rupestrian art databases
    - TRACCE online cave art bulletin
    - Bradshaw Foundation
    """
    SOURCES = [
        "https://en.wikipedia.org/wiki/Rock_art_in_Turkey",
        "https://en.wikipedia.org/wiki/Anatolian_rock_reliefs",
        "https://www.bradshawfoundation.com/cave_art_europe_central_asia.php",
        "https://en.wikipedia.org/wiki/Cup_and_ring_mark",
        "https://en.wikipedia.org/wiki/Hittite_rock_monuments",
    ]
    WIKI_SEARCH = "https://en.wikipedia.org/w/api.php"

    SYMBOL_KEYWORDS = [
        "kaya resmi", "oyuk", "sunak", "işaret", "sembol", "petroglyph",
        "rock carving", "inscription", "cup mark", "cross", "haç",
        "yılan", "kartal", "balık", "kılıç", "çivi yazısı",
        "luwian", "hittite", "urartian", "frigio",
    ]

    def __init__(self):
        super().__init__(LayerType.SYMBOL_ANALYSIS, "SembolAjanı")
        self._idx = 0

    async def discover_sources(self) -> list[str]:
        base_urls = list(self.SOURCES)

        # Wikipedia arama API - her seferinde farklı terim
        terms = ["Anatolian rock art", "Hittite symbols", "petroglyphs Turkey", "cave markings Anatolia"]
        term = terms[self._idx % len(terms)]
        self._idx += 1

                # Tam ifade araması ("...") + müzik bağlamını hariç tutan negatif terimler
        query = f'"{term}" -music -genre -band -song -album -guitarist'

        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": 8,
            "format": "json",
        }
        r = await safe_get(f"{self.WIKI_SEARCH}?{urlencode(params)}")
        if r:
            data = r.json()
            BLOCKLIST = ("rock and roll", "rock music", "rock genre", "punk rock",
                         "flamenco", "latin rock", "list of rock")
            for item in data.get("query", {}).get("search", []):
                title = item["title"]
                if any(b in title.lower() for b in BLOCKLIST):
                    continue
                title_enc = title.replace(" ", "_")
                base_urls.append(f"https://en.wikipedia.org/wiki/{title_enc}")
        return base_urls

    async def analyze_source(self, url: str) -> Optional[ScanResult]:
        r = await safe_get(url)
        if not r:
            return None

        soup = BeautifulSoup(r.text, "html.parser")
        title = soup.title.string.strip() if soup.title else url
        text = soup.get_text().lower()

        # Wikipedia'da görsel bul
        imgs = []
        for img in soup.find_all("img", src=True):
            src = img["src"]
            if "upload.wikimedia" in src and src.endswith((".jpg", ".png", ".jpeg")):
                full = "https:" + src if src.startswith("//") else src
                imgs.append(full)
        imgs = imgs[:6]

        found = [kw for kw in self.SYMBOL_KEYWORDS if kw in text]
        coords = extract_coords(text)

        return ScanResult(
            layer=LayerType.SYMBOL_ANALYSIS,
            source_url=url,
            title=title[:120],
            summary=text[:300],
            relevance_score=min(1.0, 0.4 + len(found) * 0.12),
            fake_probability=0.05,
            keywords=found,
            media_urls=imgs,
            coordinates=coords,
        )


# ─────────────────────────────────────────────────────────────
# 6. GÖRSEL / YÜZEY TANIMA AJANI — Heykeller, lahitler
# ─────────────────────────────────────────────────────────────
class ArtifactVisualAgent(BaseArcheoAgent):
    """
    Heykel, lahit, kabartma - görsel eserler:
    - Wikimedia Commons kategori arama
    - Met Museum görsel API
    - British Museum SPARQL endpoint
    NOT: Yüz tanıma sadece eserler için - insan değil.
    """
    COMMONS_API = "https://commons.wikimedia.org/w/api.php"
    CATEGORIES = [
        "Category:Sculptures_from_Turkey",
        "Category:Sarcophagi_in_Turkey",
        "Category:Hittite_monuments",
        "Category:Ancient_Greek_reliefs",
        "Category:Urartian_artifacts",
        "Category:Bronze_Age_artifacts_from_Turkey",
    ]

    def __init__(self):
        super().__init__(LayerType.ARTIFACT_VISUAL, "GörselAjanı")
        self._cat_idx = 0

    async def discover_sources(self) -> list[str]:
        cat = self.CATEGORIES[self._cat_idx % len(self.CATEGORIES)]
        self._cat_idx += 1
        urls = []

        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": cat,
            "cmtype": "file",
            "cmlimit": "15",
            "format": "json",
        }
        r = await safe_get(f"{self.COMMONS_API}?{urlencode(params)}")
        if r:
            data = r.json()
            members = data.get("query", {}).get("categorymembers", [])
            for m in members:
                title = m.get("title", "").replace(" ", "_")
                urls.append(f"https://commons.wikimedia.org/wiki/{title}")

        return urls

    async def analyze_source(self, url: str) -> Optional[ScanResult]:
        r = await safe_get(url)
        if not r:
            return None

        soup = BeautifulSoup(r.text, "html.parser")
        title = soup.title.string.strip() if soup.title else url

        # Wikimedia'da tam boyut görsel bul
        imgs = []
        full_img = soup.find("div", class_="fullImageLink")
        if full_img and full_img.find("a"):
            href = full_img.find("a")["href"]
            if href.startswith("//"):
                href = "https:" + href
            imgs.append(href)

        # Meta bilgisi
        text = soup.get_text().lower()
        kw = [
            k for k in ["face", "portrait", "bust", "head", "yüz", "heykel",
                         "lahit", "kabartma", "relief", "mask", "idol", "figurine"]
            if k in text
        ]

        return ScanResult(
            layer=LayerType.ARTIFACT_VISUAL,
            source_url=url,
            title=title[:120],
            summary=text[:200],
            relevance_score=min(1.0, 0.5 + len(kw) * 0.1),
            fake_probability=0.03,
            keywords=kw,
            media_urls=imgs,
        )


# ─────────────────────────────────────────────────────────────
# 7. ANTİKACI / MÜZAYEDE AJANI
# ─────────────────────────────────────────────────────────────
class AntiqueDealerAgent(BaseArcheoAgent):
    """
    Antika piyasası takibi (kayıp eser tespiti için):
    - Loot.gr (çalıntı eser DB)
    - INTERPOL stolen works (public RSS)
    - UNESCO database references
    - Legitimate auction house public catalogs
    """
    SOURCES = [
        "https://www.interpol.int/en/Crimes/Cultural-heritage-crime/Stolen-Works-of-Art-Database",
        "https://db.aa-a.org/search/",  # Art Loss Register arama
        "https://www.lostart.de/en/",   # Kayıp sanat veritabanı
    ]
    STOLEN_KEYWORDS = [
        "stolen", "looted", "illicit", "smuggled", "missing", "kayıp",
        "çalıntı", "kaçakçılık", "illegal export", "unprovenanced",
        "Turkey", "Anatolia", "repatriation", "iade",
    ]

    def __init__(self):
        super().__init__(LayerType.ANTIQUE_DEALER, "AntikacıAjanı")

    async def discover_sources(self) -> list[str]:
        return self.SOURCES

    async def analyze_source(self, url: str) -> Optional[ScanResult]:
        r = await safe_get(url)
        if not r:
            return None

        soup = BeautifulSoup(r.text, "html.parser")
        title = soup.title.string.strip() if soup.title else url
        text = soup.get_text().lower()
        found = [kw for kw in self.STOLEN_KEYWORDS if kw in text]

        return ScanResult(
            layer=LayerType.ANTIQUE_DEALER,
            source_url=url,
            title=title[:120],
            summary=text[:200],
            relevance_score=min(1.0, 0.3 + len(found) * 0.1),
            fake_probability=0.1,
            keywords=found,
            media_urls=[],
        )


# ─────────────────────────────────────────────────────────────
# 8. VİDEO MEDYA AJANI — YouTube, belgeseller
# ─────────────────────────────────────────────────────────────
class VideoMediaAgent(BaseArcheoAgent):
    """
    Video içerik tarama:
    - YouTube Data API v3 (ücretsiz, 10k quota/gün)
    - Internet Archive video bölümü
    - Vimeo public API
    """
    YOUTUBE_SEARCH = "https://www.googleapis.com/youtube/v3/search"
    ARCHIVE_SEARCH = "https://archive.org/advancedsearch.php"

    QUERIES = [
        "Türkiye arkeoloji kazı",
        "Anadolu define işaretleri",
        "Turkey ancient treasure documentary",
        "hittite excavation documentary",
        "Türkiye kaya mezarları",
        "archaeology Turkey underground",
        "define avcısı kaya işaretleri",
    ]

    def __init__(self, youtube_api_key: Optional[str] = None):
        super().__init__(LayerType.VIDEO_MEDIA, "VideoAjanı")
        self.yt_key = youtube_api_key
        self._q_idx = 0

    async def discover_sources(self) -> list[str]:
        q = self.QUERIES[self._q_idx % len(self.QUERIES)]
        self._q_idx += 1
        urls = []

        # Internet Archive - API key gerektirmez
        params = {
            "q": f"({q}) AND mediatype:movies",
            "fl[]": "identifier,title,description",
            "rows": 10,
            "output": "json",
        }
        r = await safe_get(f"{self.ARCHIVE_SEARCH}?{urlencode(params)}")
        if r:
            try:
                data = r.json()
                for doc in data.get("response", {}).get("docs", []):
                    iid = doc.get("identifier")
                    if iid:
                        urls.append(f"https://archive.org/details/{iid}")
            except:
                pass

        # YouTube (key varsa)
        if self.yt_key:
            yt_params = {
                "part": "snippet",
                "q": q,
                "type": "video",
                "maxResults": 8,
                "key": self.yt_key,
            }
            r2 = await safe_get(f"{self.YOUTUBE_SEARCH}?{urlencode(yt_params)}")
            if r2:
                data2 = r2.json()
                for item in data2.get("items", []):
                    vid_id = item["id"].get("videoId")
                    if vid_id:
                        urls.append(f"https://www.youtube.com/watch?v={vid_id}")

        return list(set(urls))

    async def analyze_source(self, url: str) -> Optional[ScanResult]:
        r = await safe_get(url)
        if not r:
            return None

        soup = BeautifulSoup(r.text, "html.parser")
        title = soup.title.string.strip() if soup.title else url
        text = soup.get_text().lower()

        kw = [
            k for k in ["arkeoloji", "archaeology", "kazı", "excavation", "define",
                         "treasure", "kaya", "mezar", "höyük", "tümülüs", "lahit"]
            if k in text
        ]

        imgs = [i["src"] for i in soup.find_all("img", src=True)
                if not i["src"].startswith("data:") and "thumb" in i["src"].lower()][:3]

        return ScanResult(
            layer=LayerType.VIDEO_MEDIA,
            source_url=url,
            title=title[:120],
            summary=text[:200],
            relevance_score=min(1.0, 0.3 + len(kw) * 0.12),
            fake_probability=0.2,  # Video içerik → orta güven
            keywords=kw,
            media_urls=imgs,
        )
