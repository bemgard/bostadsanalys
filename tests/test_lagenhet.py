"""
Testar skuldjusterat pris för en lägenhet.
Kör: python tests/test_lagenhet.py
Inga API-anrop och ingen data behövs.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bedomning import skuld_per_kvm_bostadsratt  # noqa: E402
from lagenhet import per_kvm, skuldjusterat_pris  # noqa: E402


def data(lang, kort, bostadsyta, foreningens):
    return {
        "skulder_kreditinstitut_langfristiga": {"varde": lang, "sida": 1},
        "skulder_kreditinstitut_kortfristiga": {"varde": kort, "sida": 1},
        "bostadsyta_kvm": {"varde": bostadsyta, "sida": 1},
        "total_yta_kvm": {"varde": 99_999, "sida": 1},  # ska INTE användas
        "skuldsattning_per_kvm_bostadsratt": {"varde": foreningens, "sida": 1},
        "lan": [],
    }


def skuld_per_kvm(*argument):
    return skuld_per_kvm_bostadsratt(data(*argument))[0]

FALL = [
    # (beskrivning, funktion, argument, förväntat)
    ("vanligt fall", skuldjusterat_pris, (5_000_000, 50, 10_000), 5_500_000),
    ("skuldfri förening", skuldjusterat_pris, (5_000_000, 50, 0), 5_000_000),
    ("halva kvadratmeter", skuldjusterat_pris, (5_995_000, 59.5, 5256), 6_307_732),
    ("belåning saknas", skuldjusterat_pris, (5_000_000, 50, None), None),
    ("pris saknas", skuldjusterat_pris, (None, 50, 10_000), None),
    ("kvm saknas", skuldjusterat_pris, (5_000_000, None, 10_000), None),
    ("kvm är noll", skuldjusterat_pris, (5_000_000, 0, 10_000), None),
    ("skuld/kvm: egen uträkning på bostadsrättsyta", skuld_per_kvm, (8_000_000, 2_000_000, 1000, 9000), 10_000),
    ("skuld/kvm: indata saknas, föreningens siffra", skuld_per_kvm, (8_000_000, 2_000_000, None, 9000), 9000),
    ("skuld/kvm: allt saknas", skuld_per_kvm, (None, None, None, None), None),
    ("skuldfri förening (skuld 0)", skuld_per_kvm, (0, 0, 1000, None), 0),
    ("per kvm", per_kvm, (5_500_000, 50), 110_000),
    ("per kvm, belopp saknas", per_kvm, (None, 50), None),
]

godkanda = 0
for beskrivning, funktion, argument, forvantat in FALL:
    fick = funktion(*argument)
    if fick == forvantat:
        godkanda += 1
        print(f"  ✅ {beskrivning}")
    else:
        print(f"  ❌ {beskrivning}: fick {fick}, väntade {forvantat}")

print(f"\n{godkanda}/{len(FALL)} godkända")
sys.exit(0 if godkanda == len(FALL) else 1)
