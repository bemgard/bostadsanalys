"""
Steg 3: Bedöm en förening utifrån extraherad data och gränserna i kriterier.py.
Kör: python bedomning.py data/extracted/<namn>.json [--idag ÅÅÅÅ-MM-DD]
Resultatet sparas i data/bedomning/<namn>.json
"""

import argparse
import calendar
import json
import re
import sys
from datetime import date
from pathlib import Path

import kriterier as k
import rimlighet

GRON, GUL, ROD, SAKNAS = "grön", "gul", "röd", "saknas"
INFO = "info"  # informationsrad utan färg – påverkar inte utslaget
ALDRE_EXTRAKTION = "Extraktionen är gjord med en äldre version – kör om med --force."

# Vilka extraktionsfält varje nyckeltal bygger på. Saknas ett fält helt i JSON-filen
# är extraktionen gjord med en äldre version (inte att uppgiften saknas i årsredovisningen).
BEROENDEN = {
    "Belåning per kvm": ("skulder_kreditinstitut_langfristiga", "skulder_kreditinstitut_kortfristiga", "bostadsyta_kvm"),
    "Räntekänslighet": ("skulder_kreditinstitut_langfristiga", "skulder_kreditinstitut_kortfristiga", "arsavgifter_bostader"),
    "Sparande per kvm": ("sparande_per_kvm",),
    "Avgift per kvm": ("arsavgifter_bostader", "bostadsyta_kvm"),
    "Avgiftshöjningar": ("genomforda_avgiftshojningar", "planerade_avgiftshojningar", "rakenskapsar"),
    "Energikostnad per kvm": ("energikostnad_per_kvm",),
    "Räntebindning": ("lan", "rakenskapsar"),
    "Renoveringar": ("planerat_underhall",),
    "Byggdelar": ("utfort_underhall",),
    "Grundläggning": ("grundlaggning",),
    "Rapportens ålder": ("rakenskapsar",),
    "Tomträtt": ("tomtratt",),
    "Äkta förening": ("akta_forening",),
    "Föreningens storlek": ("antal_bostadsratter", "antal_lagenheter_totalt"),
    "Byggår": ("byggnadsar",),
    "Revisorn": ("revisorns_anmarkning", "revisorns_upplysning"),
}
OUTPUT_DIR = Path("data/bedomning")


# --- Hjälpfunktioner ---------------------------------------------------------

def v(data, falt):
    """Hämta 'varde' för ett {varde, sida}-fält, eller None om det saknas."""
    post = data.get(falt)
    return post.get("varde") if isinstance(post, dict) else None


def till_datum(text):
    """ÅÅÅÅ-MM-DD -> date, eller None om texten saknas/är ogiltig."""
    try:
        return date.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def rakenskapsar_slut(data):
    return till_datum((data.get("rakenskapsar") or {}).get("slut", {}).get("varde"))


def lagg_till_manader(d, manader):
    """Datum + antal månader (t.ex. 31 aug + 6 mån = 28/29 feb)."""
    ar, man = divmod(d.month - 1 + manader, 12)
    ar, man = d.year + ar, man + 1
    return date(ar, man, min(d.day, calendar.monthrange(ar, man)[1]))


def manader_mellan(fran, till):
    """Antal hela månader från ett datum till ett annat."""
    manader = (till.year - fran.year) * 12 + till.month - fran.month
    return manader - 1 if till.day < fran.day else manader


def tal(x, decimaler=0, enhet=""):
    """Formatera ett tal på svenska: 5 256,4 kr/kvm."""
    if x is None:
        return "–"
    text = f"{x:,.{decimaler}f}".replace(",", " ").replace(".", ",")
    return f"{text} {enhet}".strip()


def avrunda(x, decimaler=0):
    """Avrunda som i det formaterade värdet (heltal om 0 decimaler). None förblir None."""
    if x is None:
        return None
    return round(x) if decimaler == 0 else round(x, decimaler)


# --- Uträkningar (en per nyckeltal) ------------------------------------------
# Alla returnerar None om något indatavärde saknas.

def total_skuld_med_forklaring(data):
    """(total skuld till kreditinstitut, förklaring). Saknas den ena delen (lång- eller
    kortfristig) räknas den som 0 – men BARA om summan av lånen i lånenoten är exakt
    lika med den del som finns. Annars (None, förklaring)."""
    lang = v(data, "skulder_kreditinstitut_langfristiga")
    kort = v(data, "skulder_kreditinstitut_kortfristiga")
    if lang is not None and kort is not None:
        return lang + kort, "långfristiga + kortfristiga skulder"
    if lang is None and kort is None:
        return None, "skulder till kreditinstitut saknas"
    kand, del_ = (lang, "långfristiga") if lang is not None else (kort, "kortfristiga")
    lan = data.get("lan") or []
    if lan and all(l.get("belopp") is not None for l in lan) and sum(l["belopp"] for l in lan) == kand:
        return kand, f"bara {del_} skulder redovisas; lånenoten bekräftar summan"
    return None, f"bara {del_} skulder redovisas och lånenoten bekräftar inte summan"


def total_skuld(data):
    return total_skuld_med_forklaring(data)[0]


def belaning_per_kvm(data):
    """Belåning per kvm BOSTADSRÄTTSYTA – samma mått som skuldjusterat pris bygger på."""
    return skuld_per_kvm_bostadsratt(data)[0]


def skuld_per_kvm_bostadsratt(data):
    """(skuld per kvm bostadsrättsyta, källa). Det är bostadsrättsinnehavarna som bär
    föreningens skuld, så det här är måttet för en köpares skuldandel (lokaler och
    hyresrätter räknas inte in i ytan). Egen uträkning i första hand; saknas indata
    används föreningens redovisade siffra. (None, förklaring) om båda saknas."""
    skuld, yta = total_skuld(data), v(data, "bostadsyta_kvm")
    if skuld is not None and yta:
        return skuld / yta, "egen uträkning (skuld / bostadsrättsyta)"
    foreningens = v(data, "skuldsattning_per_kvm_bostadsratt")
    if foreningens is not None:
        return foreningens, "föreningens redovisade siffra"
    return None, "skuld eller bostadsrättsyta saknas"


def rantekanslighet_procent(data):
    skuld, avgifter = total_skuld(data), v(data, "arsavgifter_bostader")
    if skuld is None or not avgifter:
        return None
    return skuld * 0.01 / avgifter * 100


def sparande_per_kvm(data):
    # Föreningens egen redovisade siffra – ingen egen uträkning
    return v(data, "sparande_per_kvm")


