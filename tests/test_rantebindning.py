"""
Testar räntebindningsraden: väntad avgiftshöjning när lån som villkorsändras inom
horisonten (räknad från idag) får marknadsräntan i kriterier.py. Lån vars
villkorsändringsdag passerat räknas som redan omförhandlade.
Kör: python tests/test_rantebindning.py
Inga API-anrop och ingen data behövs.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import kriterier as k  # noqa: E402
from bedomning import GRON, GUL, ROD, SAKNAS, bedom, rantebindning  # noqa: E402

k.MARKNADSRANTA_FORENINGSLAN_PROCENT = 3.5  # testerna räknar med 3,5 % oavsett kriterier.py
IDAG = date(2026, 10, 8)  # horisonten är 24 mån från IDAG, alltså t.o.m. 2028-10-08
ARSAVGIFTER = 2_000_000
OMFORHANDLAD = "Lånen har redan omförhandlats – fråga vilka räntor det blev och hur avgiften påverkats."


def data(lan, arsavgifter=ARSAVGIFTER):
    """Minsta möjliga extraktion: räkenskapsår, skulder, årsavgifter och lån."""
    return {
        "rakenskapsar": {"start": {"varde": "2024-01-01"}, "slut": {"varde": "2024-12-31"}},
        "skulder_kreditinstitut_langfristiga": {"varde": sum(b for b, _, _ in lan), "sida": 1},
        "skulder_kreditinstitut_kortfristiga": {"varde": 0, "sida": 1},
        "arsavgifter_bostader": {"varde": arsavgifter, "sida": 1},
        "lan": [{"belopp": b, "rantesats_procent": r, "villkorsandringsdag": d} for b, r, d in lan],
    }


def rad(lan, **kw):
    return next(r for r in bedom(data(lan, **kw), IDAG)["nyckeltal"] if r["nyckeltal"] == "Räntebindning")


FALL = [
    # (beskrivning, lån [(belopp, ränta %, villkorsändringsdag)], förväntad färg, "redan omförhandlad"-text?)
    # 10 Mkr från 0,72 % till 3,5 % = 278 000 kr/år = 13,9 % av 2 Mkr i årsavgifter
    ("låg ränta väntar → röd (13,9 %)", [(10_000_000, 0.72, "2026-12-01")], ROD, False),
    ("nära marknadsräntan → grön (2,5 %)", [(10_000_000, 3.0, "2026-12-01")], GRON, False),
    ("måttlig höjning → gul (5 %)", [(10_000_000, 2.5, "2026-12-01")], GUL, False),
    ("ränta över marknadsräntan räknas som 0 → grön", [(10_000_000, 4.0, "2026-12-01")], GRON, False),
    ("låg ränta redan omförhandlad → gul", [(10_000_000, 0.72, "2026-03-01")], GUL, True),
    ("blandat: låg ränta passerad + låg ränta kvar (6,75 %) → gul, inte omförhandlad-text",
     [(5_000_000, 0.70, "2026-03-01"), (5_000_000, 0.80, "2026-12-01")], GUL, False),
    ("dag = idag räknas som ännu inte villkorsändrad → röd", [(10_000_000, 0.72, "2026-10-08")], ROD, False),
    ("lån utan villkorsändringsdag räknas som ej omförhandlat → röd", [(10_000_000, 0.72, None)], ROD, False),
    ("efter rapportens horisont men inom 24 mån från idag → röd", [(10_000_000, 0.72, "2027-06-01")], ROD, False),
    ("precis på horisonten (idag + 24 mån) → röd", [(10_000_000, 0.72, "2028-10-08")], ROD, False),
    ("efter horisonten från idag → grön", [(10_000_000, 0.72, "2028-10-09")], GRON, False),
    ("ränta saknas på kommande lån → gul", [(10_000_000, None, "2026-12-01")], GUL, False),
]

godkanda = totalt = 0
for beskrivning, lan, farg, omforhandlad in FALL:
    r = rad(lan)
    fick = (r["farg"], r["kommentar"] == OMFORHANDLAD)
    totalt += 1
    if fick == (farg, omforhandlad):
        godkanda += 1
        print(f"  ✅ {beskrivning}")
    else:
        print(f"  ❌ {beskrivning}\n       förväntat: {(farg, omforhandlad)}\n       fick:      {fick}  ({r['kommentar']})")

ovriga = [
    ("väntad avgiftshöjning räknas rätt (13,9 %)",
     round(rantebindning(data([(10_000_000, 0.72, "2026-12-01")]), IDAG)["vantad_avgiftshojning"], 6), 13.9),
    ("årsavgifter saknas → gul", rad([(10_000_000, 0.72, "2026-12-01")], arsavgifter=None)["farg"], GUL),
    ("skuldfri förening → grön",
     next(r["farg"] for r in bedom({**data([]), "skulder_kreditinstitut_langfristiga": {"varde": 0, "sida": 1}},
                                   IDAG)["nyckeltal"] if r["nyckeltal"] == "Räntebindning"), GRON),
    ("skuld men inga lån → saknas",
     next(r["farg"] for r in bedom({**data([]), "skulder_kreditinstitut_langfristiga": {"varde": 5, "sida": 1}},
                                   IDAG)["nyckeltal"] if r["nyckeltal"] == "Räntebindning"), SAKNAS),
]
for beskrivning, fick, vantat in ovriga:
    totalt += 1
    if fick == vantat:
        godkanda += 1
        print(f"  ✅ {beskrivning}")
    else:
        print(f"  ❌ {beskrivning}: fick {fick}, väntade {vantat}")

print(f"\n{godkanda}/{totalt} tester godkända")
sys.exit(0 if godkanda == totalt else 1)
