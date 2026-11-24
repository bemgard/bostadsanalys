"""
Testar att köparprofilen följer med genom bedömningen (bedomning.bedom): rätt profil och
horisont i resultatet, horisonten påverkar renoveringsraden, och okänd profil ger fel.
Kör: python tests/test_profil.py
Inga API-anrop och ingen data behövs.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bedomning as b  # noqa: E402
import kriterier as k  # noqa: E402

IDAG = date(2026, 11, 15)
# Minimal förening: ett planerat stambyte 2034 (10 år fram) som bara en lång horisont fångar.
DATA = {
    "rakenskapsar": {"slut": {"varde": "2024-12-31"}},
    "planerat_underhall": [{"atgard": "Stambyte", "planerat_ar": "2034"}],
}

godkanda = totalt = 0


def kontrollera(namn, fick, forvantat):
    global godkanda, totalt
    totalt += 1
    ok = fick == forvantat
    godkanda += ok
    print(f"  {'✅' if ok else '❌'} {namn}" + ("" if ok else f"\n       fick {fick!r}, väntade {forvantat!r}"))


# Utan profil = standard (par)
r = b.bedom(DATA, IDAG)
kontrollera("utan profil → par", r["koparprofil"], "par")
kontrollera("par-horisont = 5", r["renoveringshorisont_ar"], 5)

# Varje profil följer med till resultatet med rätt horisont
for pid, profil in k.KOPARPROFILER.items():
    r = b.bedom(DATA, IDAG, pid)
    kontrollera(f"{pid}: koparprofil i resultatet", r["koparprofil"], pid)
    kontrollera(f"{pid}: horisont följer profilen", r["renoveringshorisont_ar"], profil["renoveringshorisont_ar"])


# Horisonten påverkar renoveringsraden: familj (15 år) fångar stambytet 2034, par (5 år) inte
def renov_antal(pid):
    r = b.bedom(DATA, IDAG, pid)
    return next(x["varde_tal"] for x in r["nyckeltal"] if x["nyckeltal"] == "Renoveringar")


kontrollera("par: stambyte 2034 utanför 5-årshorisonten", renov_antal("par"), 0)
kontrollera("familj: stambyte 2034 inom 15-årshorisonten", renov_antal("familj"), 1)

# Okänd profil → ValueError (samma skydd som los_profil ger)
try:
    b.bedom(DATA, IDAG, "pensionär")
    kontrollera("okänd profil kastar fel", False, True)
except ValueError:
    kontrollera("okänd profil kastar fel", True, True)

print(f"\n{godkanda}/{totalt} tester godkända")
sys.exit(0 if godkanda == totalt else 1)
