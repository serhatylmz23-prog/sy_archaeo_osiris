"""
Tüm ajanları sunucu olmadan test et.
Terminalde: python tools/run_agents.py
"""
import asyncio
import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.ecosystem import ArcheoEcosystem
from core.agent_base import LayerType


async def main():
    print("=" * 60)
    print("ARCHAEO-OSIRIS // AJAN EKOSİSTEMİ TEST MODU")
    print("=" * 60)

    eco = ArcheoEcosystem()

    # Canlı besleme callback
    async def on_result(result):
        icon = {
            "akademik": "📚", "müze": "🏛️", "saha": "⛏️",
            "forum": "💬", "sembol": "🔷", "görsel": "👁️",
            "antikacı": "🏺", "medya": "🎬",
        }.get(result.layer.value, "●")
        relevance_bar = "█" * int(result.relevance_score * 10) + "░" * (10 - int(result.relevance_score * 10))
        fake_label = "⚠️ SAHTE?" if result.fake_probability > 0.4 else "✅"
        print(
            f"\n{icon} [{result.layer.value.upper()}] {result.title[:60]}\n"
            f"   Relevans: [{relevance_bar}] {result.relevance_score:.2f} | "
            f"Güven: {fake_label} ({1-result.fake_probability:.0%})\n"
            f"   🔑 {', '.join(result.keywords[:4])}\n"
            f"   🔗 {result.source_url[:80]}"
        )
        if result.coordinates:
            print(f"   📍 Koordinat: {result.coordinates[0]:.4f}, {result.coordinates[1]:.4f}")

    eco.bus.subscribe(on_result)

    await eco.start()
    print("\n✅ Tüm ajanlar başlatıldı. Ctrl+C ile durdur.\n")

    try:
        while True:
            await asyncio.sleep(30)
            status = eco.status_report()
            print(f"\n{'─'*50}")
            print(f"📊 DURUM | Toplam Sonuç: {status['total_results']}")
            for a in status['agents']:
                print(f"   {a['name']}: {a['status']} | "
                      f"Bulunan: {a['results_count']} | "
                      f"Kaynak: {a['sources_discovered']}")
            print(f"{'─'*50}")
    except KeyboardInterrupt:
        print("\n\n⏹ Durduruluyor...")
        await eco.stop()
        print("Ekosistem kapatıldı.")


if __name__ == "__main__":
    asyncio.run(main())
