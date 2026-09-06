"""
Yüzey tarayıcısını tek bir görüntü/video üzerinde test et.
Kullanım: python tools/test_scanner.py <dosya_yolu> [filtre]
Filtreler: ORIGINAL, YDS, LAB, THERMAL, EDGE
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import cv2
import numpy as np
from scanner.surface_scanner import SurfaceGridScanner
from agents.authenticity_engine import OtantisiteMotoru

def test_image(path: str, mode: str = "ORIGINAL"):
    print(f"[TARAYICI] Görüntü: {path} | Filtre: {mode}")
    scanner = SurfaceGridScanner()
    otantisite = OtantisiteMotoru()

    frame = cv2.imread(path)
    if frame is None:
        print("HATA: Görüntü yüklenemedi.")
        return

    annotated, detections = scanner.render_surface_effects(frame, mode=mode)

    with open(path, "rb") as f:
        data = f.read()
    auth = otantisite.analyze_image_bytes(data)

    print(f"\n📊 OTANTİSİTE RAPORU:")
    print(f"  Güven Skoru  : {auth.trust_score:.1f}/100")
    print(f"  ELA Skoru    : {auth.ela_score:.3f}")
    print(f"  AI Üretim    : {auth.ai_generation_risk:.3f}")
    print(f"  pHash        : {auth.phash}")
    print(f"  Uyarılar     : {', '.join(auth.flags) or 'Yok'}")

    print(f"\n🔍 TESPİTLER ({len(detections)} adet):")
    for d in detections:
        print(f"  [{d['id']}] {d['type']} | merkez={d['center']} r={d['radius']} güven=%{d['confidence']:.0f}")

    # Görüntüyü göster
    out_path = path.replace(".", "_analyzed.")
    cv2.imwrite(out_path, annotated)
    print(f"\n✅ Analiz kaydedildi: {out_path}")

    # Pencere aç (mümkünse)
    try:
        cv2.imshow("Archaeo-Osiris Tarama", cv2.resize(annotated, (1200, 675)))
        print("Çıkmak için herhangi bir tuşa basın...")
        cv2.waitKey(0)
        cv2.destroyAllWindows()
    except:
        print("(Görüntü penceresi açılamadı - headless mod)")


def test_video(path: str, mode: str = "ORIGINAL"):
    print(f"[TARAYICI] Video: {path} | Filtre: {mode}")
    scanner = SurfaceGridScanner()
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"FPS: {fps} | Toplam Kare: {total}")

    out_path = path.replace(".", "_scanned.")
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    writer = cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*'mp4v'), fps, (w, h))

    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        processed, dets = scanner.render_surface_effects(frame, mode=mode, frame_idx=frame_idx)
        writer.write(processed)
        frame_idx += 1
        if frame_idx % 50 == 0:
            print(f"  Kare {frame_idx}/{total} | {len(dets)} tespit")

    cap.release()
    writer.release()
    print(f"\n✅ Video kaydedildi: {out_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Kullanım: python tools/test_scanner.py <dosya> [filtre]")
        sys.exit(1)

    path = sys.argv[1]
    mode = sys.argv[2].upper() if len(sys.argv) > 2 else "ORIGINAL"

    if path.lower().endswith(('.mp4', '.mov', '.avi', '.mkv')):
        test_video(path, mode)
    else:
        test_image(path, mode)