def avgift_per_kvm(data):
    avgifter, yta = v(data, "arsavgifter_bostader"), v(data, "bostadsyta_kvm")
    if avgifter is None or not yta:
        return None
    return avgifter / yta


def sammanlagd_procent(procentsatser):
    """Höjningar räknade med ränta-på-ränta: [10, 10] → 21.0. Tom lista → 0."""
    faktor = 1.0
    for p in procentsatser:
        faktor *= 1 + p / 100
    return (faktor - 1) * 100


def avgiftshojningar(data, idag):
    """Avgiftshöjningar sorterade efter datum i förhållande till idag. None om fälten saknas
    (äldre extraktion) eller räkenskapsåret saknas. Returnerar en dict:
      kommande         – [(procent, datum)] som träder i kraft efter idag, eller beslutade utan datum
      kommande_procent – de kommande höjningarna med känt datum och känd storlek, sammanlagt (%)
      kommande_osaker  – True om någon kommande höjning saknar datum eller storlek
      senaste          – [(procent, datum)] som trätt i kraft inom historikfönstret före idag
      senaste_procent  – de senaste höjningarna sammanlagt (%)
    En genomförd höjning utan datum antas ha skett vid räkenskapsårets slut. En beslutad
    höjning utan datum räknas som kommande (den kan redan ha trätt i kraft – fråga)."""
    genomforda, planerade = data.get("genomforda_avgiftshojningar"), data.get("planerade_avgiftshojningar")
    slut = rakenskapsar_slut(data)
    if not isinstance(genomforda, list) or not isinstance(planerade, list) or slut is None:
        return None
    fonster_start = lagg_till_manader(idag, -k.AVGIFTSHOJNING_HISTORIK_MANADER)
    kommande, senaste = [], []
    for post, beslutad in [(p, False) for p in genomforda] + [(p, True) for p in planerade]:
        procent, datum = post.get("procent"), till_datum(post.get("fran_datum"))
        if datum is None and beslutad:
            kommande.append((procent, None))
            continue
        # Saknat datum på en genomförd höjning: placera den vid räkenskapsårets slut,
        # men visa datumet som okänt (det är ett antagande, inte en uppgift)
        placering = datum or slut
        if placering > idag:
            kommande.append((procent, datum))
        elif placering > fonster_start:
            senaste.append((procent, datum))
    kommande.sort(key=lambda h: (h[1] is None, h[1] or idag))
    senaste.sort(key=lambda h: h[1] or slut)
    return {
        "kommande": kommande,
        # Bara daterade höjningar: en beslutad höjning utan datum har ofta redan trätt i kraft
        # (rapporten kan vara över ett år gammal) – den gör raden gul via kommande_osaker.
        "kommande_procent": sammanlagd_procent([p for p, d in kommande if p is not None and d is not None]),
        "kommande_osaker": any(p is None or d is None for p, d in kommande),
        "senaste": senaste,
        "senaste_procent": sammanlagd_procent([p for p, _ in senaste if p is not None]),
    }


def lan_inom_horisont(data, idag=None):
    """Lån (med belopp) som villkorsändras från räkenskapsårets slut till horisonten,
    räknad från IDAG (inte från räkenskapsårets slut – rapporten kan vara över ett år gammal,
    och det är räntorna framåt från köpet som spelar roll). Utan idag räknas horisonten
    från räkenskapsårets slut. Lån utan villkorsändringsdag räknas som inom horisonten
    (försiktigt antagande)."""
    slut = rakenskapsar_slut(data)
    if slut is None:
        return []
    start = max(slut, idag) if idag else slut
    grans = lagg_till_manader(start, k.RANTEBINDNING_HORISONT_MANADER)
    return [
        l for l in data.get("lan") or []
        if l.get("belopp") is not None
        and (till_datum(l.get("villkorsandringsdag")) is None
             or till_datum(l.get("villkorsandringsdag")) <= grans)
    ]


def passerade_villkorsandringar(data, idag):
    """Villkorsändringsdagar (inom horisonten) som redan passerat, sorterade.
    Tom lista om någon villkorsändring inom horisonten ännu inte skett eller saknar datum."""
    datum = [till_datum(l.get("villkorsandringsdag")) for l in lan_inom_horisont(data, idag)]
    if not datum or any(d is None or d >= idag for d in datum):
        return []
    return sorted(set(datum))


def viktad_ranta(lan):
    """Beloppsviktad snittränta i %, eller None om inget lån har ränta angiven."""
    med_ranta = [l for l in lan if l.get("rantesats_procent") is not None]
    vikt = sum(l["belopp"] for l in med_ranta)
    return sum(l["belopp"] * l["rantesats_procent"] for l in med_ranta) / vikt if vikt else None


def okad_rantekostnad(lan):
    """Ökad räntekostnad i kr/år om lånen får marknadsräntan (aldrig negativ per lån).
    Lån utan räntesats räknas inte med (se ranta_saknas)."""
    mr = k.MARKNADSRANTA_FORENINGSLAN_PROCENT
    return sum(l["belopp"] * max(0.0, mr - l["rantesats_procent"]) / 100
               for l in lan if l.get("rantesats_procent") is not None)


def rantebindning(data, idag=None):
    """Lån som villkorsändras från räkenskapsårets slut till horisonten (räknad från idag).
    Returnerar en dict:
      andel, snittranta           – alla dessa lån (andel av total skuld i %, viktad ränta i %)
      andel_kvar, snittranta_kvar – bara de som ännu inte villkorsändrats (datum ≥ idag)
      vantad_avgiftshojning       – kommande lån till marknadsräntan, i % av årsavgifterna
      passerad_avgiftseffekt      – samma för lån som redan villkorsändrats efter räkenskapsåret
                                    (effekten kan redan synas i avgiften – eller komma)
      ranta_saknas                – något lån som ännu inte villkorsändrats saknar räntesats
    Avgiftseffekterna är None om årsavgifterna saknas.
    Lån utan villkorsändringsdag räknas som inom horisonten och ej omförhandlade (försiktigt).
    None om skuld, räkenskapsår eller lån saknas."""
    skuld, slut = total_skuld(data), rakenskapsar_slut(data)
    if skuld is None or slut is None:
        return None
    if skuld == 0:
        return {"andel": 0.0, "snittranta": None, "andel_kvar": 0.0, "snittranta_kvar": None,
                "vantad_avgiftshojning": 0.0, "passerad_avgiftseffekt": 0.0, "ranta_saknas": False}
    if not data.get("lan"):
        return None  # skuld finns men inga lån redovisas

    inom = lan_inom_horisont(data, idag)
    kvar = [l for l in inom
            if idag is None or till_datum(l.get("villkorsandringsdag")) is None
            or till_datum(l.get("villkorsandringsdag")) >= idag]
    passerade = [l for l in inom if l not in kvar]
    avgifter = v(data, "arsavgifter_bostader")
    return {
        "andel": sum(l["belopp"] for l in inom) / skuld * 100,
        "snittranta": viktad_ranta(inom),
        "andel_kvar": sum(l["belopp"] for l in kvar) / skuld * 100,
        "snittranta_kvar": viktad_ranta(kvar),
        "vantad_avgiftshojning": okad_rantekostnad(kvar) / avgifter * 100 if avgifter else None,
        "passerad_avgiftseffekt": okad_rantekostnad(passerade) / avgifter * 100 if avgifter else None,
        "ranta_saknas": any(l.get("rantesats_procent") is None for l in kvar),
    }


