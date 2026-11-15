"""
Testar utslaget (utslag.py): stoppfaktorer, viktad poäng, reglerna för röda tunga
kriterier, motivering och datakvalitet.
Kör: python tests/test_utslag.py
Inga API-anrop och ingen data behövs.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import utslag as u  # noqa: E402

TUNGA = ["Belåning per kvm", "Sparande per kvm", "Räntebindning", "Avgiftshöjningar", "Renoveringar",
         "Byggdelar", "Grundläggning"]
LATTA = ["Räntekänslighet", "Avgift per kvm", "Energikostnad per kvm", "Föreningens storlek", "Tomträtt",
         "Rapportens ålder", "Äkta förening", "Revisorn"]


def rader(**farger):
    """Alla rader gröna, utom de som anges: rader(Sparande_per_kvm="röd")."""
    andrade = {namn.replace("_", " "): farg for namn, farg in farger.items()}
    return [{"nyckeltal": n, "farg": andrade.get(n, "grön"), "vart_varde": "x", "raknas_i_utslag": True}
            for n in TUNGA + LATTA]


def bedom(r, varningar=(), vantad=0.0):
    return u.bedom_utslag(r, list(varningar), vantad)


alla_gula = rader(**{n.replace(" ", "_"): "gul" for n in TUNGA + LATTA})
FALL = [
    # (beskrivning, fick, väntat)
    ("allt grönt → 100 och GÅ VIDARE", (bedom(rader())["poang"], bedom(rader())["utslag"]), (100, "GÅ VIDARE")),
    ("allt gult → 50 och AVVAKTA", (bedom(alla_gula)["poang"], bedom(alla_gula)["utslag"]), (50, "AVVAKTA")),
    ("tung röd väger mer än lätt röd",
     bedom(rader(Sparande_per_kvm="röd"))["poang"] < bedom(rader(Energikostnad_per_kvm="röd"))["poang"], True),
    ("en röd tung → högst AVVAKTA trots hög poäng", bedom(rader(Sparande_per_kvm="röd"))["utslag"], "AVVAKTA"),
    ("motiveringen säger varför den inte blir GÅ VIDARE",
     "kan inte bli GÅ VIDARE" in bedom(rader(Sparande_per_kvm="röd"))["motivering"], True),
    ("två röda tunga → SORTERA BORT",
     bedom(rader(Sparande_per_kvm="röd", Belåning_per_kvm="röd"))["utslag"], "SORTERA BORT"),
    ("en röd lätt → kan bli GÅ VIDARE", bedom(rader(Energikostnad_per_kvm="röd"))["utslag"], "GÅ VIDARE"),
    ("stopp: oäkta förening", bedom(rader(Äkta_förening="röd"))["utslag"], "SORTERA BORT"),
    ("stopp: grundproblem", bedom(rader(Grundläggning="röd"))["stoppfaktorer"],
     ["planerade eller pågående problem med grunden"]),
    ("stopp: väntad avgiftshöjning ≥ 20 %", bedom(rader(), vantad=25.0)["utslag"], "SORTERA BORT"),
    ("ingen stopp vid 19 %", bedom(rader(), vantad=19.0)["stoppfaktorer"], []),
    ("största riskerna: röda före gula, tunga före lätta",
     u.risker(rader(Energikostnad_per_kvm="röd", Sparande_per_kvm="gul", Belåning_per_kvm="röd")),
     ["belåning per kvm x", "energikostnad per kvm x", "sparande per kvm x"]),
    ("datakvalitet säker", bedom(rader())["datakvalitet"], "Säker"),
    ("datakvalitet osäker när ett tungt nyckeltal saknas", bedom(rader(Sparande_per_kvm="saknas"))["datakvalitet"], "Osäker"),
    ("datakvalitet säker när ett lätt saknas", bedom(rader(Tomträtt="saknas"))["datakvalitet"], "Säker"),
    ("datakvalitet osäker vid två varningar", bedom(rader(), varningar=["a", "b"])["datakvalitet"], "Osäker"),
    ("rader som inte räknas påverkar inte poängen",
     u.poang(rader() + [{"nyckeltal": "Byggår", "farg": "röd", "raknas_i_utslag": False}]), 100),
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
