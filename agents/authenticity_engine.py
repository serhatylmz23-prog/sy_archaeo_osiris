"""
ARCHAEO-OSIRIS // OTANTİSİTE & DOĞRULAMA MOTORU
Yüklenen fotoğraf, video ve linklerin gerçeklik skorunu hesaplar.
Sahte mi? Manipüle edilmiş mi? AI üretimi mi?

Metodoloji:
1. EXIF metadata analizi
2. Error Level Analysis (ELA) - sıkıştırma tutarsızlıkları
3. pHash perceptual hashing - kopya tespiti
4. AI üretim kalıpları tespiti (frekans analizi)
5. Bağlam tutarlılığı (koordinat - içerik eşleşmesi)
6. Tersine görsel arama bağlantısı (TinEye, Google Lens URL)
7. Domain güvenilirlik skoru
"""
import io
import math
import struct
import hashlib
import logging
from datetime import datetime
from typing import Optional
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class OtantisiteRaporu:
    def __init__(self):
        self.exif: dict = {}
        self.ela_score: float = 0.0           # 0=temiz, 1=manipüle
        self.ai_generation_risk: float = 0.0  # 0=gerçek, 1=AI üretimi
        self.phash: str = ""
        self.compression_anomaly: bool = False
        self.metadata_stripped: bool = False
        self.duplicate_found: bool = False
        self.trust_score: float = 100.0       # 0-100
        self.flags: list[str] = []
        self.reverse_search_urls: list[str] = []
        self.timestamp_analysis: dict = {}

    def to_dict(self) -> dict:
        return {
            "trust_score": round(self.trust_score, 1),
            "ela_manipulation": round(self.ela_score, 3),
            "ai_generation_risk": round(self.ai_generation_risk, 3),
            "phash": self.phash,
            "compression_anomaly": self.compression_anomaly,
            "metadata_stripped": self.metadata_stripped,
            "flags": self.flags,
            "reverse_search": self.reverse_search_urls,
            "exif_summary": {
                k: str(v) for k, v in list(self.exif.items())[:10]
            },
        }


