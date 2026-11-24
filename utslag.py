"""
Utslaget: GÅ VIDARE / AVVAKTA / SORTERA BORT, med poäng, motivering och datakvalitet.

1. Stoppfaktorer – en räcker för SORTERA BORT, oavsett resten.
2. Poäng 0–100 – viktat snitt över raderna som räknas i utslaget (grön = 1, gul = ½,
   röd = 0, saknas = som SAKNAS_RAKNAS_SOM). Tunga kriterier väger mer.
   Röda tunga kriterier har egna regler: två eller fler → SORTERA BORT, ett → högst AVVAKTA.
3. Motivering i klartext – utslaget, poängen och de största riskerna.
4. Datakvalitet – Säker/Osäker efter hur mycket som saknas och antal rimlighetsvarningar.

Alla vikter och gränser i kriterier.py. Modulen räknar bara på de färdiga raderna.
"""

import kriterier as k

GRON, GUL, ROD, SAKNAS = "grön", "gul", "röd", "saknas"
GA_VIDARE, AVVAKTA, SORTERA_BORT = "GÅ VIDARE", "AVVAKTA", "SORTERA BORT"
POANG_PER_FARG = {GRON: 1.0, GUL: 0.5, ROD: 0.0}


def vikt(namn, vikter=None):
    """Vikten för ett nyckeltal. vikter = köparprofilens vikter (kriterier.los_profil);
    None = basvikterna i UTSLAG_VIKTER."""
    return (vikter or k.UTSLAG_VIKTER).get(namn, k.UTSLAG_VIKT_STANDARD)


def tung(namn, vikter=None):
    return vikt(namn, vikter) >= k.UTSLAG_TUNG_VIKT


def sparande_tung_rod(per_namn):
    """Lågt sparande räknas som en tung röd risk bara om föreningen också har hög belåning
    eller stort kommande underhåll (röd på någon av k.SPARANDE_TUNG_ROD_VILLKOR). Isolerat
    lågt sparande med låg skuld och underhåll i ordning är ofarligt."""
    if not k.SPARANDE_TUNG_ROD_KRAVER_RISK:
        return True
    return any(per_namn.get(n, {}).get("farg") == ROD for n in k.SPARANDE_TUNG_ROD_VILLKOR)


def poang(rader, vikter=None):
    """Viktat snitt 0–100 över raderna som räknas, eller None om inga rader räknas."""
    raknas = [r for r in rader if r.get("raknas_i_utslag")]
    total = sum(vikt(r["nyckeltal"], vikter) for r in raknas)
    if not total:
        return None
    summa = sum(vikt(r["nyckeltal"], vikter) * POANG_PER_FARG[k.SAKNAS_RAKNAS_SOM if r["farg"] == SAKNAS else r["farg"]]
                for r in raknas)
    return round(summa / total * 100)


def stoppfaktorer(rader, vantad_avgiftshojning):
    """Texter för de stoppfaktorer som slår till (tom lista om inga)."""
    per_namn = {r["nyckeltal"]: r for r in rader}
    stopp = []
    if k.STOPP_OAKTA_FORENING and per_namn.get("Äkta förening", {}).get("farg") == ROD:
        stopp.append("oäkta förening (skattekonsekvenser för medlemmarna)")
    if k.STOPP_REVISORNS_ANMARKNING and per_namn.get("Revisorn", {}).get("vart_varde") == "Anmärkning":
        stopp.append("revisorn har en anmärkning")
    if k.STOPP_GRUNDPROBLEM and per_namn.get("Grundläggning", {}).get("farg") == ROD:
        stopp.append("planerade eller pågående problem med grunden")
    grans = k.STOPP_VANTAD_AVGIFTSHOJNING_PROCENT
    if grans is not None and vantad_avgiftshojning is not None and vantad_avgiftshojning >= grans:
        stopp.append(f"väntad avgiftshöjning ca {round(vantad_avgiftshojning)} % när lånen villkorsändras")
    return stopp


def risker(rader, antal=3, vikter=None):
    """De största riskerna: röda före gula, tunga före lätta, i radordning. Korta texter."""
    kandidater = [(i, r) for i, r in enumerate(rader) if r.get("raknas_i_utslag") and r["farg"] in (ROD, GUL)]
    kandidater.sort(key=lambda ir: (ir[1]["farg"] != ROD, -vikt(ir[1]["nyckeltal"], vikter), ir[0]))
    return [r.get("kort") or f"{r['nyckeltal'].lower()} {r['vart_varde']}" for _, r in kandidater[:antal]]


