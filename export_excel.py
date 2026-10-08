"""
Steg 4: Samla alla bedömningar i en Excel-fil.
Kör: python export_excel.py
Läser data/bedomning/*.json och bygger output/bostadsanalys.xlsx från grunden varje gång.
"""

import json
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

import kriterier as k

BEDOMNING_DIR = Path("data/bedomning")
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


def sorteringsnyckel(b):
    """GÅ VIDARE först, sedan AVVAKTA, sist SORTERA BORT; inom gruppen färst röda (sedan gula) först."""
    return (UTSLAG_ORDNING.get(b["utslag"], 9), b["antal_roda"], b["antal_gula"], b["forening"] or "")


def formatera_flik(ark):
    """Fet rubrikrad, frys rubriken, autofilter och kolumnbredd efter innehållet."""
    for cell in ark[1]:
        cell.font = Font(bold=True)
    ark.freeze_panes = "A2"
    ark.auto_filter.ref = ark.dimensions
    for kolumn in ark.columns:
        langst = max(len(str(c.value)) if c.value is not None else 0 for c in kolumn)
        ark.column_dimensions[get_column_letter(kolumn[0].column)].width = min(langst + 2, MAX_KOLUMNBREDD)


def bygg_oversikt(ark, bedomningar):
    # Nyckeltalen i den ordning de först förekommer
    nyckeltal = []
    for b in bedomningar:
        for r in b["nyckeltal"]:
            if r["nyckeltal"] not in nyckeltal:
                nyckeltal.append(r["nyckeltal"])

    fasta = ["Förening", "Org.nr", "Räkenskapsår (slut)", "Bedömd datum", "Utslag", "Antal röda", "Antal gula"]
    # Okänt nyckeltal (finns inte i KOLUMNER) får sitt namn som rubrik och inget talformat
    ark.append(fasta + [KOLUMNER.get(n, (n, None))[0] for n in nyckeltal])

    for b in bedomningar:
        per_namn = {r["nyckeltal"]: r for r in b["nyckeltal"]}
        ark.append(
            [b["forening"], b.get("org_nr"), b["rakenskapsar_slut"], b["idag"], b["utslag"], b["antal_roda"], b["antal_gula"]]
            + [per_namn[n].get("varde_tal") if n in per_namn else None for n in nyckeltal]
        )
        rad = ark.max_row
        # Färga utslaget
        ark.cell(rad, fasta.index("Utslag") + 1).fill = FARGER[UTSLAG_FARG.get(b["utslag"], "saknas")]
        # Talformat och färg för varje nyckeltal (grå om det saknas)
        for i, n in enumerate(nyckeltal, start=len(fasta) + 1):
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

    bok = Workbook()
    oversikt = bok.active
    oversikt.title = "Översikt"
    bygg_oversikt(oversikt, bedomningar)
    bygg_fragor(bok.create_sheet("Frågor till mäklaren"), bedomningar)

    UTFIL.parent.mkdir(parents=True, exist_ok=True)
    try:
        bok.save(UTFIL)
    except PermissionError:
        sys.exit(f"Stäng {UTFIL.name} i Excel och kör igen.")

    print(f"✅ {len(bedomningar)} föreningar exporterade till {UTFIL}")


if __name__ == "__main__":
    main()
