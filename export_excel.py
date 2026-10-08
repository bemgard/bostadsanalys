"""
Steg 4: Samla alla bedömningar i en Excel-fil.
Kör: python export_excel.py
Läser data/bedomning/*.json och data/annonser.json och bygger output/bostadsanalys.xlsx
från grunden varje gång. En rad per annons; föreningar utan annons får en egen rad.
"""

import json
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

import kriterier as k

BEDOMNING_DIR = Path("data/bedomning")
ANNONSER_FIL = Path("data/annonser.json")
UTFIL = Path("output/bostadsanalys.xlsx")

# Kolumnrubrik (med enhet) och Excel-talformat per nyckeltal.
# Format None = texten skrivs som den är (tomträtt, revisorn).
KOLUMNER = {
    "Belåning per kvm": ("Belåning (kr/kvm)", "#,##0"),
    "Räntekänslighet": ("Räntekänslighet (%)", "0.0"),
    "Sparande per kvm": ("Sparande (kr/kvm)", "#,##0"),
    "Avgift per kvm": ("Avgift (kr/kvm)", "#,##0"),
    "Räntebindning": (f"Räntebindning (% av skulden inom {k.RANTEBINDNING_HORISONT_MANADER} mån)", "0"),
    "Renoveringar": (f"Stora renoveringar (antal inom {k.RENOVERINGAR_HORISONT_AR} år)", "0"),
    "Rapportens ålder": ("Rapportens ålder (mån)", "0"),
    "Tomträtt": ("Tomträtt", None),
    "Revisorn": ("Revisorn", None),
}

# Bakgrundsfärger för celler (Excels standardtoner för grön/gul/röd)
FARGER = {
    "grön": PatternFill("solid", fgColor="C6EFCE"),
    "gul": PatternFill("solid", fgColor="FFEB9C"),
    "röd": PatternFill("solid", fgColor="FFC7CE"),
    "saknas": PatternFill("solid", fgColor="D9D9D9"),
}
UTSLAG_FARG = {"GÅ VIDARE": "grön", "AVVAKTA": "gul", "SORTERA BORT": "röd"}
UTSLAG_ORDNING = {"GÅ VIDARE": 0, "AVVAKTA": 1, "SORTERA BORT": 2}
MAX_KOLUMNBREDD = 60


def las_bedomningar():
    """Läs alla bedömningar i data/bedomning/."""
    bedomningar = []
    for fil in sorted(BEDOMNING_DIR.glob("*.json")):
        try:
            bedomningar.append(json.loads(fil.read_text(encoding="utf-8")))
        except json.JSONDecodeError as e:
            sys.exit(f"{fil} är inte giltig JSON: {e}")
    return bedomningar


def las_annonser():
    """Läs data/annonser.json (lista med annonser), eller tom lista om filen saknas."""
    if not ANNONSER_FIL.exists():
        return []
    try:
        return json.loads(ANNONSER_FIL.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"{ANNONSER_FIL} är inte giltig JSON: {e}")


def sorteringsnyckel(b):
    """GÅ VIDARE först, sedan AVVAKTA, sist SORTERA BORT; inom gruppen färst röda (sedan gula) först.
    En annons vars förening saknar bedömning (b = None) hamnar sist."""
    if b is None:
        return (99, 0, 0, "")
    return (UTSLAG_ORDNING.get(b["utslag"], 9), b["antal_roda"], b["antal_gula"], b["forening"] or "")


def rader_for_oversikt(bedomningar, annonser):
    """Para ihop annonser och bedömningar via org.nr: en rad per annons, plus en rad
    (utan annons) för varje bedömd förening som ingen annons pekar på. Sorterade."""
    per_org = {b.get("org_nr"): b for b in bedomningar if b.get("org_nr")}
    rader = [(a, per_org.get(a.get("org_nr"))) for a in annonser]
    med_annons = {a.get("org_nr") for a in annonser}
    rader += [(None, b) for b in bedomningar if not b.get("org_nr") or b.get("org_nr") not in med_annons]
    return sorted(rader, key=lambda rad: sorteringsnyckel(rad[1]))


def formatera_flik(ark):
    """Fet rubrikrad, frys rubriken, autofilter och kolumnbredd efter innehållet."""
    for cell in ark[1]:
        cell.font = Font(bold=True)
    ark.freeze_panes = "A2"
    ark.auto_filter.ref = ark.dimensions
    for kolumn in ark.columns:
        langst = max(len(str(c.value)) if c.value is not None else 0 for c in kolumn)
        ark.column_dimensions[get_column_letter(kolumn[0].column)].width = min(langst + 2, MAX_KOLUMNBREDD)


