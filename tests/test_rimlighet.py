"""
Testar rimlighetskontrollerna (rimlighet.py).
Kör: python tests/test_rimlighet.py
Inga API-anrop och ingen data behövs.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import rimlighet  # noqa: E402
from bedomning import sidor  # noqa: E402


def f(varde, sida=1):
    return {"varde": varde, "sida": sida}


def ytdata(br, lokal, total, hyresratter=None):
    return {"bostadsyta_kvm": f(br), "lokalyta_kvm": f(lokal), "total_yta_kvm": f(total),
            "antal_hyresratter": f(hyresratter)}


def ar(start, slut):
    return {"rakenskapsar": {"start": f(start), "slut": f(slut)}}


LAN = [{"belopp": 6_000_000, "rantesats_procent": 3.1, "villkorsandringsdag": "2027-03-01", "sida": 9},
       {"belopp": 4_000_000, "rantesats_procent": 2.4, "villkorsandringsdag": "2028-01-01", "sida": 9}]

FALL = [
    # (beskrivning, funktion, argument, antal förväntade varningar)
    ("ytor går ihop", rimlighet.ytor, (ytdata(2000, 200, 2200),), 0),
    ("ytor inom toleransen", rimlighet.ytor, (ytdata(2000, 200, 2250),), 0),
    ("ytor: summan större än totalytan (Tomten)", rimlighet.ytor, (ytdata(2018, 238, 2128),), 1),
    ("ytor: summan för liten, inga hyresrätter", rimlighet.ytor, (ytdata(1500, 100, 2200),), 1),
    ("ytor: summan för liten men hyresrätter finns", rimlighet.ytor, (ytdata(1500, 100, 2200, 5),), 0),
    ("ytor: totalyta saknas", rimlighet.ytor, (ytdata(2000, 200, None),), 0),
    ("lån stämmer med skulden", rimlighet.lan, ({"lan": LAN}, 10_000_000), 0),
    ("lån stämmer inte med skulden", rimlighet.lan, ({"lan": LAN}, 12_000_000), 1),
    ("lån utan belopp jämförs inte", rimlighet.lan, ({"lan": [{"belopp": None}]}, 12_000_000), 0),
    ("orimlig ränta", rimlighet.lan, ({"lan": [{"belopp": 1, "rantesats_procent": 31}]}, 1), 1),
    ("oläsligt datum", rimlighet.lan, ({"lan": [{"belopp": 1, "villkorsandringsdag": "mars 2027"}]}, 1), 1),
    ("vanligt räkenskapsår", rimlighet.rakenskapsar, (ar("2024-01-01", "2024-12-31"),), 0),
    ("förlängt första år (18 mån)", rimlighet.rakenskapsar, (ar("2023-07-01", "2024-12-31"),), 0),
    ("start efter slut", rimlighet.rakenskapsar, (ar("2025-01-01", "2024-12-31"),), 1),
    ("belopp som text", rimlighet.typer_och_tecken, ({"arsavgifter_bostader": f("1 250 304")},), 1),
    ("negativ skuld", rimlighet.typer_och_tecken, ({"skulder_kreditinstitut_langfristiga": f(-5)},), 1),
    ("negativt årsresultat är ok", rimlighet.typer_och_tecken, ({"arsresultat": f(-500_000)},), 0),
    ("värde utan sida", rimlighet.sidhanvisningar, ({"total_yta_kvm": f(2000, None)},), 1),
    ("null utan sida är ok", rimlighet.sidhanvisningar, ({"total_yta_kvm": f(None, None)},), 0),
    ("sida 0 är ogiltig", rimlighet.sidhanvisningar, ({"total_yta_kvm": f(2000, 0)},), 1),
]

godkanda = 0
for beskrivning, funktion, argument, antal in FALL:
    fick = funktion(*argument)
    if len(fick) == antal:
        godkanda += 1
        print(f"  ✅ {beskrivning}")
    else:
        print(f"  ❌ {beskrivning}: väntade {antal} varningar, fick {fick}")

# Sidhänvisningar samlas även ur listor och delobjekt
data = {"lan": LAN, "rakenskapsar": {"start": f("2024-01-01", 2), "slut": f("2024-12-31", 2)},
        "total_yta_kvm": f(2000, 4)}
fick = sidor(data, ("lan", "rakenskapsar", "total_yta_kvm", "finns_inte"))
totalt = len(FALL) + 1
if fick == [2, 4, 9]:
    godkanda += 1
    print("  ✅ sidor ur listor och delobjekt")
else:
    print(f"  ❌ sidor ur listor och delobjekt: fick {fick}")

print(f"\n{godkanda}/{totalt} godkända")
sys.exit(0 if godkanda == totalt else 1)
