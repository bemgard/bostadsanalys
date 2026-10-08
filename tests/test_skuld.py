"""
Testar hur total skuld till kreditinstitut räknas när en del (lång- eller kortfristig) saknas.
Kör: python tests/test_skuld.py
Inga API-anrop och ingen data behövs.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bedomning import total_skuld  # noqa: E402


def data(lang, kort, lan):
    return {
        "skulder_kreditinstitut_langfristiga": {"varde": lang, "sida": 1},
        "skulder_kreditinstitut_kortfristiga": {"varde": kort, "sida": 1},
        "lan": [{"belopp": b} for b in lan],
    }


FALL = [
    # (beskrivning, data, förväntad total skuld)
    ("båda delarna finns", data(8_000_000, 2_000_000, [10_000_000]), 10_000_000),
    ("båda finns, lånenoten spelar ingen roll", data(8_000_000, 2_000_000, []), 10_000_000),
    ("kortfristig saknas, lånenoten bekräftar (Smedjan)", data(15_000_000, None, [15_000_000]), 15_000_000),
    ("långfristig saknas, flera lån bekräftar", data(None, 10_350_000, [6_000_000, 4_350_000]), 10_350_000),
    ("kortfristig saknas, lånenoten summerar annorlunda", data(15_000_000, None, [12_000_000]), None),
    ("kortfristig saknas, ingen lånenot", data(15_000_000, None, []), None),
    ("kortfristig saknas, lån utan belopp", data(15_000_000, None, [15_000_000, None]), None),
    ("båda saknas", data(None, None, [15_000_000]), None),
]

godkanda = 0
for beskrivning, d, forvantat in FALL:
    fick = total_skuld(d)
    if fick == forvantat:
        godkanda += 1
        print(f"  ✅ {beskrivning}")
    else:
        print(f"  ❌ {beskrivning}\n       förväntat: {forvantat}\n       fick:      {fick}")

print(f"\n{godkanda}/{len(FALL)} tester godkända")
sys.exit(0 if godkanda == len(FALL) else 1)