def bygg_oversikt(ark, bedomningar, annonser):
    # Nyckeltalen i den ordning de först förekommer
    nyckeltal = []
    for b in bedomningar:
        for r in b["nyckeltal"]:
            if r["nyckeltal"] not in nyckeltal:
                nyckeltal.append(r["nyckeltal"])

    # Annonskolumner: (rubrik, talformat)
    annonskolumner = [("Adress", None), ("Pris (kr)", "#,##0"), ("Avgift (kr/mån)", "#,##0"),
                      ("Rum", None), ("Boarea (kvm)", None), ("Pris per kvm (kr)", "#,##0")]
    fasta = ["Förening", "Org.nr", "Räkenskapsår (slut)", "Bedömd datum", "Utslag", "Antal röda", "Antal gula"]
    forsta_forening = len(annonskolumner) + 1  # kolumnnummer där föreningens kolumner börjar
    # Okänt nyckeltal (finns inte i KOLUMNER) får sitt namn som rubrik och inget talformat
    ark.append([r for r, _ in annonskolumner] + fasta + [KOLUMNER.get(n, (n, None))[0] for n in nyckeltal])

    for a, b in rader_for_oversikt(bedomningar, annonser):
        # Annonsdelen (tom om föreningen analyserats utan annons)
        a = a or {}
        pris, kvm = a.get("pris"), a.get("kvm")
        pris_per_kvm = round(pris / kvm) if pris and kvm else None
        annonsdel = [a.get("adress") or a.get("annons_url"), pris, a.get("avgift"), a.get("rum"), kvm, pris_per_kvm]

        # Föreningsdelen (tom om annonsens förening saknar bedömning)
        if b is None:
            ark.append(annonsdel + [None] * (len(fasta) + len(nyckeltal)))
        else:
            per_namn = {r["nyckeltal"]: r for r in b["nyckeltal"]}
            ark.append(
                annonsdel
                + [b["forening"], b.get("org_nr"), b["rakenskapsar_slut"], b["idag"], b["utslag"], b["antal_roda"], b["antal_gula"]]
                + [per_namn[n].get("varde_tal") if n in per_namn else None for n in nyckeltal]
            )
        rad = ark.max_row

        # Adressen blir en klickbar länk till annonsen; talformat på annonsens tal
        if a.get("annons_url"):
            cell = ark.cell(rad, 1)
            cell.hyperlink = a["annons_url"]
            cell.style = "Hyperlink"
        for i, (_, talformat) in enumerate(annonskolumner, start=1):
            if talformat:
                ark.cell(rad, i).number_format = talformat

        if b is None:
            continue
        # Färga utslaget
        ark.cell(rad, forsta_forening + fasta.index("Utslag")).fill = FARGER[UTSLAG_FARG.get(b["utslag"], "saknas")]
        # Talformat och färg för varje nyckeltal (grå om det saknas)
        for i, n in enumerate(nyckeltal, start=forsta_forening + len(fasta)):
            cell = ark.cell(rad, i)
            talformat = KOLUMNER.get(n, (n, None))[1]
            if talformat:
                cell.number_format = talformat
            farg = per_namn[n]["farg"] if n in per_namn else "saknas"
            cell.fill = FARGER.get(farg, FARGER["saknas"])

    formatera_flik(ark)


def bygg_fragor(ark, bedomningar):
    ark.append(["Förening", "Utslag", "Fråga"])
    for b in bedomningar:
        for fraga in b["fragor_till_maklare"]:
            ark.append([b["forening"], b["utslag"], fraga])
    formatera_flik(ark)


def main():
    bedomningar = las_bedomningar()
    if not bedomningar:
        sys.exit(f"Inga bedömningar hittades i {BEDOMNING_DIR}. Kör bedomning.py först.")
    bedomningar.sort(key=sorteringsnyckel)
    annonser = las_annonser()

    bok = Workbook()
    oversikt = bok.active
    oversikt.title = "Översikt"
    bygg_oversikt(oversikt, bedomningar, annonser)
    bygg_fragor(bok.create_sheet("Frågor till mäklaren"), bedomningar)

    UTFIL.parent.mkdir(parents=True, exist_ok=True)
    try:
        bok.save(UTFIL)
    except PermissionError:
        sys.exit(f"Stäng {UTFIL.name} i Excel och kör igen.")

    print(f"✅ {len(bedomningar)} föreningar och {len(annonser)} annonser exporterade till {UTFIL}")


if __name__ == "__main__":
    main()