def redan_omforhandlad(resultat):
    """True om lån som redan villkorsändrats efter räkenskapsåret (troligen från låg ränta)
    ger en märkbar avgiftseffekt, medan de som återstår inte gör det."""
    if resultat is None or resultat["passerad_avgiftseffekt"] is None:
        return False
    gul = k.RANTEBINDNING_GUL_AVGIFTSHOJNING_PROCENT
    return (resultat["passerad_avgiftseffekt"] >= gul
            and (resultat["vantad_avgiftshojning"] or 0) < gul)


def inom_renoveringshorisont(planerat_ar, slutar):
    """True om åtgärden ligger inom horisonten. Saknat/oläsligt år räknas som inom."""
    ar = re.findall(r"\d{4}", planerat_ar or "")
    if not ar or slutar is None:
        return True
    return min(int(a) for a in ar) <= slutar + k.RENOVERINGAR_HORISONT_AR


def stora_renoveringar(data):
    """Lista med stora åtgärder (enligt nyckelorden) inom horisonten, eller None om fältet saknas."""
    underhall = data.get("planerat_underhall")
    if not isinstance(underhall, list):
        return None
    slut = rakenskapsar_slut(data)
    slutar = slut.year if slut else None
    return [
        u["atgard"] for u in underhall
        if ar_stor_atgard(u.get("atgard") or "")
        and inom_renoveringshorisont(u.get("planerat_ar"), slutar)
    ]


def ar_stor_atgard(text):
    """True om texten har ett nyckelord i början eller slutet av ett ord
    ("takkupor", "yttertak" men inte "kontakt") och inget undantagsord."""
    if any(undantag.lower() in text.lower() for undantag in k.RENOVERINGAR_UNDANTAG):
        return False
    return any(
        re.search(rf"\b{re.escape(ord_)}|{re.escape(ord_)}\b", text, re.IGNORECASE)
        for ord_ in k.RENOVERINGAR_STORA_ATGARDER
    )


def likvida_per_kvm(data):
    likvida, yta = v(data, "likvida_medel_arets_slut"), v(data, "total_yta_kvm")
    if likvida is None or not yta:
        return None
    return likvida / yta


def rapportens_alder_manader(data, idag):
    slut = rakenskapsar_slut(data)
    return None if slut is None else manader_mellan(slut, idag)


def antal_bostadsratter(data):
    """(antal, förklaring). Antal bostadsrätter om det står uttryckligen, annars totalt antal
    lägenheter minus hyresrätter (eller bara totalt om hyresrätter saknas). (None, None) om inget finns."""
    br = v(data, "antal_bostadsratter")
    if br is not None:
        return br, f"{br} bostadsrätter enligt årsredovisningen"
    totalt, hyr = v(data, "antal_lagenheter_totalt"), v(data, "antal_hyresratter")
    if totalt is None:
        return None, None
    if hyr is None:
        return totalt, f"{totalt} lägenheter totalt (antal hyresrätter anges inte)"
    return totalt - hyr, f"{totalt} lägenheter − {hyr} hyresrätter = {totalt - hyr} bostadsrätter"


def senaste_ar(text):
    """Senaste årtalet i en text: "2019-2020" → 2020, "2002" → 2002. None om inget årtal finns."""
    ar = [int(a) for a in re.findall(r"\d{4}", text or "")]
    return max(ar) if ar else None


def byggdelar_i_text(text):
    """Vilka byggdelar (nycklar i k.BYGGDELAR) en åtgärdstext gäller.
    "Elstambyte" → {"el"}, "Rörstambyte - Omfattar badrum" → {"stambyte"},
    "Stamspolning - Översyn av stammar" → set() (spolning/översyn är inget byte)."""
    text = (text or "").lower()
    if any(ord_ in text for ord_ in k.BYGGDELAR_EJ_BYTE):
        return set()
    traffar = set()
    for nyckel, del_ in k.BYGGDELAR.items():
        t = text
        for ord_ in del_["ignorera"]:
            t = t.replace(ord_, " ")
        if any(u in t for u in del_["undantag"]):
            continue
        if (any(re.search(rf"\b{re.escape(o)}|{re.escape(o)}\b", t) for o in del_["nyckelord"])
                or any(re.search(rf"\b{re.escape(o)}\b", t) for o in del_.get("hela_ord", []))):
            traffar.add(nyckel)
    return traffar


def byggdelar(data, idag):
    """Senaste åtgärd och ålder per byggdel ur utfort_underhall, samt om en ny åtgärd
    är planerad inom renoveringshorisonten. None om fältet saknas (äldre extraktion).
    Returnerar {nyckel: {"ar", "alder", "atgard", "planerad"}}; ar/alder är None om okänd."""
    utfort = data.get("utfort_underhall")
    if not isinstance(utfort, list):
        return None
    resultat = {n: {"ar": None, "alder": None, "atgard": None, "planerad": False} for n in k.BYGGDELAR}
    for post in utfort:
        ar = senaste_ar(post.get("ar"))
        if ar is None:
            continue
        for nyckel in byggdelar_i_text(post.get("atgard")):
            if resultat[nyckel]["ar"] is None or ar > resultat[nyckel]["ar"]:
                resultat[nyckel].update(ar=ar, alder=idag.year - ar, atgard=post.get("atgard"))
    # Planerade åtgärder inom horisonten (samma regel som för renoveringar)
    slut = rakenskapsar_slut(data)
    for post in data.get("planerat_underhall") or []:
        if inom_renoveringshorisont(post.get("planerat_ar"), slut.year if slut else None):
            for nyckel in byggdelar_i_text(post.get("atgard")):
                resultat[nyckel]["planerad"] = True
    return resultat


