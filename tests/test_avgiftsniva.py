"""
Testar att nyckeltal som bygger på årsavgifterna räknas på dagens avgiftsnivå:
höjningar mitt i räkenskapsåret räknas upp till helår, höjningar efter räkenskapsåret
(senast idag) läggs till, framtida höjningar räknas inte.
Kör: python tests/test_avgiftsniva.py
Inga API-anrop och ingen data behövs.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bedomning import avgift_per_kvm, avgiftsniva_faktor, bedom, rantekanslighet_procent  # noqa: E402

IDAG = date(2026, 11, 15)


def data(genomforda=(), planerade=(), start="2025-01-01", slut="2025-12-31"):
    return {
        "rakenskapsar": {"start": {"varde": start}, "slut": {"varde": slut}},
        "arsavgifter_bostader": {"varde": 1_000_000, "sida": 1},
        "arsavgift_per_kvm": {"varde": 500, "sida": 1},
        "bostadsyta_kvm": {"varde": 2000, "sida": 1},
        "skulder_kreditinstitut_langfristiga": {"varde": 10_000_000, "sida": 1},
        "skulder_kreditinstitut_kortfristiga": {"varde": 0, "sida": 1},
        "genomforda_avgiftshojningar": [{"procent": p, "fran_datum": d, "sida": 2} for p, d in genomforda],
        "planerade_avgiftshojningar": [{"procent": p, "fran_datum": d, "sida": 2} for p, d in planerade],
    }


def faktor(d):
    return round(avgiftsniva_faktor(d, IDAG)[0], 4)


FALL = [
    # (beskrivning, fick, väntat)
    ("inga höjningar → 1", faktor(data()), 1.0),
    ("höjning före räkenskapsåret påverkar inte", faktor(data([(10, "2024-06-01")])), 1.0),
    ("höjning första dagen i året finns redan med helt", faktor(data([(10, "2025-01-01")])), 1.0),
    # 10 % från 1 juli: 181 dagar på nivå 1,0 och 184 på 1,1 → snitt 1,0504; 1,1 / 1,0504 = 1,0472
    ("höjning mitt i året räknas upp till helår", faktor(data([(10, "2025-07-01")])), 1.0472),
    ("höjning efter året, före idag (Kommendören)",
     faktor(data(planerade=[(28, "2026-05-01"), (22, "2026-09-01")])), round(1.28 * 1.22, 4)),
    ("framtida höjning räknas inte", faktor(data(planerade=[(10, "2027-01-01")])), 1.0),
    ("höjning utan datum räknas inte", faktor(data([(10, None)])), 1.0),
    ("samma höjning i båda listorna räknas en gång",
     faktor(data([(10, "2026-03-01")], [(10, "2026-03-01")])), 1.1),
    ("avgift per kvm på dagens nivå", round(avgift_per_kvm(data(planerade=[(25, "2026-01-01")]), IDAG)), 625),
    ("avgift per kvm utan idag = rapportens nivå", round(avgift_per_kvm(data(planerade=[(25, "2026-01-01")]))), 500),
    ("räntekänslighet på dagens nivå", round(rantekanslighet_procent(data(planerade=[(25, "2026-01-01")]), IDAG), 4), 8.0),
]

rad = next(r for r in bedom(data(planerade=[(25, "2026-01-01")]), IDAG)["nyckeltal"] if r["nyckeltal"] == "Avgift per kvm")
FALL += [
    ("raden visar dagens nivå", rad["varde_tal"], 625),
    ("kontrollräkningen görs på rapportens nivå (ingen falsk avvikelse)", rad["avvikelse"], False),
    ("kommentaren förklarar justeringen", "dagens avgiftsnivå" in rad["kommentar"], True),
]

godkanda = 0
for beskrivning, fick, vantat in FALL:
    if fick == vantat:
        godkanda += 1
        print(f"  ✅ {beskrivning}")
    else:
        print(f"  ❌ {beskrivning}: fick {fick}, väntade {vantat}")

print(f"\n{godkanda}/{len(FALL)} godkända")
sys.exit(0 if godkanda == len(FALL) else 1)
