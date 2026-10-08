"""
Kör hela kedjan med ett kommando: (nedladdning) → extraktion → bedömning → Excel.
Kör: python analysera.py "<länk till årsredovisning-PDF>" [annonsuppgifter]
     python analysera.py data/pdfs/<fil>.pdf [annonsuppgifter]

Annonsuppgifter (valfria, sparas i data/annonser.json och visas i Excel):
     --annons <booli-url> --adress <text> --pris <heltal> --avgift <heltal> --rum <tal> --kvm <tal>

Extraktionen (Claude-API:t) kostar pengar och körs bara efter att du svarat ja.
Alla andra steg är gratis.
"""

import argparse
import hashlib
import json
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlparse

import bedomning
import export_excel
import extract_report

PDF_DIR = Path("data/pdfs")
ADRESS_MAX_TECKEN = 100


def filsakert_namn(url: str) -> str:
    """Filnamnet ur URL:en (utan query-parametrar), utan å/ä/ö och mellanslag."""
    namn = unquote(Path(urlparse(url).path).name) or "arsredovisning.pdf"
    namn = unicodedata.normalize("NFKD", namn).encode("ascii", "ignore").decode("ascii")  # å -> a
    namn = re.sub(r"[^A-Za-z0-9._-]+", "_", namn).strip("._") or "arsredovisning"
    return namn if namn.lower().endswith(".pdf") else f"{namn}.pdf"


def identisk_pdf(innehall: bytes) -> Path | None:
    """En befintlig PDF i data/pdfs/ med exakt samma innehåll, eller None."""
    kontrollsumma = hashlib.sha256(innehall).hexdigest()
    for fil in sorted(PDF_DIR.glob("*.pdf")):
        if hashlib.sha256(fil.read_bytes()).hexdigest() == kontrollsumma:
            return fil
    return None


def ladda_ner(url: str) -> Path:
    """Steg 1: ladda ner PDF:en till data/pdfs/ (om den inte redan finns)."""
    sokvag = PDF_DIR / filsakert_namn(url)
    if sokvag.exists():
        print(f"PDF finns redan: {sokvag}")
        return sokvag

    print(f"Laddar ner {url} ...")
    try:
        # Egen User-Agent – Pythons standard ("Python-urllib") nekas av vissa servrar
        begaran = urllib.request.Request(url, headers={"User-Agent": "bostadsanalys/1.0"})
        with urllib.request.urlopen(begaran, timeout=60) as svar:
            innehall = svar.read()
    except urllib.error.HTTPError as e:
        sys.exit(f"Nedladdningen misslyckades: servern svarade {e.code} ({e.reason}).")
    except (urllib.error.URLError, TimeoutError) as e:
        sys.exit(f"Kunde inte nå {url}: {getattr(e, 'reason', e)}")

    if not innehall.startswith(b"%PDF"):
        sys.exit("Det nedladdade är ingen PDF (kanske en felsida eller inloggning). Kontrollera länken.")

    # Samma PDF under annat namn? Använd den befintliga, så att extraktionen inte görs (och betalas) två gånger.
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    befintlig = identisk_pdf(innehall)
    if befintlig:
        print(f"Samma PDF finns redan som {befintlig} – använder den.")
        return befintlig

    sokvag.write_bytes(innehall)
    print(f"Sparad: {sokvag}")
    return sokvag


def fraga_ja_nej(fraga: str) -> bool:
    try:
        return input(f"{fraga} [j/n] ").strip().lower() in ("j", "ja")
    except (EOFError, KeyboardInterrupt):
        print()
        return False


class SvenskParser(argparse.ArgumentParser):
    """argparse med felmeddelande på svenska."""
    def error(self, message):
        sys.exit(f"Fel i argumenten: {message}\n{self.format_usage()}")


def heltal(namn, text):
    """Positivt heltal, t.ex. 5995000. Inga mellanslag eller enheter."""
    if not re.fullmatch(r"\d+", text) or int(text) == 0:
        sys.exit(f"Ogiltigt värde för --{namn}: {text!r} (ange ett positivt heltal, t.ex. 5995000)")
    return int(text)


def decimaltal(namn, text):
    """Positivt tal med punkt eller komma som decimaltecken, t.ex. 2,5 eller 63."""
    if not re.fullmatch(r"\d+([.,]\d+)?", text) or float(text.replace(",", ".")) == 0:
        sys.exit(f"Ogiltigt värde för --{namn}: {text!r} (ange ett positivt tal, t.ex. 2 eller 63,5)")
    tal = float(text.replace(",", "."))
    return int(tal) if tal.is_integer() else tal


