"""
Testar räntebindningsraden: lån vars villkorsändringsdag passerat (före --idag) räknas
som redan omförhandlade, och röd-regeln gäller bara lån som ännu inte villkorsändrats.
Kör: python tests/test_rantebindning.py
Inga API-anrop och ingen data behövs.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bedomning import GUL, ROD, bedom  # noqa: E402

IDAG = date(2026, 10, 8)  # horisonten (24 mån från 2024-12-31) slutar 2026-12-31
OMFORHANDLAD = "Lånen har redan omförhandlats – fråga vilka räntor det blev och hur avgiften påverkats."


def data(lan):
    """Minsta möjliga extraktion: räkenskapsår, skulder och lån (belopp, ränta, villkorsändringsdag)."""
    return {
        "rakenskapsar": {"start": {"varde": "2024-01-01"}, "slut": {"varde": "2024-12-31"}},
        "skulder_kreditinstitut_langfristiga": {"varde": sum(b for b, _, _ in lan), "sida": 1},
        "skulder_kreditinstitut_kortfristiga": {"varde": 0, "sida": 1},
        "lan": [{"belopp": b, "rantesats_procent": r, "villkorsandringsdag": d} for b, r, d in lan],
    }


def rad(lan):
    return next(r for r in bedom(data(lan), IDAG)["nyckeltal"] if r["nyckeltal"] == "Räntebindning")


FALL = [
    # (beskrivning, lån [(belopp, ränta %, villkorsändringsdag)], förväntad färg, redan omförhandlad?)
    ("alla passerade: låg ränta redan omförhandlad → gul",
     [(15_000_000, 0.72, "2026-03-01")], GUL, True),
    ("inga passerade: låg ränta väntar → röd",
     [(15_000_000, 0.72, "2026-12-01")], ROD, False),
    ("blandat: >40 % med låg ränta väntar fortfarande → röd",
     [(5_000_000, 0.70, "2026-03-01"), (5_000_000, 0.80, "2026-12-01")], ROD, False),
    ("blandat: låg ränta passerad, bara 30 % kvar → gul, redan omförhandlad",
     [(7_000_000, 0.70, "2026-03-01"), (3_000_000, 0.80, "2026-12-01")], GUL, True),
    ("inga passerade, normal ränta → gul (stor andel men inte låg ränta)",
     [(10_000_000, 4.00, "2026-12-31")], GUL, False),
    ("passerad dag = idag räknas som ännu inte villkorsändrad → röd",
     [(10_000_000, 0.72, "2026-10-08")], ROD, False),
    ("lån utan villkorsändringsdag räknas som ej omförhandlat → röd",
     [(10_000_000, 0.72, None)], ROD, False),
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

print(f"\n{godkanda}/{totalt} tester godkända")
sys.exit(0 if godkanda == totalt else 1)
