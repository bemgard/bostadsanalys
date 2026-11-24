"""
Testar hur åtgärdstexter matchas mot byggdelar (stambyte, tak, fasad, el) i bedomning.py.
Kör: python tests/test_byggdelar.py
Inga API-anrop och ingen data behövs.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bedomning import byggdelar, byggdelar_i_text, farg_byggdel, senaste_ar, stora_renoveringar  # noqa: E402

FALL = [
    # (åtgärdstext, förväntade byggdelar)
    ("Elstambyte", {"el"}),
    ("Elstamsbyte och nya elcentraler", {"el"}),
    ("Rörstambyte - Omfattar badrum", {"stambyte"}),
    ("Stambyte kök - Exkl. kallvatten", {"stambyte"}),
    ("Relining av avloppsstammar", {"stambyte"}),
    ("Spolning avloppsstammar/avloppsrör", set()),
    ("Stamspolning - Översyn av stammar", set()),
    ("Omläggning av tak", {"tak"}),
    ("Byte av yttertak", {"tak"}),
    ("Reparation och målning tak", set()),
    ("Oförutsedda renoveringar takterrasser - D-huset", set()),
    ("Oförutsedda renoveringar takterasser - C-huset", set()),
    ("Fasadrenovering - innergården", {"fasad"}),
    ("Omputsning av fasad - Fasad mot gata målad och klotterskyddad.", {"fasad"}),
    ("Balkong, besiktning", set()),
    ("Ny kontakt i trapphus", set()),
    ("Byte av radiatorer i en lägenhet", set()),
    # Från Skålens årsredovisning
    ("Byte av el-central - Utfört", {"el"}),
    ("Stambyte av VVS och EL - Utfört", {"stambyte", "el"}),
    ("Korrigeringar i stambytet - Utfört", set()),
    # "el" bara som helt ord
    ("Byte av panel i trapphus", set()),
    ("Ny kabel till tvättstugan", set()),
]

ARTAL = [("2002", 2002), ("2019-2020", 2020), ("2008-2010", 2010), ("", None), ("okänt", None)]

godkanda = totalt = 0


def kontrollera(namn, fick, forvantat):
    global godkanda, totalt
    totalt += 1
    if fick == forvantat:
        godkanda += 1
        print(f"  ✅ {namn}")
    else:
        print(f"  ❌ {namn}\n       förväntat: {forvantat}\n       fick:      {fick}")


print("Byggdel per åtgärdstext")
for text, forvantat in FALL:
    kontrollera(f"{text!r} → {sorted(forvantat) or 'ingen'}", byggdelar_i_text(text), forvantat)

print("\nSenaste årtal")
for text, forvantat in ARTAL:
    kontrollera(f"{text!r} → {forvantat}", senaste_ar(text), forvantat)

print("\nSenaste åtgärd per byggdel")
data = {
    "rakenskapsar": {"slut": {"varde": "2024-12-31"}},
    "utfort_underhall": [
        {"atgard": "Elstambyte", "ar": "1995"},
        {"atgard": "Stambyte kök", "ar": "1978"},
        {"atgard": "Rörstambyte - Omfattar badrum", "ar": "2002"},
        {"atgard": "Fasadrenovering", "ar": "2019-2020"},
    ],
    "planerat_underhall": [{"atgard": "Takbyte", "planerat_ar": "2027"}],
}
resultat = byggdelar(data, date(2026, 10, 8))
kontrollera("stambyte: senaste är 2002, inte 1978 och inte elstambytet 1995", resultat["stambyte"]["ar"], 2002)
kontrollera("el: 1995 från Elstambyte", resultat["el"]["ar"], 1995)
kontrollera("fasad: 2020 ur intervallet 2019-2020", resultat["fasad"]["ar"], 2020)
kontrollera("tak: okänt (inget utfört), men planerat", (resultat["tak"]["ar"], resultat["tak"]["planerad"]), (None, True))
kontrollera("saknat fält (äldre extraktion) → None", byggdelar({}, date(2026, 10, 8)), None)

print("\nRelining åldras snabbare än ett fullt stambyte")


def stam(*atgarder):
    """(typ, färg) för stammarna med utförda åtgärder [(text, år), ...], bedömt 2026-10-08."""
    d = {"rakenskapsar": {"slut": {"varde": "2024-12-31"}}, "planerat_underhall": [],
         "utfort_underhall": [{"atgard": t, "ar": a} for t, a in atgarder]}
    info = byggdelar(d, date(2026, 10, 8))["stambyte"]
    return info["typ"], farg_byggdel("stambyte", info)


kontrollera("relining 2000 (26 år) → gul", stam(("Relining av avloppsstammar", "2000")), ("relining", "gul"))
kontrollera("fullt stambyte 2000 (26 år) → grön", stam(("Stambyte vatten och avlopp", "2000")), ("stambyte", "grön"))
kontrollera("relining 1990 (36 år), inget planerat → röd", stam(("Relining huvudledning", "1990")), ("relining", "röd"))
kontrollera("fullt stambyte 1990 (36 år) → grön", stam(("Rörstambyte", "1990")), ("stambyte", "grön"))
kontrollera("relining 1995 + stambyte 2015 → senaste är stambytet",
            stam(("Relining", "1995"), ("Stambyte", "2015")), ("stambyte", "grön"))

print("\nRenoveringshorisont (köparprofil)")
dh = {"rakenskapsar": {"slut": {"varde": "2024-12-31"}},
      "planerat_underhall": [{"atgard": "Stambyte", "planerat_ar": "2034"}]}
kontrollera("standard (5 år): stambyte 2034 räknas inte", stora_renoveringar(dh), [])
kontrollera("5 år: stambyte 2034 räknas inte", stora_renoveringar(dh, 5), [])
kontrollera("familj (15 år): stambyte 2034 räknas", stora_renoveringar(dh, 15), ["Stambyte"])

print(f"\n{godkanda}/{totalt} tester godkända")
sys.exit(0 if godkanda == totalt else 1)