# --- Färger enligt kriterier.py ----------------------------------------------

def farg_belaning(x):
    if x is None:
        return SAKNAS
    if x <= k.BELANING_PER_KVM_GRON_MAX:
        return GRON
    return GUL if x <= k.BELANING_PER_KVM_GUL_MAX else ROD


def farg_rantekanslighet(x):
    if x is None:
        return SAKNAS
    if x <= k.RANTEKANSLIGHET_PROCENT_GRON_MAX:
        return GRON
    return GUL if x <= k.RANTEKANSLIGHET_PROCENT_GUL_MAX else ROD


def farg_sparande(x):
    if x is None:
        return SAKNAS
    if x >= k.SPARANDE_PER_KVM_GRON_MIN:
        return GRON
    return GUL if x >= k.SPARANDE_PER_KVM_GUL_MIN else ROD


def farg_avgift(x):
    if x is None:
        return SAKNAS
    return GRON if k.AVGIFT_PER_KVM_GRON_MIN <= x <= k.AVGIFT_PER_KVM_GRON_MAX else GUL


def farg_avgiftshojningar(h):
    if h is None:
        return SAKNAS
    if h["kommande_procent"] >= k.AVGIFTSHOJNING_ROD_KOMMANDE_PROCENT:
        return ROD
    if h["kommande"] or h["senaste_procent"] >= k.AVGIFTSHOJNING_GUL_SENASTE_PROCENT:
        return GUL
    return GRON


def hojningstext(hojningar):
    """[(10, 2026-01-01), (None, None)] → "+10 % från 2026-01-01, okänd höjning (datum okänt)"."""
    return ", ".join(
        (f"+{tal(p, 1)} %" if p is not None else "okänd höjning")
        + (f" från {d}" if d else " (datum okänt)")
        for p, d in hojningar
    )


def farg_rantebindning(resultat):
    """Färg efter väntad avgiftshöjning när lånen får marknadsräntan."""
    if resultat is None:
        return SAKNAS
    vantad = resultat["vantad_avgiftshojning"]
    if vantad is not None and vantad >= k.RANTEBINDNING_ROD_AVGIFTSHOJNING_PROCENT:
        return ROD
    if vantad is None and resultat["andel_kvar"] > 0:
        return GUL  # årsavgifterna saknas – kan inte räkna
    if ((vantad or 0) >= k.RANTEBINDNING_GUL_AVGIFTSHOJNING_PROCENT or redan_omforhandlad(resultat)
            or resultat["ranta_saknas"]):
        return GUL
    return GRON


def farg_renoveringar(atgarder, likvida):
    if atgarder is None:
        return SAKNAS
    if not atgarder:
        return GRON
    svag_ekonomi = (
        likvida is not None and likvida < k.RENOVERINGAR_ROD_LIKVIDA_PER_KVM_MIN
    )
    return ROD if svag_ekonomi else GUL


def farg_alder(manader):
    if manader is None:
        return SAKNAS
    return GUL if manader > k.RAPPORTENS_ALDER_GUL_MANADER else GRON


def farg_byggdel(nyckel, info):
    """Färg för en byggdel. Okänd (ingen åtgärd i historiken) = gul."""
    granser = k.BYGGDELAR[nyckel]
    if info["alder"] is None:
        return GUL
    if granser["rod_over"] is not None and info["alder"] > granser["rod_over"] and not info["planerad"]:
        return ROD
    return GUL if info["alder"] > granser["gul_over"] else GRON


def farg_byggdelar(status):
    """Sämsta färgen bland byggdelarna."""
    if status is None:
        return SAKNAS
    farger = [farg_byggdel(n, info) for n, info in status.items()]
    return ROD if ROD in farger else GUL if GUL in farger else GRON


def farg_grundlaggning(post):
    if not isinstance(post, dict) or post.get("varde") is None:
        return SAKNAS
    if post["varde"] is False:
        return GRON
    return k.GRUNDLAGGNING_FARG.get(post.get("status") or "okänd", GUL)


def farg_akta(akta):
    if akta is None:
        return SAKNAS
    return GRON if akta else k.OAKTA_FORENING_FARG


def farg_energikostnad(x):
    if x is None:
        return SAKNAS
    return GUL if x > k.ENERGIKOSTNAD_PER_KVM_GUL_OVER else GRON


def farg_byggar(ar):
    if ar is None:
        return SAKNAS
    return ROD if ar > k.BYGGAR_MAX else GRON


def farg_storlek(antal):
    if antal is None:
        return SAKNAS
    return GUL if antal < k.LITEN_FORENING_GUL_UNDER else GRON


def farg_tomtratt(tomtratt):
    if tomtratt is None:
        return SAKNAS
    return k.TOMTRATT_FARG if tomtratt else GRON


def farg_revisorn(anmarkning, upplysning):
    if anmarkning is True:
        return k.REVISORN_ANMARKNING_FARG
    if upplysning is True:
        return k.REVISORN_UPPLYSNING_FARG
    if anmarkning is None or upplysning is None:
        return SAKNAS
    return GRON


# --- Kontrollräkning ---------------------------------------------------------

def sidor(data, falten):
    """Alla sidnummer (sorterade) som fälten hämtats från, även inuti listor och delobjekt."""
    hittade = set()

    def samla(x):
        if isinstance(x, dict):
            if isinstance(x.get("sida"), int):
                hittade.add(x["sida"])
            for varde in x.values():
                if isinstance(varde, (dict, list)):
                    samla(varde)
        elif isinstance(x, list):
            for post in x:
                samla(post)

    for falt in falten:
        samla(data.get(falt))
    return sorted(hittade)


def avvikelse_procent(vart, foreningens):
    """Hur många procent vårt värde avviker från föreningens, eller None om det inte går att jämföra."""
    if vart is None or foreningens is None or foreningens == 0:
        return None
    return abs(vart - foreningens) / abs(foreningens) * 100


# --- Bedömning ---------------------------------------------------------------

