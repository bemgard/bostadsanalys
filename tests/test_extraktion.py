"""
Jämför extraherad data mot facit, utan API-anrop.
Kör: python tests/test_extraktion.py

Varje fil i tests/facit/<namn>.json jämförs mot data/extracted/<namn>.json.
Facit innehåller bara de fält som kontrollerats för hand. Nytt facit för en
förening = lägg till en ny fil i tests/facit/.
"""

import json
import sys
from pathlib import Path

ROT = Path(__file__).resolve().parent.parent
FACIT_DIR = ROT / "tests" / "facit"
EXTRACTED_DIR = ROT / "data" / "extracted"

# Fält där bara vissa nycklar jämförs (fritext som modellen kan formulera olika
# varje gång utelämnas). För listor jämförs nycklarna per post, och antalet
# poster jämförs alltid.
JAMFOR_NYCKLAR = {
    "planerat_underhall": ["planerat_ar", "uppskattad_kostnad", "sida"],
    "lan": ["belopp", "rantesats_procent", "villkorsandringsdag", "sida"],
    "revisorns_anmarkning": ["varde"],
    "revisorns_upplysning": ["varde", "sida"],
}


def urval(falt, varde):
    """Plocka ut de nycklar som ska jämföras för ett fält och sortera posterna,
    så att ordningen i listan inte spelar roll. Övriga fält jämförs i sin helhet."""
    nycklar = JAMFOR_NYCKLAR.get(falt)
    if nycklar is None:
        return varde
    if isinstance(varde, dict):
        return {k: varde.get(k) for k in nycklar}
    if not isinstance(varde, list):
        return varde
    poster = [{k: post.get(k) for k in nycklar} if isinstance(post, dict) else post for post in varde]
    # Sortera på JSON-texten – fungerar även när värden är null
    return sorted(poster, key=lambda p: json.dumps(p, ensure_ascii=False))


def testa_fil(facitfil: Path) -> tuple[int, int]:
    """Jämför en facit-fil mot motsvarande extraherade fil. Returnerar (godkända, totalt)."""
    print(f"\n{facitfil.stem}")
    facit = json.loads(facitfil.read_text(encoding="utf-8"))

    extraherad_fil = EXTRACTED_DIR / facitfil.name
    if not extraherad_fil.exists():
        print(f"  ❌ Hittar ingen extraherad fil: {extraherad_fil.relative_to(ROT)}")
        return 0, len(facit)
    extraherad = json.loads(extraherad_fil.read_text(encoding="utf-8"))

    godkanda = 0
    for falt, forvantat in facit.items():
        if falt not in extraherad:
            print(f"  ❌ {falt}: saknas i extraherad fil")
            continue
        forvantat = urval(falt, forvantat)
        fick = urval(falt, extraherad[falt])
        if fick == forvantat:
            print(f"  ✅ {falt}")
            godkanda += 1
        else:
            print(f"  ❌ {falt}")
            print(f"       förväntat: {json.dumps(forvantat, ensure_ascii=False)}")
            print(f"       fick:      {json.dumps(fick, ensure_ascii=False)}")
    return godkanda, len(facit)


def main():
    facitfiler = sorted(FACIT_DIR.glob("*.json"))
    if not facitfiler:
        sys.exit(f"Inga facit-filer i {FACIT_DIR.relative_to(ROT)}")

    totalt_godkanda = totalt = 0
    for facitfil in facitfiler:
        g, t = testa_fil(facitfil)
        totalt_godkanda += g
        totalt += t

    print(f"\n{totalt_godkanda}/{totalt} fält stämmer")
    # Exitkod 1 vid fel, så att testet kan användas i skript senare
    sys.exit(0 if totalt_godkanda == totalt else 1)


if __name__ == "__main__":
    main()