def datakvalitet(rader, varningar, vikter=None):
    """("Säker"/"Osäker", förklaring)."""
    raknas = [r for r in rader if r.get("raknas_i_utslag")]
    saknas = [r["nyckeltal"] for r in raknas if r["farg"] == SAKNAS]
    tunga_saknas = [n for n in saknas if tung(n, vikter)]
    osaker = (len(saknas) >= k.DATAKVALITET_OSAKER_SAKNADE or tunga_saknas
              or len(varningar) >= k.DATAKVALITET_OSAKER_VARNINGAR)
    delar = [f"{len(saknas)} av {len(raknas)} nyckeltal saknas" + (f" ({', '.join(saknas)})" if saknas else ""),
             f"{len(varningar)} rimlighetsvarning{'ar' if len(varningar) != 1 else ''}"]
    return ("Osäker" if osaker else "Säker"), ", ".join(delar)


def bedom_utslag(rader, varningar, vantad_avgiftshojning, vikter=None):
    """Utslag, poäng, stoppfaktorer, motivering och datakvalitet som en dict.
    vikter = köparprofilens vikter (kriterier.los_profil); None = basvikterna."""
    p = poang(rader, vikter)
    stopp = stoppfaktorer(rader, vantad_avgiftshojning)
    per_namn = {r["nyckeltal"]: r for r in rader}
    tunga_roda = [r["nyckeltal"] for r in rader
                  if r.get("raknas_i_utslag") and r["farg"] == ROD and tung(r["nyckeltal"], vikter)]
    # Lågt sparande ensamt (utan hög belåning eller stort kommande underhåll) ska inte
    # kunna ge SORTERA BORT eller blockera GÅ VIDARE – se kriterier.SPARANDE_TUNG_ROD_*.
    if "Sparande per kvm" in tunga_roda and not sparande_tung_rod(per_namn):
        tunga_roda.remove("Sparande per kvm")
    if stopp:
        utslag = SORTERA_BORT
    elif len(tunga_roda) >= k.UTSLAG_SORTERA_BORT_TUNGA_RODA:
        utslag = SORTERA_BORT
    elif p is None or p < k.UTSLAG_AVVAKTA_MIN_POANG:
        utslag = SORTERA_BORT
    elif tunga_roda or p < k.UTSLAG_GA_VIDARE_MIN_POANG:
        utslag = AVVAKTA
    else:
        utslag = GA_VIDARE

    storsta = risker(rader, vikter=vikter)
    if stopp:
        stoppnamn = {"Äkta förening", "Revisorn", "Grundläggning"}
        storsta = risker([r for r in rader if r["nyckeltal"] not in stoppnamn], vikter=vikter)
    tunga_risker = [r for r in rader
                    if r.get("raknas_i_utslag") and r["farg"] in (ROD, GUL) and tung(r["nyckeltal"], vikter)]
    rubrik = f"{utslag} ({p if p is not None else '–'}/100)."
    if stopp:
        motivering = f"{utslag} – stoppfaktor: {'; '.join(stopp)}."
        if storsta:
            motivering += f" Övriga risker: {' · '.join(storsta)}."
    elif utslag == GA_VIDARE:
        motivering = rubrik + (f" Att kontrollera: {' · '.join(storsta)}." if tunga_risker and storsta
                               else " Inga tunga risker." + (f" Små anmärkningar: {' · '.join(storsta)}." if storsta else ""))
    elif utslag == AVVAKTA:
        orsak = (f" Rött på {', '.join(n.lower() for n in tunga_roda)} – kan inte bli GÅ VIDARE förrän det är utrett."
                 if tunga_roda and p >= k.UTSLAG_GA_VIDARE_MIN_POANG else "")
        motivering = (f"{rubrik}{orsak} Största riskerna: {' · '.join(storsta)}. "
                      "Klargör dem med mäklaren innan du går vidare (se fliken Frågor till mäklaren).")
    else:
        orsak = (f" Rött på flera tunga kriterier: {', '.join(n.lower() for n in tunga_roda)}."
                 if len(tunga_roda) >= k.UTSLAG_SORTERA_BORT_TUNGA_RODA else "")
        motivering = rubrik + orsak + (f" Största riskerna: {' · '.join(storsta)}." if storsta else "")

    kvalitet, kvalitet_text = datakvalitet(rader, varningar, vikter)
    if kvalitet == "Osäker":
        motivering += " Underlaget är osäkert – kontrollera i PDF:en."
    return {
        "utslag": utslag,
        "poang": p,
        "stoppfaktorer": stopp,
        "motivering": motivering,
        "datakvalitet": kvalitet,
        "datakvalitet_forklaring": kvalitet_text,
    }
