"""
Testar raden för avgiftshöjningar: höjningar sorteras efter datum (inte efter vilken
lista de står i), kommande höjningar ger gult/rött, stora senaste höjningar gult.
Kör: python tests/test_avgiftshojningar.py
Inga API-anrop och ingen data behövs.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bedomning import GRON, GUL, ROD, SAKNAS, avgiftshojningar, bedom, sammanlagd_procent  # noqa: E402
from lagenhet import avgift_efter_hojningar  # noqa: E402

IDAG = date(2026, 11, 15)  # historikfönstret (36 mån) börjar 2023-11-15


def data(genomforda, planerade):
    return {
        "rakenskapsar": {"start": {"varde": "2024-01-01"}, "slut": {"varde": "2024-12-31"}},
        "genomforda_avgiftshojningar": [{"procent": p, "fran_datum": d, "sida": 3} for p, d in genomforda],
        "planerade_avgiftshojningar": [{"procent": p, "fran_datum": d, "sida": 3} for p, d in planerade],
    }


def farg(genomforda, planerade):
    return next(r["farg"] for r in bedom(data(genomforda, planerade), IDAG)["nyckeltal"]
                if r["nyckeltal"] == "Avgiftshöjningar")


FALL = [
    # (beskrivning, genomförda, planerade, förväntad färg)
    ("inga höjningar", [], [], GRON),
    ("liten höjning nyligen", [(5, "2024-07-01")], [], GRON),
    ("stora höjningar senaste 3 åren → gul", [(10, "2024-01-01"), (10, "2025-01-01")], [], GUL),
    ("stora höjningar men före fönstret", [(15, "2022-01-01"), (15, "2023-01-01")], [], GRON),
    ("planerad men redan passerad räknas som senaste", [], [(5, "2026-01-01")], GRON),
    ("kommande liten höjning → gul", [], [(4.5, "2027-01-01")], GUL),
    ("kommande höjning ≥ 10 % → röd", [], [(10, "2027-01-01")], ROD),
    ("två kommande som tillsammans ≥ 10 % → röd", [], [(5, "2027-01-01"), (5, "2028-01-01")], ROD),
    ("'genomförd' med datum efter idag räknas som kommande", [(12, "2027-03-01")], [], ROD),
    ("planerad utan datum → gul (kan redan gälla)", [], [(10, None)], GUL),
    ("planerad utan storlek → gul", [], [(None, "2027-01-01")], GUL),
    ("genomförd utan datum antas vid räkenskapsårets slut", [(25, None)], [], GUL),
]

godkanda = 0
for beskrivning, genomforda, planerade, forvantat in FALL:
    fick = farg(genomforda, planerade)
    if fick == forvantat:
        godkanda += 1
        print(f"  ✅ {beskrivning}")
    else:
        print(f"  ❌ {beskrivning}: fick {fick}, väntade {forvantat}")

# Övriga kontroller: (beskrivning, fick, väntat)
ovriga = [
    ("ränta-på-ränta: 10 % + 10 % = 21 %", round(sammanlagd_procent([10, 10]), 6), 21.0),
    ("äldre extraktion utan fälten → saknas",
     next(r["farg"] for r in bedom({"rakenskapsar": data([], [])["rakenskapsar"]}, IDAG)["nyckeltal"]
          if r["nyckeltal"] == "Avgiftshöjningar"), SAKNAS),
    ("kommande sammanlagt", round(avgiftshojningar(data([], [(5, "2027-01-01"), (5, "2028-01-01")]), IDAG)
                                  ["kommande_procent"], 6), 10.25),
    ("avgift efter höjningar", avgift_efter_hojningar(4000, 10.25), 4410),
    ("avgift utan höjningsuppgift", avgift_efter_hojningar(4000, None), None),
    ("avgift saknas", avgift_efter_hojningar(None, 5), None),
]
for beskrivning, fick, vantat in ovriga:
    if fick == vantat:
        godkanda += 1
        print(f"  ✅ {beskrivning}")
    else:
        print(f"  ❌ {beskrivning}: fick {fick}, väntade {vantat}")

totalt = len(FALL) + len(ovriga)
print(f"\n{godkanda}/{totalt} godkända")
sys.exit(0 if godkanda == totalt else 1)