def rad(namn, vart, foreningens, farg, kommentarer, fraga, avvikelse=None, varde_tal=None):
    """Bygg en rad i bedömningen. kommentarer = {färg: text}, fraga = text för röd/gul.
    varde_tal = själva talet (för sortering), vart = det formaterade värdet."""
    if farg == SAKNAS:
        kommentar = "Uppgift saknas i årsredovisningen."
        fraga = f"Årsredovisningen saknar underlag för {namn.lower()}. Kan ni ta fram uppgiften?"
    else:
        kommentar = kommentarer[farg]
        if farg == GRON:
            fraga = None
    flaggad = avvikelse is not None and avvikelse > k.KONTROLLRAKNING_TOLERANS_PROCENT
    if flaggad:
        kommentar += f" Avvikelse {tal(avvikelse, 1)} % mot föreningens siffra."
    return {
        "nyckeltal": namn,
        "vart_varde": vart,
        "varde_tal": varde_tal,
        "foreningens_varde": foreningens,
        "farg": farg,
        "kommentar": kommentar,
        "avvikelse_procent": avvikelse,
        "avvikelse": flaggad,
        "fraga_till_maklare": fraga,
    }


def bedom(data, idag):
    """Räkna nyckeltal, sätt färger och utslag. Returnerar resultatet som dict."""
    rader = []

    # Belåning per kvm bostadsrättsyta (bostadsrättsinnehavarna bär skulden, inte lokalerna)
    x, kalla = skuld_per_kvm_bostadsratt(data)
    f = v(data, "skuldsattning_per_kvm_bostadsratt")
    egen = kalla.startswith("egen")
    rader.append(rad(
        "Belåning per kvm", tal(x, 0, "kr/kvm"), tal(f, 0, "kr/kvm"), farg_belaning(x),
        {GRON: "Låg belåning.", GUL: "Måttlig belåning.", ROD: "Hög belåning."},
        f"Belåningen är {tal(x, 0, 'kr/kvm')} bostadsrättsyta. Finns en plan för amortering, "
        "och hur påverkas avgiften om räntan stiger?",
        avvikelse_procent(x, f) if egen else None, varde_tal=avrunda(x),
    ))

    # Räntekänslighet
    x, f = rantekanslighet_procent(data), v(data, "rantekanslighet_procent")
    rader.append(rad(
        "Räntekänslighet", tal(x, 1, "%"), tal(f, 1, "%"), farg_rantekanslighet(x),
        {GRON: "Avgiften tål räntehöjningar väl.",
         GUL: "Avgiften påverkas märkbart av räntehöjningar.",
         ROD: "Avgiften är mycket känslig för räntehöjningar."},
        f"En räntehöjning på 1 procentenhet motsvarar {tal(x, 1, '%')} av årsavgifterna. "
        "Hur har styrelsen budgeterat för högre räntor?",
        avvikelse_procent(x, f), varde_tal=avrunda(x, 1),
    ))

    # Sparande per kvm (föreningens egen siffra)
    sparande = sparande_per_kvm(data)
    rader.append(rad(
        "Sparande per kvm", tal(sparande, 0, "kr/kvm"), tal(sparande, 0, "kr/kvm"), farg_sparande(sparande),
        {GRON: "Gott sparande till underhåll.",
         GUL: "Sparandet är något lågt.",
         ROD: "Sparandet räcker inte till framtida underhåll."},
        f"Föreningen redovisar ett sparande på {tal(sparande, 0, 'kr/kvm')}. "
        "Hur ska framtida underhåll finansieras – avgiftshöjningar eller nya lån?",
        varde_tal=avrunda(sparande),
    ))

    # Avgift per kvm
    x, f = avgift_per_kvm(data), v(data, "arsavgift_per_kvm")
    intervall = f"{k.AVGIFT_PER_KVM_GRON_MIN}–{k.AVGIFT_PER_KVM_GRON_MAX} kr/kvm"
    rader.append(rad(
        "Avgift per kvm", tal(x, 0, "kr/kvm"), tal(f, 0, "kr/kvm"), farg_avgift(x),
        {GRON: f"Inom normalintervallet {intervall}.", GUL: f"Utanför normalintervallet {intervall}."},
        f"Avgiften är {tal(x, 0, 'kr/kvm')}, utanför normalintervallet. Vad beror det på, och är fler höjningar planerade?",
        avvikelse_procent(x, f), varde_tal=avrunda(x),
    ))

    # Avgiftshöjningar – kommande slår direkt mot din månadskostnad, stora senaste tyder på press
    hojn = avgiftshojningar(data, idag)
    farg = farg_avgiftshojningar(hojn)
    fonster = k.AVGIFTSHOJNING_HISTORIK_MANADER
    if hojn is None:
        vart, kommentar_rod = "–", ""
    else:
        delar = []
        if hojn["kommande"]:
            delar.append(f"kommande {hojningstext(hojn['kommande'])}")
        if hojn["senaste"]:
            delar.append(f"senaste {fonster} mån {hojningstext(hojn['senaste'])}")
        vart = "; ".join(delar) or "inga"
    fragor = []
    if hojn and hojn["kommande"]:
        fragor.append(f"Föreningen har beslutat om avgiftshöjningar ({hojningstext(hojn['kommande'])}). "
                      "Ingår de i annonsens avgift, och planeras fler?")
    if hojn and hojn["senaste_procent"] >= k.AVGIFTSHOJNING_GUL_SENASTE_PROCENT:
        fragor.append(f"Avgiften har höjts med sammanlagt {tal(hojn['senaste_procent'], 0, '%')} de senaste "
                      f"{fonster} månaderna. Varför, och räcker höjningarna för att täcka kostnaderna?")
    rader.append(rad(
        "Avgiftshöjningar", vart, "–", farg,
        {GRON: f"Inga beslutade höjningar framåt och inga stora höjningar de senaste {fonster} månaderna.",
         GUL: (f"Beslutade höjningar framåt: {hojningstext(hojn['kommande'])}." if hojn and hojn["kommande"]
               else f"Avgiften har höjts med sammanlagt {tal(hojn['senaste_procent'], 0, '%')} de senaste "
                    f"{fonster} månaderna.") if hojn else "",
         ROD: (f"Beslutade höjningar framåt på sammanlagt {tal(hojn['kommande_procent'], 0, '%')} "
               f"({hojningstext(hojn['kommande'])}) – höjer din månadskostnad.") if hojn else ""},
        " ".join(fragor) or None,
        varde_tal=avrunda(hojn["kommande_procent"], 1) if hojn else None,
    ))

    # Energikostnad per kvm (föreningens egen siffra)
    energi = v(data, "energikostnad_per_kvm")
    rader.append(rad(
        "Energikostnad per kvm", tal(energi, 0, "kr/kvm"), tal(energi, 0, "kr/kvm"), farg_energikostnad(energi),
        {GRON: "Normal energikostnad.",
         GUL: f"Hög energikostnad (över {k.ENERGIKOSTNAD_PER_KVM_GUL_OVER} kr/kvm)."},
        f"Energikostnaden är {tal(energi, 0, 'kr/kvm')}. Finns planer på energibesparande åtgärder, "
        "och hur har kostnaden utvecklats de senaste åren?",
        varde_tal=avrunda(energi),
    ))

    # Räntebindning – väntad avgiftshöjning när lånen får marknadsräntan
    resultat = rantebindning(data, idag)
    h = k.RANTEBINDNING_HORISONT_MANADER
    mr = tal(k.MARKNADSRANTA_FORENINGSLAN_PROCENT, 1, "%")
    farg = farg_rantebindning(resultat)
    andel = resultat["andel"] if resultat else None
    snitt = resultat["snittranta"] if resultat else None
    vantad = resultat["vantad_avgiftshojning"] if resultat else None
    passerade = passerade_villkorsandringar(data, idag)
    if resultat is None:
        gul_text = ""
    elif redan_omforhandlad(resultat):
        gul_text = "Lånen har redan omförhandlats – fråga vilka räntor det blev och hur avgiften påverkats."
    elif resultat["ranta_saknas"]:
        gul_text = "Räntan saknas för lån som villkorsändras – väntad avgiftshöjning går inte att räkna fullt ut."
    elif vantad is None:
        gul_text = "Årsavgifterna saknas – väntad avgiftshöjning går inte att räkna."
    else:
        gul_text = (f"Lån som villkorsändras inom {h} mån ger en väntad avgiftshöjning på ca "
                    f"{tal(vantad, 0, '%')} vid {mr} marknadsränta.")
    fragor = []
    if passerade:
        fragor.append(f"Lånen villkorsändrades {', '.join(str(d) for d in passerade)}. "
                      "Vilka räntor blev det och hur har avgiften påverkats?")
    if resultat and resultat["andel_kvar"] > 0:
        fragor.append(f"{tal(resultat['andel_kvar'], 0, '%')} av lånen villkorsändras inom {h} månader"
                      + (f", vilket vid {mr} ränta motsvarar ca {tal(vantad, 0, '%')} högre avgift"
                         if vantad else "")
                      + ". Hur har styrelsen budgeterat för det?")
    rader.append(rad(
        "Räntebindning",
        (f"{tal(andel, 0, '%')} inom {h} mån, snitt {tal(snitt, 2, '%')}, "
         f"väntad avgiftshöjning {tal(vantad, 1, '%')}") if resultat else "–",
        "–", farg,
        {GRON: f"Liten väntad avgiftshöjning när lånen villkorsändras inom {h} mån (vid {mr} marknadsränta).",
         GUL: gul_text,
         ROD: (f"Lån som villkorsändras inom {h} mån ger en väntad avgiftshöjning på ca "
               f"{tal(vantad, 0, '%')} vid {mr} marknadsränta.") if vantad is not None else ""},
        " ".join(fragor) or None, varde_tal=avrunda(vantad, 1),
    ))

    # Renoveringar – utan redovisad underhållsplan blir raden minst gul
    atgarder = stora_renoveringar(data)
    likvida = likvida_per_kvm(data)
    ar = k.RENOVERINGAR_HORISONT_AR
    farg = farg_renoveringar(atgarder, likvida)
    plan_saknas = v(data, "underhallsplan_finns") is not True
    plan_okand = "underhallsplan_finns" not in data  # äldre extraktion utan fältet
    if plan_saknas and farg == GRON:
        farg = GUL
    if plan_okand:
        tillagg = " Underhållsplan okänd – " + ALDRE_EXTRAKTION[0].lower() + ALDRE_EXTRAKTION[1:]
    else:
        tillagg = " Ingen underhållsplan redovisas." if plan_saknas else ""
    fragor = []
    if atgarder:
        fragor.append(f"Planerade stora åtgärder: {'; '.join(atgarder)}. Vad beräknas de kosta och hur ska de finansieras?")
    if plan_saknas and not plan_okand:
        fragor.append("Årsredovisningen redovisar ingen underhållsplan. Finns en aktuell plan, och hur långt fram sträcker den sig?")
    rader.append(rad(
        "Renoveringar", f"{len(atgarder)} stora inom {ar} år" if atgarder is not None else "–", "–", farg,
        {GRON: f"Inga stora åtgärder planerade inom {ar} år.",
         GUL: (f"Stora åtgärder planerade inom {ar} år, kassan räcker (likvida medel {tal(likvida, 0, 'kr/kvm')})."
               if atgarder else f"Inga stora åtgärder planerade inom {ar} år.") + tillagg,
         ROD: f"Stora åtgärder inom {ar} år och liten kassa "
              f"(likvida medel {tal(likvida, 0, 'kr/kvm')}, under {k.RENOVERINGAR_ROD_LIKVIDA_PER_KVM_MIN} kr/kvm)." + tillagg},
        " ".join(fragor) or None,
        varde_tal=len(atgarder) if atgarder is not None else None,
    ))

    # Byggdelar – ålder sedan senaste åtgärd, färg = sämsta byggdelen
    delar = byggdelar(data, idag)
    if delar is not None:
        beskrivning = ", ".join(
            f"{k.BYGGDELAR[n]['namn']} {i['ar']} ({i['alder']} år)" if i["ar"] else f"{k.BYGGDELAR[n]['namn']} okänd"
            for n, i in delar.items()
        )
        flaggade = [
            f"{k.BYGGDELAR[n]['namn']}: senast åtgärdad {i['ar']} ({i['alder']} år sedan)" if i["ar"]
            else f"{k.BYGGDELAR[n]['namn']}: ingen åtgärd i underhållshistoriken"
            for n, i in delar.items() if farg_byggdel(n, i) != GRON
        ]
        kanda = [(i["alder"], k.BYGGDELAR[n]["namn"]) for n, i in delar.items() if i["alder"] is not None]
        aldst = max(kanda) if kanda else None
    else:
        beskrivning, flaggade, aldst = "", [], None
    rader.append(rad(
        "Byggdelar", f"äldst {aldst[0]} år ({aldst[1]})" if aldst else "–", "–", farg_byggdelar(delar),
        {GRON: beskrivning + ".", GUL: beskrivning + ".", ROD: beskrivning + "."},
        f"{'; '.join(flaggade)}. När gjordes senaste större åtgärd, och vad planeras?",
        varde_tal=aldst[0] if aldst else None,
    ))

    # Grundläggning
    grund = data.get("grundlaggning") if isinstance(data.get("grundlaggning"), dict) else {}
    farg = farg_grundlaggning(grund)
    status = grund.get("status")
    grund_text = grund.get("beskrivning") or ""
    if farg == SAKNAS:
        vart = "–"
    elif grund.get("varde") is False:
        vart = "Nej"
    else:
        vart = status or "okänd"
    rader.append(rad(
        "Grundläggning", vart, "–", farg,
        {GRON: f"Grundproblem åtgärdat ({senaste_ar(grund_text) or 'år okänt'}): {grund_text}"
               if grund.get("varde") else "Inga problem med grunden nämns.",
         GUL: f"Grundproblem nämns, status okänd: {grund_text}",
         ROD: f"Grundproblem {status}: {grund_text}"},
        f"Årsredovisningen nämner problem med grunden ({grund_text}). Vad är status, vad kostar åtgärden "
        "och hur påverkar den avgiften?",
        varde_tal=None if farg == SAKNAS else vart,  # text
    ))

    # Rapportens ålder
    manader = rapportens_alder_manader(data, idag)
    rader.append(rad(
        "Rapportens ålder", tal(manader, 0, "mån"), "–", farg_alder(manader),
        {GRON: "Aktuell årsredovisning.",
         GUL: f"Räkenskapsåret slutade för mer än {k.RAPPORTENS_ALDER_GUL_MANADER} månader sedan."},
        "Finns en nyare årsredovisning eller annan aktuell ekonomisk information?",
        varde_tal=manader,
    ))

    # Tomträtt
    tomtratt = v(data, "tomtratt")
    tomtratt_text = {True: "Ja", False: "Nej"}.get(tomtratt, "–")
    rader.append(rad(
        "Tomträtt", tomtratt_text, "–", farg_tomtratt(tomtratt),
        {GRON: "Marken ägs av föreningen.",
         GUL: "Tomträtt – avgälden kan höjas vid omreglering. Fråga när nästa omreglering sker.",
         ROD: "Tomträtt – avgälden kan höjas vid omreglering. Fråga när nästa omreglering sker."},
        "När omregleras tomträttsavgälden nästa gång, och vad väntas den nya avgälden bli?",
        varde_tal=tomtratt_text,  # text
    ))

    # Äkta förening
    akta = v(data, "akta_forening")
    akta_text = {True: "Ja", False: "Nej"}.get(akta, "–")
    rader.append(rad(
        "Äkta förening", akta_text, "–", farg_akta(akta),
        {GRON: "Äkta bostadsrättsförening.",
         GUL: "Oäkta bostadsrättsförening – kan ge skattekonsekvenser för medlemmarna.",
         ROD: "Oäkta bostadsrättsförening – kan ge skattekonsekvenser för medlemmarna."},
        "Föreningen är oäkta. Vilka skattekonsekvenser får det för mig som köpare, och planerar föreningen att bli äkta?",
        varde_tal=akta_text,  # text
    ))

    # Föreningens storlek – kommentaren visar hur antalet räknats fram
    antal, harledning = antal_bostadsratter(data)
    rader.append(rad(
        "Föreningens storlek", tal(antal, 0, "bostadsrätter"), "–", farg_storlek(antal),
        {GRON: f"{harledning}. Tillräckligt många att dela kostnader och styrelsearbete.",
         GUL: f"{harledning}. Liten förening (under {k.LITEN_FORENING_GUL_UNDER} bostadsrätter) – "
              "större kostnader slår hårt."},
        f"Föreningen har bara {tal(antal, 0)} bostadsrätter. Hur fungerar styrelsearbetet, och hur skulle "
        "en stor oväntad kostnad hanteras?",
        varde_tal=antal,
    ))

    # Hyresrätter – informationsrad utan färg
    hyr = v(data, "antal_hyresratter")
    if hyr is None:
        hyr_text = "Antal hyresrätter anges inte."
    elif hyr > 0:
        hyr_text = "Kan säljas som bostadsrätter när de blir lediga – möjlig intäkt för föreningen."
    else:
        hyr_text = "Inga hyresrätter."
    rader.append(rad("Hyresrätter", tal(hyr, 0, "st"), "–", INFO, {INFO: hyr_text}, None, varde_tal=hyr))

    # Byggår (senaste om flera hus)
    byggar = v(data, "byggnadsar")
    rader.append(rad(
        "Byggår", str(byggar) if byggar else "–", "–", farg_byggar(byggar),
        {GRON: f"Byggt {byggar}.", ROD: f"Utanför sökfiltret (byggt efter {k.BYGGAR_MAX})."},
        None,  # sökfilter, ingen fråga till mäklaren
        varde_tal=byggar,
    ))

    # Revisorn
    anmarkning, upplysning = v(data, "revisorns_anmarkning"), v(data, "revisorns_upplysning")
    farg = farg_revisorn(anmarkning, upplysning)
    vart = "Anmärkning" if anmarkning else "Upplysning" if upplysning else "Ren" if farg == GRON else "–"
    rader.append(rad(
        "Revisorn", vart, "–", farg,
        {GRON: "Ren revisionsberättelse.",
         GUL: "Revisorn lämnar en upplysning av särskild betydelse." if upplysning else "Revisorn har en anmärkning.",
         ROD: "Revisorn har en anmärkning." if anmarkning else "Revisorn lämnar en upplysning av särskild betydelse."},
        "Revisorn har en anmärkning. Vad gäller den och vad har styrelsen gjort åt saken?" if anmarkning
        else "Revisorn lämnar en upplysning av särskild betydelse. Vad gäller den och vad gör styrelsen åt saken?",
        varde_tal=vart,  # text
    ))
    if farg == SAKNAS:
        rader[-1]["fraga_till_maklare"] = (
            "Revisionsberättelsen verkar inte ingå i årsredovisningen. Kan ni skicka den?")

    # Saknas uppgiften för att extraktionen är äldre än fältet? Då ska inte mäklaren få frågan.
    for r in rader:
        if r["farg"] == SAKNAS and any(f not in data for f in BEROENDEN.get(r["nyckeltal"], ())):
            r["kommentar"] = ALDRE_EXTRAKTION
            r["fraga_till_maklare"] = None

    # Sidhänvisningar: varifrån i PDF:en varje rad hämtat sina uppgifter
    for r in rader:
        r["sidor"] = sidor(data, BEROENDEN.get(r["nyckeltal"], ()))

    # Rimlighetsvarningar: troliga felavläsningar + egna nyckeltal som avviker från föreningens
    varningar = rimlighet.kontrollera(data, total_skuld(data))
    varningar += [f"{r['nyckeltal']}: egen uträkning avviker {tal(r['avvikelse_procent'], 1)} % "
                  "från föreningens siffra." for r in rader if r["avvikelse"]]

    # Rader som inte räknas i utslaget märks, så att det syns i terminal och Excel
    for r in rader:
        r["raknas_i_utslag"] = r["nyckeltal"] not in k.UTSLAG_RAKNAS_EJ and r["farg"] != INFO
        if r["nyckeltal"] in k.UTSLAG_RAKNAS_EJ:
            r["kommentar"] += " (Påverkar inte utslaget.)"
            r["fraga_till_maklare"] = None  # aldrig mäklarfrågor för rader utanför utslaget

    # Utslag – "saknas" räknas som färgen i SAKNAS_RAKNAS_SOM
    farger = [k.SAKNAS_RAKNAS_SOM if r["farg"] == SAKNAS else r["farg"] for r in rader if r["raknas_i_utslag"]]
    roda, gula = farger.count(ROD), farger.count(GUL)
    if roda >= k.UTSLAG_SORTERA_BORT_MIN_RODA:
        utslag = "SORTERA BORT"
    elif roda >= k.UTSLAG_AVVAKTA_MIN_RODA or gula >= k.UTSLAG_AVVAKTA_MIN_GULA:
        utslag = "AVVAKTA"
    else:
        utslag = "GÅ VIDARE"

    return {
        "forening": v(data, "foreningens_namn"),
        "org_nr": v(data, "organisationsnummer"),
        "rakenskapsar_slut": str(rakenskapsar_slut(data)) if rakenskapsar_slut(data) else None,
        "idag": idag.isoformat(),
        "nyckeltal": rader,
        "detaljer": {
            "total_skuld": total_skuld(data),
            "total_skuld_forklaring": total_skuld_med_forklaring(data)[1],
            "likvida_medel_per_kvm": likvida,
            "vantad_avgiftshojning_ranta_procent": avrunda(resultat["vantad_avgiftshojning"], 2) if resultat else None,
            "avgiftshojningar_kommande_procent": avrunda(hojn["kommande_procent"], 2) if hojn else None,
            "avgiftshojningar_kommande_osaker": hojn["kommande_osaker"] if hojn else None,
            "skuld_per_kvm_bostadsratt": avrunda(skuld_per_kvm_bostadsratt(data)[0]),
            "skuld_per_kvm_bostadsratt_kalla": skuld_per_kvm_bostadsratt(data)[1],
            "skuld_per_kvm_bostadsratt_avvikelse_procent": avrunda(avvikelse_procent(
                skuld_per_kvm_bostadsratt(data)[0], v(data, "skuldsattning_per_kvm_bostadsratt")), 1),
            "stora_renoveringar": atgarder,
            "byggdelar": delar,
        },
        "utslag": utslag,
        "antal_roda": roda,
        "antal_gula": gula,
        "antal_saknas": [r["farg"] for r in rader if r["raknas_i_utslag"]].count(SAKNAS),
        "raknas_ej_i_utslag": [r["nyckeltal"] for r in rader if r["nyckeltal"] in k.UTSLAG_RAKNAS_EJ],
        "fragor_till_maklare": [r["fraga_till_maklare"] for r in rader if r["fraga_till_maklare"]],
        "varningar": varningar,
    }


