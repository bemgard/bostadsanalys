"""
Rimlighetskontroller av en extraktion: fångar felavläsningar som validera() i
extract_report.py inte ser (den kontrollerar bara att fälten finns och har rätt form).

Kontrollerna ändrar INTE färger eller utslag – de ger varningar om att en siffra bör
kontrolleras i PDF:en. Toleranser i kriterier.py.
"""

from datetime import date

import kriterier as k

# Fält vars värde ska vara ett tal (inte text som "1 234 567")
NUMERISKA = [
    "skulder_kreditinstitut_langfristiga", "skulder_kreditinstitut_kortfristiga",
    "bostadsyta_kvm", "lokalyta_kvm", "total_yta_kvm", "antal_bostadsratter", "antal_hyresratter",
    "antal_lagenheter_totalt", "byggnadsar", "arsresultat", "likvida_medel_arets_slut",
    "kassaflode_lopande_verksamhet", "arsavgifter_bostader", "skuldsattning_per_kvm_bostadsratt",
    "skuldsattning_per_kvm_totalyta", "sparande_per_kvm", "rantekanslighet_procent",
    "arsavgift_per_kvm", "energikostnad_per_kvm", "underhallsplan_till_ar",
]
# Fält som aldrig kan vara negativa
EJ_NEGATIVA = [
    "skulder_kreditinstitut_langfristiga", "skulder_kreditinstitut_kortfristiga",
    "bostadsyta_kvm", "lokalyta_kvm", "total_yta_kvm", "arsavgifter_bostader", "likvida_medel_arets_slut",
]


def _v(data, falt):
    post = data.get(falt)
    return post.get("varde") if isinstance(post, dict) else None


def _tal(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _avviker(a, b, tolerans):
    """True om a och b skiljer sig mer än tolerans procent (av det största)."""
    storst = max(abs(a), abs(b))
    return storst > 0 and abs(a - b) / storst * 100 > tolerans


def _kr(x):
    return f"{x:,.0f}".replace(",", " ")


def typer_och_tecken(data):
    varningar = []
    for falt in NUMERISKA:
        x = _v(data, falt)
        if x is not None and not _tal(x):
            varningar.append(f"{falt} är inte ett tal ({x!r}) – kontrollera avläsningen.")
    for falt in EJ_NEGATIVA:
        x = _v(data, falt)
        if _tal(x) and x < 0:
            varningar.append(f"{falt} är negativt ({_kr(x)}) – kan inte stämma.")
    return varningar


def sidhanvisningar(data):
    """Varje avläst värde ska ha ett sidnummer ≥ 1."""
    varningar = []
    for falt, post in data.items():
        if not isinstance(post, dict) or "sida" not in post:
            continue
        sida = post.get("sida")
        if post.get("varde") is not None and post.get("varde") is not False and sida is None:
            varningar.append(f"{falt} saknar sidhänvisning.")
        elif sida is not None and (not isinstance(sida, int) or sida < 1):
            varningar.append(f"{falt} har ogiltigt sidnummer ({sida!r}).")
    return varningar


def ytor(data):
    """Bostadsrättsyta + lokalyta ska inte överstiga totalytan. Blir summan klart mindre
    utan att det finns hyresrätter (vars yta inte ingår i någon av dem) går ytorna inte ihop."""
    br, lokal, total = _v(data, "bostadsyta_kvm"), _v(data, "lokalyta_kvm"), _v(data, "total_yta_kvm")
    if not (_tal(br) and _tal(total)) or total <= 0:
        return []
    summa = br + (lokal if _tal(lokal) else 0)
    tol = k.RIMLIGHET_TOLERANS_PROCENT
    if summa > total * (1 + tol / 100):
        return [f"Bostadsyta + lokalyta ({_kr(summa)} kvm) är större än totalytan ({_kr(total)} kvm)."]
    hyresratter = _v(data, "antal_hyresratter")
    if summa < total * (1 - tol / 100) and not (_tal(hyresratter) and hyresratter > 0):
        return [f"Bostadsyta + lokalyta ({_kr(summa)} kvm) är mindre än totalytan ({_kr(total)} kvm) "
                "och inga hyresrätter anges – kontrollera ytorna."]
    return []


def lan(data, total_skuld):
    """Lånenotens summa ska stämma med skulderna i balansräkningen, och räntor/datum vara rimliga."""
    varningar = []
    poster = data.get("lan") or []
    belopp = [p.get("belopp") for p in poster]
    if poster and total_skuld is not None and all(_tal(b) for b in belopp):
        summa = sum(belopp)
        if _avviker(summa, total_skuld, k.RIMLIGHET_TOLERANS_PROCENT):
            varningar.append(f"Lånenotens summa ({_kr(summa)} kr) stämmer inte med skulderna i "
                             f"balansräkningen ({_kr(total_skuld)} kr).")
    for p in poster:
        r = p.get("rantesats_procent")
        if r is not None and (not _tal(r) or not 0 <= r <= k.RIMLIGHET_MAX_RANTA_PROCENT):
            varningar.append(f"Orimlig ränta i lånenoten: {r!r} %.")
        d = p.get("villkorsandringsdag")
        if d is not None:
            try:
                date.fromisoformat(d)
            except (TypeError, ValueError):
                varningar.append(f"Villkorsändringsdag går inte att läsa som datum: {d!r}.")
    return varningar


def rakenskapsar(data):
    ar = data.get("rakenskapsar") or {}
    try:
        start = date.fromisoformat((ar.get("start") or {}).get("varde"))
        slut = date.fromisoformat((ar.get("slut") or {}).get("varde"))
    except (TypeError, ValueError):
        return []
    manader = (slut.year - start.year) * 12 + slut.month - start.month + 1
    if not k.RIMLIGHET_RAKENSKAPSAR_MANADER[0] <= manader <= k.RIMLIGHET_RAKENSKAPSAR_MANADER[1]:
        return [f"Räkenskapsåret är {manader} månader ({start} – {slut}) – kontrollera datumen."]
    return []


def kontrollera(data, total_skuld):
    """Alla rimlighetsvarningar för en extraktion, som en lista med texter (tom = inget att anmärka)."""
    return (typer_och_tecken(data) + sidhanvisningar(data) + ytor(data)
            + lan(data, total_skuld) + rakenskapsar(data))