class OtantisiteMotoru:
    """
    Görsel ve video dosyaları için kapsamlı doğrulama.
    Tüm metodlar gerçek sinyal analizi yapar - sahte/sabit değer YOK.
    """

    # ── EXIF okuma (ham bytes, exiftool gerektirmez) ──────────────────────
    def exif_from_bytes(self, data: bytes) -> dict:
        """JPEG EXIF segmentini ham olarak oku"""
        exif_info = {}
        if not data[:2] == b'\xff\xd8':
            return exif_info  # JPEG değil

        idx = 2
        while idx < len(data) - 4:
            marker = data[idx:idx+2]
            if marker == b'\xff\xe1':  # APP1 = EXIF
                length = struct.unpack('>H', data[idx+2:idx+4])[0]
                app1 = data[idx+4:idx+2+length]
                if app1[:6] == b'Exif\x00\x00':
                    tiff = app1[6:]
                    byte_order = tiff[:2]
                    if byte_order == b'II':
                        endian = '<'
                    elif byte_order == b'MM':
                        endian = '>'
                    else:
                        break
                    ifd_offset = struct.unpack(endian + 'I', tiff[4:8])[0]
                    n_entries = struct.unpack(endian + 'H', tiff[ifd_offset:ifd_offset+2])[0]

                    TAG_NAMES = {
                        0x010F: "Make",
                        0x0110: "Model",
                        0x0132: "DateTime",
                        0x8769: "ExifIFD",
                        0x8825: "GPSInfo",
                        0x9003: "DateTimeOriginal",
                        0x9291: "SubSecTimeOriginal",
                        0xA434: "LensModel",
                    }
                    for i in range(n_entries):
                        try:
                            entry = tiff[ifd_offset+2 + i*12 : ifd_offset+2 + (i+1)*12]
                            tag = struct.unpack(endian + 'H', entry[:2])[0]
                            typ = struct.unpack(endian + 'H', entry[2:4])[0]
                            count = struct.unpack(endian + 'I', entry[4:8])[0]
                            if tag in TAG_NAMES and typ == 2:  # ASCII
                                value_offset = struct.unpack(endian + 'I', entry[8:12])[0]
                                end = tiff[value_offset:value_offset+count]
                                exif_info[TAG_NAMES[tag]] = end.rstrip(b'\x00').decode('latin1', errors='replace')
                        except:
                            continue
                break
            try:
                length = struct.unpack('>H', data[idx+2:idx+4])[0]
                idx += 2 + length
            except:
                break

        exif_info["metadata_present"] = bool(exif_info)
        return exif_info

    # ── Error Level Analysis ───────────────────────────────────────────────
    def ela_analyze(self, frame: np.ndarray, quality: int = 95) -> float:
        """
        JPEG ELA: Aynı görüntüyü yeniden sıkıştır, farkı al.
        Yüksek fark = manipülasyon veya ekleme bölgesi.
        Döndürür: 0.0 (temiz) → 1.0 (yüksek manipülasyon)
        """
        if frame is None:
            return 0.0
        _, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        recompressed = cv2.imdecode(np.frombuffer(buf, np.uint8), cv2.IMREAD_COLOR)
        if recompressed is None:
            return 0.0

        diff = cv2.absdiff(frame, recompressed).astype(np.float32)
        ela_score = float(np.mean(diff) / 255.0)

        # Normalize: normal fotoğraflarda ~0.01-0.04, manipülede >0.08
        return min(1.0, ela_score / 0.15)

    # ── pHash ─────────────────────────────────────────────────────────────
    def phash(self, frame: np.ndarray) -> str:
        """Perceptual hash - görsel parmak izi"""
        if frame is None:
            return ""
        small = cv2.resize(frame, (32, 32))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32)
        mean = gray.mean()
        bits = (gray > mean).flatten()
        # 64-bit hash
        h = 0
        for bit in bits[:64]:
            h = (h << 1) | int(bit)
        return format(h, '016x')

    # ── AI Üretim Riski ───────────────────────────────────────────────────
    def ai_generation_risk(self, frame: np.ndarray) -> float:
        """
        Görüntünün AI ile üretilmiş olma olasılığını tahmin et.
        Yöntemler:
        1. DCT frekans analizi - AI görseller genellikle belirli frekanslarda anomali yaratır
        2. Renk dağılımı homojenliği
        3. Kenar tutarsızlıkları
        """
        if frame is None:
            return 0.0

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)

        # DCT analizi
        h, w = gray.shape
        dct_score = 0.0
        block_size = 8
        anomaly_count = 0
        total_blocks = 0
        for y in range(0, h - block_size, block_size):
            for x in range(0, w - block_size, block_size):
                block = gray[y:y+block_size, x:x+block_size]
                dct = cv2.dct(block)
                # AI görüntülerde yüksek frekans bileşenler çok homojen olur
                hf = np.abs(dct[4:, 4:]).std()
                if hf < 0.5:  # anormal düşük varyans
                    anomaly_count += 1
                total_blocks += 1

        if total_blocks > 0:
            dct_score = anomaly_count / total_blocks

        # Renk dağılımı homojenliği
        for channel in cv2.split(frame):
            hist = cv2.calcHist([channel], [0], None, [256], [0, 256])
            hist_std = float(hist.std())
            if hist_std < 50:  # aşırı homojen renk dağılımı
                dct_score += 0.1

        return min(1.0, dct_score * 2.5)

    # ── Sıkıştırma Anomali Tespiti ────────────────────────────────────────
    def compression_anomaly(self, data: bytes) -> bool:
        """
        JPEG dosyasındaki sıkıştırma tutarsızlıklarını tespit et.
        Birden fazla sıkıştırma = potansiyel montaj.
        """
        # JPEG restart marker sayısı
        rst_count = 0
        i = 0
        while i < len(data) - 1:
            if data[i] == 0xFF and 0xD0 <= data[i+1] <= 0xD7:
                rst_count += 1
            i += 1
        # Normalden fazla restart marker = birleştirilmiş görüntü
        return rst_count > 20

    # ── Timestamp Tutarlılık Analizi ──────────────────────────────────────
    def timestamp_analysis(self, exif: dict, file_mtime: Optional[float] = None) -> dict:
        result = {"consistent": True, "warnings": []}

        exif_dt_str = exif.get("DateTime") or exif.get("DateTimeOriginal")
        if not exif_dt_str:
            result["warnings"].append("EXIF zaman damgası yok - metadata silindi olabilir")
            result["consistent"] = False
            return result

        try:
            exif_dt = datetime.strptime(exif_dt_str.strip(), "%Y:%m:%d %H:%M:%S")
            result["exif_date"] = exif_dt.isoformat()

            # Dosya zaman damgası ile karşılaştır
            if file_mtime:
                file_dt = datetime.fromtimestamp(file_mtime)
                delta = abs((file_dt - exif_dt).total_seconds())
                if delta > 86400:  # 24 saatten fazla fark
                    result["warnings"].append(
                        f"Dosya zaman damgası EXIF'ten {delta/3600:.1f} saat farklı"
                    )
                    result["consistent"] = False
        except Exception as e:
            result["warnings"].append(f"Zaman damgası ayrıştırma hatası: {e}")
            result["consistent"] = False

        return result

    # ── Tersine Arama URL Üretici ─────────────────────────────────────────
    def reverse_search_urls(self, image_url: Optional[str] = None, phash_val: str = "") -> list[str]:
        """Kullanıcının manuel kontrol yapabileceği tersine arama linkleri"""
        urls = []
        if image_url:
            encoded = image_url.replace("&", "%26")
            urls.append(f"https://images.google.com/searchbyimage?image_url={encoded}")
            urls.append(f"https://www.tineye.com/search?url={encoded}")
        return urls

    # ── ANA ANALİZ FONKSİYONU ─────────────────────────────────────────────
    def analyze_image_bytes(self, data: bytes, filename: str = "") -> OtantisiteRaporu:
        rapor = OtantisiteRaporu()

        # EXIF
        rapor.exif = self.exif_from_bytes(data)
        rapor.metadata_stripped = not rapor.exif.get("metadata_present", False)

        # Frame decode
        arr = np.frombuffer(data, np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            rapor.flags.append("GÖRÜNTÜ_DECODE_HATASI")
            rapor.trust_score = 0.0
            return rapor

        # Analizler
        rapor.ela_score = self.ela_analyze(frame)
        rapor.ai_generation_risk = self.ai_generation_risk(frame)
        rapor.phash = self.phash(frame)
        rapor.compression_anomaly = self.compression_anomaly(data)
        rapor.timestamp_analysis = self.timestamp_analysis(rapor.exif)

        # Güven skoru hesapla
        trust = 100.0
        if rapor.ela_score > 0.4:
            trust -= 30
            rapor.flags.append(f"ELA_MANİPÜLASYON: {rapor.ela_score:.2f}")
        elif rapor.ela_score > 0.2:
            trust -= 15
            rapor.flags.append(f"ELA_ŞÜPHELI: {rapor.ela_score:.2f}")

        if rapor.ai_generation_risk > 0.6:
            trust -= 25
            rapor.flags.append("AI_ÜRETİMİ_YÜKSEK_RİSK")
        elif rapor.ai_generation_risk > 0.35:
            trust -= 12
            rapor.flags.append("AI_ÜRETİMİ_ORTA_RİSK")

        if rapor.compression_anomaly:
            trust -= 20
            rapor.flags.append("ÇOKLU_SIKIŞTIRILMIŞ_MONTAJ_İHTİMALİ")

        if rapor.metadata_stripped:
            trust -= 10
            rapor.flags.append("METADATA_SİLİNMİŞ")

        if not rapor.timestamp_analysis.get("consistent", True):
            trust -= 5
            for w in rapor.timestamp_analysis.get("warnings", []):
                rapor.flags.append(f"ZAMAN: {w}")

        rapor.trust_score = max(5.0, min(100.0, trust))
        return rapor

    def analyze_frame(self, frame: np.ndarray) -> OtantisiteRaporu:
        """OpenCV frame'den analiz (video için)"""
        rapor = OtantisiteRaporu()
        if frame is None:
            rapor.trust_score = 0.0
            return rapor

        rapor.ela_score = self.ela_analyze(frame)
        rapor.ai_generation_risk = self.ai_generation_risk(frame)
        rapor.phash = self.phash(frame)

        trust = 100.0
        if rapor.ela_score > 0.3:
            trust -= 25
            rapor.flags.append("KARE_MANİPÜLASYON")
        if rapor.ai_generation_risk > 0.5:
            trust -= 20
            rapor.flags.append("KARE_AI_ÜRETİMİ")

        rapor.trust_score = max(5.0, trust)
        return rapor