# --- Utskrift ----------------------------------------------------------------

def skriv_tabell(resultat):
    rubriker = ["Nyckeltal", "Vårt värde", "Föreningens värde", "Färg", "Kort kommentar"]
    rader = [
        [r["nyckeltal"], r["vart_varde"], r["foreningens_varde"],
         "–" if r["farg"] == INFO else r["farg"] + ("*" if r["nyckeltal"] in k.UTSLAG_RAKNAS_EJ else ""),
         r["kommentar"]]
        for r in resultat["nyckeltal"]
    ]
    # Kolumnbredd = längsta texten i varje kolumn (utom sista)
    bredd = [max(len(str(x)) for x in kolumn) for kolumn in zip(rubriker, *rader)]
    for i, rad_ in enumerate([rubriker] + rader):
        print(" | ".join(str(x).ljust(b) for x, b in zip(rad_[:-1], bredd)) + " | " + rad_[-1])
        if i == 0:
            print("-+-".join("-" * b for b in bredd[:-1]) + "-+-" + "-" * len(rubriker[-1]))


def main():
    parser = argparse.ArgumentParser(description="Bedöm en förening utifrån extraherad JSON.")
    parser.add_argument("fil", help="data/extracted/<namn>.json")
    parser.add_argument("--idag", help="Dagens datum ÅÅÅÅ-MM-DD (för rapportens ålder)")
    args = parser.parse_args()

    idag = date.today()
    if args.idag:
        idag = till_datum(args.idag)
        if idag is None:
            sys.exit(f"Ogiltigt datum för --idag: {args.idag} (använd ÅÅÅÅ-MM-DD)")

    bedom_fil(Path(args.fil), idag)


