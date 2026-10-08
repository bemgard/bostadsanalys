"""
Kör hela kedjan med ett kommando: (nedladdning) → extraktion → bedömning → Excel.
Kör: python analysera.py "<länk till årsredovisning-PDF>"
     python analysera.py data/pdfs/<fil>.pdf

Extraktionen (Claude-API:t) kostar pengar och körs bara efter att du svarat ja.
Alla andra steg är gratis.
"""

import hashlib
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


def main():
    if len(sys.argv) != 2:
        sys.exit('Användning: python analysera.py "<länk till årsredovisning-PDF>" | data/pdfs/<fil>.pdf')
    indata = sys.argv[1]

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
