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
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

import kriterier as k
from lagenhet import annonsnyckeltal

BEDOMNING_DIR = Path("data/bedomning")
ANNONSER_FIL = Path("data/annonser.json")
UTFIL = Path("output/bostadsanalys.xlsx")
PDF_DIR = Path("data/pdfs")

# Kolumnrubrik (med enhet) och Excel-talformat per nyckeltal.
# Format None = texten skrivs som den är (tomträtt, revisorn).
KOLUMNER = {
    "Belåning per kvm": ("Belåning (kr/kvm bostadsrättsyta)", "#,##0"),
    "Räntekänslighet": ("Räntekänslighet (%)", "0.0"),
    "Sparande per kvm": ("Sparande (kr/kvm)", "#,##0"),
    "Avgift per kvm": ("Avgift (kr/kvm)", "#,##0"),
    "Avgiftshöjningar": ("Avgiftshöjningar (% beslutade framåt)", "0.0"),
    "Energikostnad per kvm": ("Energikostnad (kr/kvm)", "#,##0"),
    "Byggdelar": ("Byggdelar (äldsta, år sedan åtgärd)", "0"),
    "Grundläggning": ("Grundläggning", None),
    "Äkta förening": ("Äkta förening", None),
    "Föreningens storlek": ("Bostadsrätter (antal)", "0"),
    "Hyresrätter": ("Hyresrätter (antal)", "0"),
    "Byggår": ("Byggår", "0"),
    "Räntebindning": (f"Räntebindning (väntad avgiftshöjning %, vid {k.MARKNADSRANTA_FORENINGSLAN_PROCENT} % ränta)", "0.0"),
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
RUBRIK_MAX_BREDD = 16  # längre rubriker radbryts i stället för att göra kolumnen bred


def las_bedomningar():
    """Läs alla bedömningar i data/bedomning/."""
    bedomningar = []
    for fil in sorted(BEDOMNING_DIR.glob("*.json")):
        try:
            b = json.loads(fil.read_text(encoding="utf-8"))
            b["_stam"] = fil.stem  # samma stam som PDF:en och extraktionen
            bedomningar.append(b)
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


def profilnamn(b):
    """Visningsnamn för bedömningens köparprofil (gamla bedömningar utan profil = standard)."""
    pid = b.get("koparprofil") or k.STANDARD_KOPARPROFIL
    return k.KOPARPROFILER.get(pid, {}).get("namn", pid)


def sorteringsnyckel(b):
    """GÅ VIDARE först, sedan AVVAKTA, sist SORTERA BORT; inom gruppen högst poäng först.
    En annons vars förening saknar bedömning (b = None) hamnar sist."""
    if b is None:
        return (99, 0, "")
    return (UTSLAG_ORDNING.get(b["utslag"], 9), -(b.get("poang") or 0), b["forening"] or "")


def rader_for_oversikt(bedomningar, annonser):
    """Para ihop annonser och bedömningar via org.nr: en rad per annons, plus en rad
    (utan annons) för varje bedömd förening som ingen annons pekar på. Sorterade."""
    per_org = {b.get("org_nr"): b for b in bedomningar if b.get("org_nr")}
    rader = [(a, per_org.get(a.get("org_nr"))) for a in annonser]
    med_annons = {a.get("org_nr") for a in annonser}
    rader += [(None, b) for b in bedomningar if not b.get("org_nr") or b.get("org_nr") not in med_annons]
    return sorted(rader, key=lambda rad: sorteringsnyckel(rad[1]))


def formatera_flik(ark):
    """Fet, radbruten rubrikrad, frys rubriken, autofilter och kolumnbredd efter innehållet.
    Långa rubriker radbryts, så kolumnbredden styrs främst av värdena under rubriken."""
    for cell in ark[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    ark.freeze_panes = "A2"
    ark.auto_filter.ref = ark.dimensions
    rader_i_rubrik = 1
    for kolumn in ark.columns:
        rubrik = str(kolumn[0].value or "")
        langst_varde = max((len(str(c.value)) for c in kolumn[1:] if c.value is not None), default=0)
        # Längsta ordet i rubriken ska rymmas, annars räcker värdenas bredd (eller RUBRIK_MAX_BREDD)
        langsta_ord = max((len(o) for o in rubrik.split()), default=0)
        bredd = min(max(langst_varde, langsta_ord, min(len(rubrik), RUBRIK_MAX_BREDD)) + 2, MAX_KOLUMNBREDD)
        ark.column_dimensions[get_column_letter(kolumn[0].column)].width = bredd
        rader_i_rubrik = max(rader_i_rubrik, -(-len(rubrik) // max(bredd - 2, 1)))  # avrundat uppåt
    # Höjd för rubrikraden så att radbrutna rubriker syns (ca 15 punkter per textrad)
    ark.row_dimensions[1].height = 15 * rader_i_rubrik


# Beslutskolumnerna står först, direkt efter adressen
BESLUT = [("Utslag", None), ("Poäng (0–100)", "0"), ("Motivering", None), ("Datakvalitet", None)]
MOTIVERING_BREDD = 70
DATAKVALITET_FARG = {"Säker": "grön", "Osäker": "gul"}


def bygg_oversikt(ark, bedomningar, annonser):
    # Nyckeltalen i den ordning de först förekommer
    nyckeltal = []
    for b in bedomningar:
        for r in b["nyckeltal"]:
            if r["nyckeltal"] not in nyckeltal:
                nyckeltal.append(r["nyckeltal"])

    # Annonskolumner efter beslutet: (rubrik, talformat)
    annonskolumner = [("Pris (kr)", "#,##0"), ("Avgift (kr/mån)", "#,##0"), ("Väntad avgift (kr/mån)", "#,##0"),
                      ("Skuldjusterat pris (kr)", "#,##0"), ("Skuldjusterat pris per kvm (kr)", "#,##0"),
                      ("Pris per kvm (kr)", "#,##0"), ("Avgift efter beslutade höjningar (kr/mån)", "#,##0"),
                      ("Rum", None), ("Boarea (kvm)", None)]
    fasta = ["Förening", "Org.nr", "Räkenskapsår (slut)", "Bedömd datum", "Köparprofil",
             "Antal röda", "Antal gula", "Kontrollera i PDF:en"]
    kolumner = [("Adress", None)] + BESLUT + annonskolumner
    forsta_forening = len(kolumner) + 1  # kolumnnummer där föreningens kolumner börjar
    kol = {namn: i for i, (namn, _) in enumerate(kolumner, start=1)}
    kol.update({namn: forsta_forening + i for i, namn in enumerate(fasta)})
    # Renoveringsrubriken visar horisonten bedömningarna faktiskt använt (en profil → en siffra,
    # flera profiler i samma export → generell text), inte den hårdkodade konstanten.
    horisonter = {b.get("renoveringshorisont_ar") for b in bedomningar if b.get("renoveringshorisont_ar")}
    renov_titel = (f"Stora renoveringar (antal inom {next(iter(horisonter))} år)"
                   if len(horisonter) == 1 else "Stora renoveringar (antal inom horisonten)")

    def rubrik(n):
        # Rader som inte räknas i utslaget (kriterier.UTSLAG_RAKNAS_EJ) märks i rubriken.
        titel = renov_titel if n == "Renoveringar" else KOLUMNER.get(n, (n, None))[0]
        return titel + (" – påverkar inte utslaget" if n in k.UTSLAG_RAKNAS_EJ else "")

    ark.append([r for r, _ in kolumner] + fasta + [rubrik(n) for n in nyckeltal])

    for a, b in rader_for_oversikt(bedomningar, annonser):
        # Annonsdelen (tom om föreningen analyserats utan annons)
        a = a or {}
        t = annonsnyckeltal(a, b)
        annonsdel = [t["pris"], t["avgift"], t["vantad_avgift"], t["skuldjusterat_pris"],
                     t["skuldjusterat_pris_per_kvm"], t["pris_per_kvm"], t["avgift_efter_beslutade_hojningar"],
                     t["rum"], t["kvm"]]
        adress = a.get("adress") or a.get("annons_url") or (b or {}).get("forening")

        if b is None:
            ark.append([adress] + [None] * len(BESLUT) + annonsdel + [None] * (len(fasta) + len(nyckeltal)))
        else:
            per_namn = {r["nyckeltal"]: r for r in b["nyckeltal"]}
            ark.append(
                [adress, b["utslag"], b.get("poang"), b.get("motivering"), b.get("datakvalitet")]
                + annonsdel
                + [b["forening"], b.get("org_nr"), b["rakenskapsar_slut"], b["idag"], profilnamn(b),
                   b["antal_roda"], b["antal_gula"], "; ".join(b.get("varningar") or []) or None]
                + [per_namn[n].get("varde_tal") if n in per_namn else None for n in nyckeltal]
            )
        rad = ark.max_row

        # Adressen blir en klickbar länk till annonsen; talformat på beslut och annonsens tal
        if a.get("annons_url"):
            cell = ark.cell(rad, kol["Adress"])
            cell.hyperlink = a["annons_url"]
            cell.style = "Hyperlink"
        for namn, talformat in kolumner:
            if talformat:
                ark.cell(rad, kol[namn]).number_format = talformat

        if b is None:
            continue
        # Beslutet: färgat utslag och datakvalitet, radbruten motivering
        utslag_cell = ark.cell(rad, kol["Utslag"])
        utslag_cell.fill = FARGER[UTSLAG_FARG.get(b["utslag"], "saknas")]
        utslag_cell.font = Font(bold=True)
        ark.cell(rad, kol["Poäng (0–100)"]).fill = FARGER[UTSLAG_FARG.get(b["utslag"], "saknas")]
        ark.cell(rad, kol["Motivering"]).alignment = Alignment(wrap_text=True, vertical="top")
        # Radhöjd så att hela motiveringen syns (ca 15 punkter per textrad)
        ark.row_dimensions[rad].height = 15 * max(1, -(-len(b.get("motivering") or "") // (MOTIVERING_BREDD - 5)))
        kvalitet = ark.cell(rad, kol["Datakvalitet"])
        kvalitet.fill = FARGER[DATAKVALITET_FARG.get(b.get("datakvalitet"), "saknas")]
        if b.get("datakvalitet_forklaring"):
            kvalitet.comment = Comment(b["datakvalitet_forklaring"], "bostadsanalys", width=300, height=80)
        # Rimlighetsvarningar markeras gula
        if b.get("varningar"):
            ark.cell(rad, kol["Kontrollera i PDF:en"]).fill = FARGER["gul"]
        # Föreningens namn länkar till PDF:en (relativt Excel-filen i output/)
        pdf = Path(a.get("pdf_fil") or PDF_DIR / f"{b.get('_stam')}.pdf")
        if pdf.exists():
            cell = ark.cell(rad, kol["Förening"])
            cell.hyperlink = str(Path("..") / pdf)
            cell.style = "Hyperlink"
        # Talformat och färg för varje nyckeltal (grå om det saknas)
        for i, n in enumerate(nyckeltal, start=forsta_forening + len(fasta)):
            cell = ark.cell(rad, i)
            talformat = KOLUMNER.get(n, (n, None))[1]
            if talformat:
                cell.number_format = talformat
            farg = per_namn[n]["farg"] if n in per_namn else "saknas"
            # Kommentar: förklaringen och var i PDF:en uppgiften står
            if n in per_namn:
                sidorna = per_namn[n].get("sidor") or []
                text = per_namn[n].get("kommentar") or ""
                if sidorna:
                    text += f"\n\nPDF:en sida {', '.join(str(x) for x in sidorna)}"
                if text:
                    cell.comment = Comment(text, "bostadsanalys", width=300, height=120)
            if farg != "info":  # informationsrader får ingen färg
                cell.fill = FARGER.get(farg, FARGER["saknas"])

    formatera_flik(ark)
    # Motiveringen får en fast bredd och radbryts, i stället för en jättebred kolumn
    ark.column_dimensions[get_column_letter(kol["Motivering"])].width = MOTIVERING_BREDD
    ark.freeze_panes = ark.cell(2, kol["Utslag"])  # rubrikraden och adressen står kvar vid scroll


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
