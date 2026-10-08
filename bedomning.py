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

GRON, GUL, ROD, SAKNAS = "grön", "gul", "röd", "saknas"
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

def total_skuld(data):
    lang = v(data, "skulder_kreditinstitut_langfristiga")
    kort = v(data, "skulder_kreditinstitut_kortfristiga")
    if lang is None or kort is None:
        return None
    return lang + kort


def belaning_per_kvm(data):
    skuld, yta = total_skuld(data), v(data, "total_yta_kvm")
    if skuld is None or not yta:
        return None
    return skuld / yta


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


def lan_inom_horisont(data):
    """Lån (med belopp) som villkorsändras inom horisonten från räkenskapsårets slut.
    Lån utan villkorsändringsdag räknas som inom horisonten (försiktigt antagande)."""
    slut = rakenskapsar_slut(data)
    if slut is None:
        return []
    grans = lagg_till_manader(slut, k.RANTEBINDNING_HORISONT_MANADER)
    return [
        l for l in data.get("lan") or []
        if l.get("belopp") is not None
        and (till_datum(l.get("villkorsandringsdag")) is None
             or till_datum(l.get("villkorsandringsdag")) <= grans)
    ]


def passerade_villkorsandringar(data, idag):
    """Villkorsändringsdagar (inom horisonten) som redan passerat, sorterade.
    Tom lista om någon villkorsändring inom horisonten ännu inte skett eller saknar datum."""
    datum = [till_datum(l.get("villkorsandringsdag")) for l in lan_inom_horisont(data)]
    if not datum or any(d is None or d >= idag for d in datum):
        return []
    return sorted(set(datum))


def rantebindning(data):
    """Returnerar (andel av skulden i %, viktad snittränta i %) för lån som
    villkorsändras inom horisonten. Snitträntan är None om ingen ränta anges.
    Lån utan villkorsändringsdag räknas som inom horisonten (försiktigt antagande)."""
    skuld, slut = total_skuld(data), rakenskapsar_slut(data)
    if skuld is None or slut is None:
        return None
    if skuld == 0:
        return 0.0, None
    lan = data.get("lan") or []
    if not lan:
        return None  # skuld finns men inga lån redovisas

    inom = lan_inom_horisont(data)
    andel = sum(l["belopp"] for l in inom) / skuld * 100

    med_ranta = [l for l in inom if l.get("rantesats_procent") is not None]
    vikt = sum(l["belopp"] for l in med_ranta)
    snittranta = sum(l["belopp"] * l["rantesats_procent"] for l in med_ranta) / vikt if vikt else None
    return andel, snittranta


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


def farg_rantebindning(resultat):
    if resultat is None:
        return SAKNAS
    andel, snittranta = resultat
    if (andel > k.RANTEBINDNING_ROD_ANDEL_PROCENT and snittranta is not None
            and snittranta < k.RANTEBINDNING_ROD_RANTA_MAX_PROCENT):
        return ROD
    return GUL if andel > k.RANTEBINDNING_GUL_ANDEL_PROCENT else GRON


def farg_renoveringar(atgarder, sparande, likvida):
    if atgarder is None:
        return SAKNAS
    if not atgarder:
        return GRON
    svag_ekonomi = (
        (sparande is not None and sparande < k.RENOVERINGAR_ROD_SPARANDE_MIN)
        or (likvida is not None and likvida < k.RENOVERINGAR_ROD_LIKVIDA_PER_KVM_MIN)
    )
    return ROD if svag_ekonomi else GUL