def validera_annons(args):
    """Kontrollera annonsargumenten strikt. Returnerar en dict, eller None om inga angavs."""
    falt = {"annons": args.annons, "adress": args.adress, "pris": args.pris,
            "avgift": args.avgift, "rum": args.rum, "kvm": args.kvm}
    if all(v is None for v in falt.values()):
        return None
    if args.annons is None:
        sys.exit("Annonsuppgifter kräver --annons (länken till annonsen på Booli).")
    if not re.fullmatch(r"https://www\.booli\.se/[A-Za-z0-9/_.\-]*", args.annons):
        sys.exit(f"Ogiltig --annons: {args.annons!r} (måste börja med https://www.booli.se/ och vara en vanlig sökväg)")
    adress = None
    if args.adress is not None:
        adress = args.adress.strip()
        if not adress or len(adress) > ADRESS_MAX_TECKEN or not adress.isprintable():
            sys.exit(f"Ogiltig --adress: 1–{ADRESS_MAX_TECKEN} tecken, utan radbrytningar eller styrtecken.")
    return {
        "annons_url": args.annons,
        "adress": adress,
        "pris": heltal("pris", args.pris) if args.pris is not None else None,
        "avgift": heltal("avgift", args.avgift) if args.avgift is not None else None,
        "rum": decimaltal("rum", args.rum) if args.rum is not None else None,
        "kvm": decimaltal("kvm", args.kvm) if args.kvm is not None else None,
    }


def spara_annons(annons, org_nr, pdf):
    """Lägg till annonsen i data/annonser.json, eller uppdatera den om annons_url redan finns.
    Uppgifter som inte angavs denna gång behåller sitt tidigare värde."""
    annonser = export_excel.las_annonser()
    ny = {**annons, "org_nr": org_nr, "pdf_fil": str(pdf)}
    befintlig = next((a for a in annonser if a.get("annons_url") == annons["annons_url"]), None)
    if befintlig:
        befintlig.update({k: v for k, v in ny.items() if v is not None})
        print(f"Annons uppdaterad: {annons['annons_url']}")
    else:
        annonser.append({**ny, "tillagd_datum": date.today().isoformat()})
        print(f"Annons sparad: {annons['annons_url']}")
    export_excel.ANNONSER_FIL.parent.mkdir(parents=True, exist_ok=True)
    export_excel.ANNONSER_FIL.write_text(json.dumps(annonser, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = SvenskParser(description="Kör hela kedjan: PDF → extraktion → bedömning → Excel.")
    parser.add_argument("indata", help="Länk till årsredovisning-PDF eller lokal fil i data/pdfs/")
    parser.add_argument("--annons", help="Länk till annonsen, https://www.booli.se/...")
    parser.add_argument("--adress", help=f"Adress (max {ADRESS_MAX_TECKEN} tecken)")
    parser.add_argument("--pris", help="Pris i kr (heltal)")
    parser.add_argument("--avgift", help="Månadsavgift i kr (heltal)")
    parser.add_argument("--rum", help="Antal rum (tal)")
    parser.add_argument("--kvm", help="Boarea i kvm (tal)")
    args = parser.parse_args()
    indata = args.indata

    # Validera annonsuppgifterna innan något annat görs
    annons = validera_annons(args)

    # 1. PDF: ladda ner eller använd lokal fil
    print("== 1. PDF")
    if indata.startswith(("http://", "https://")):
        pdf = ladda_ner(indata)
    else:
        pdf = Path(indata)
    extract_report.las_pdf(pdf)  # kontrollerar att filen finns och är en PDF

    # 2. Extraktion (kostar pengar – fråga först)
    print("\n== 2. Extraktion")
    json_fil = extract_report.utfil_for(pdf)
    if json_fil.exists():
        print(f"Redan extraherad: {json_fil} (gratis)")
    else:
        if not fraga_ja_nej("Extraktion kostar ca 1 kr. Fortsätt?"):
            sys.exit("Avbrutet – ingen extraktion gjord.")
        extract_report.extrahera(pdf)

    # 3. Bedömning
    print("\n== 3. Bedömning")
    resultat = bedomning.bedom_fil(json_fil, date.today())

    # Spara annonsen (kopplas till föreningen via org.nr)
    if annons:
        print()
        spara_annons(annons, resultat.get("org_nr"), pdf)

    # 4. Excel-export
    print("\n== 4. Excel")
    export_excel.main()

    # 5. Sammanfattning
    print(f"\n{'=' * 50}")
    print(f"Förening: {resultat['forening']}")
    print(f"Utslag:   {resultat['utslag']} ({resultat['antal_roda']} röda, {resultat['antal_gula']} gula)")
    print(f"Excel uppdaterad: {export_excel.UTFIL}")


if __name__ == "__main__":
    try:
        main()
    except OSError as e:
        # T.ex. full disk eller saknad skrivrätt – visa ett meddelande i stället för en traceback
        sys.exit(f"Fil- eller systemfel: {e}")