def bedom_fil(sokvag: Path, idag: date) -> dict:
    """Läs en extraherad JSON-fil, bedöm den, skriv ut tabellen och spara i data/bedomning/.
    Returnerar resultatet. Avslutar med felmeddelande vid fel."""
    if not sokvag.exists():
        sys.exit(f"Filen finns inte: {sokvag}")
    try:
        data = json.loads(sokvag.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"Filen är inte giltig JSON: {e}")

    resultat = bedom(data, idag)

    print(f"{resultat['forening']} – räkenskapsår t.o.m. {resultat['rakenskapsar_slut']} (bedömt {idag})\n")
    skriv_tabell(resultat)
    print(f"\nUtslag: {resultat['utslag']}  ({resultat['antal_roda']} röda, {resultat['antal_gula']} gula"
          f"{', varav ' + str(resultat['antal_saknas']) + ' saknas' if resultat['antal_saknas'] else ''})")
    if resultat["raknas_ej_i_utslag"]:
        print(f"* Räknas inte i utslaget: {', '.join(resultat['raknas_ej_i_utslag'])}")
    if resultat["varningar"]:
        print("\n⚠️  Kontrollera i PDF:en:")
        for varning in resultat["varningar"]:
            print(f"  - {varning}")
    print("\nFrågor till mäklaren:")
    for i, fraga in enumerate(resultat["fragor_till_maklare"], 1):
        print(f"  {i}. {fraga}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    utfil = OUTPUT_DIR / sokvag.name
    utfil.write_text(json.dumps(resultat, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSparat till: {utfil}")
    return resultat


if __name__ == "__main__":
    main()