def farg_alder(manader):
    if manader is None:
        return SAKNAS
    return GUL if manader > k.RAPPORTENS_ALDER_GUL_MANADER else GRON


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

    # Belåning per kvm
    x, f = belaning_per_kvm(data), v(data, "skuldsattning_per_kvm_totalyta")
    rader.append(rad(
        "Belåning per kvm", tal(x, 0, "kr/kvm"), tal(f, 0, "kr/kvm"), farg_belaning(x),
        {GRON: "Låg belåning.", GUL: "Måttlig belåning.", ROD: "Hög belåning."},
        f"Belåningen är {tal(x, 0, 'kr/kvm')}. Finns en plan för amortering, och hur påverkas avgiften om räntan stiger?",
        avvikelse_procent(x, f), varde_tal=avrunda(x),
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

    # Räntebindning
    resultat = rantebindning(data)
    h = k.RANTEBINDNING_HORISONT_MANADER
    andel, snitt = resultat if resultat else (None, None)
    passerade = passerade_villkorsandringar(data, idag)
    if passerade:
        fraga = (f"Lånen villkorsändrades {', '.join(str(d) for d in passerade)}. "
                 "Vilka räntor blev det och hur har avgiften påverkats?")
    else:
        fraga = (f"{tal(andel, 0, '%')} av lånen villkorsändras inom {h} månader. "
                 "Vilka räntor har de nya villkoren fått, och hur påverkar det avgiften?")
    rader.append(rad(
        "Räntebindning",
        f"{tal(andel, 0, '%')} inom {h} mån, snitt {tal(snitt, 2, '%')}" if resultat else "–",
        "–", farg_rantebindning(resultat),
        {GRON: f"Liten del av skulden får ny ränta inom {h} mån.",
         GUL: f"{tal(andel, 0, '%')} av skulden får ny ränta inom {h} mån.",
         ROD: f"{tal(andel, 0, '%')} av skulden får ny ränta inom {h} mån, från låg snittränta – risk för kraftigt höjd räntekostnad."},
        fraga, varde_tal=avrunda(andel),
    ))

    # Renoveringar
    atgarder = stora_renoveringar(data)
    likvida = likvida_per_kvm(data)
    ar = k.RENOVERINGAR_HORISONT_AR
    rader.append(rad(
        "Renoveringar", f"{len(atgarder)} stora inom {ar} år" if atgarder is not None else "–", "–",
        farg_renoveringar(atgarder, sparande, likvida),
        {GRON: f"Inga stora åtgärder planerade inom {ar} år.",
         GUL: f"Stora åtgärder planerade inom {ar} år.",
         ROD: f"Stora åtgärder inom {ar} år och svag ekonomi "
              f"(sparande {tal(sparande, 0, 'kr/kvm')}, likvida medel {tal(likvida, 0, 'kr/kvm')})."},
        f"Planerade stora åtgärder: {'; '.join(atgarder or [])}. Vad beräknas de kosta och hur ska de finansieras?",
        varde_tal=len(atgarder) if atgarder is not None else None,
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
         GUL: "Marken innehas med tomträtt – avgälden kan höjas.",
         ROD: "Marken innehas med tomträtt – avgälden kan höjas."},
        "När omregleras tomträttsavgälden nästa gång, och vad väntas den nya avgälden bli?",
        varde_tal=tomtratt_text,  # text
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

    # Utslag – "saknas" räknas som färgen i SAKNAS_RAKNAS_SOM
    farger = [k.SAKNAS_RAKNAS_SOM if r["farg"] == SAKNAS else r["farg"] for r in rader]
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
            "likvida_medel_per_kvm": likvida,
            "stora_renoveringar": atgarder,
        },
        "utslag": utslag,
        "antal_roda": roda,
        "antal_gula": gula,
        "antal_saknas": [r["farg"] for r in rader].count(SAKNAS),
        "fragor_till_maklare": [r["fraga_till_maklare"] for r in rader if r["fraga_till_maklare"]],
    }


# --- Utskrift ----------------------------------------------------------------

def skriv_tabell(resultat):
    rubriker = ["Nyckeltal", "Vårt värde", "Föreningens värde", "Färg", "Kort kommentar"]
    rader = [
        [r["nyckeltal"], r["vart_varde"], r["foreningens_varde"], r["farg"], r["kommentar"]]
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
