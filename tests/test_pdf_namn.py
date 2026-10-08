"""
Testar att PDF:er från olika föreningar aldrig blandas ihop, även om de har samma filnamn.
Kör: python tests/test_pdf_namn.py
Inga nätverksanrop: nedladdningen ersätts med påhittade PDF:er i en tillfällig mapp.
"""

import io
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import analysera  # noqa: E402

# Två olika föreningar vars PDF:er heter likadant i URL:en
URL_A = "https://documents.bcdn.se/aa/11/aaaaaaaaaaaa/arsredovisning_2024.pdf"
URL_B = "https://documents.bcdn.se/bb/22/bbbbbbbbbbbb/arsredovisning_2024.pdf"
PDF_A = b"%PDF-1.4 forening A"
PDF_B = b"%PDF-1.4 forening B"

godkanda = totalt = 0


def kontrollera(namn, fick, forvantat):
    global godkanda, totalt
    totalt += 1
    if fick == forvantat:
        godkanda += 1
        print(f"  ✅ {namn}")
    else:
        print(f"  ❌ {namn}\n       förväntat: {forvantat}\n       fick:      {fick}")


def ladda_ner(url, innehall):
    """Kör analysera.ladda_ner med en påhittad nedladdning som returnerar innehall."""
    with mock.patch.object(analysera.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(innehall)):
        return analysera.ladda_ner(url)


print("Filnamn")
kontrollera("unikt prefix ur URL:en",
            analysera.filsakert_namn(URL_A), "aaaaaaaaaaaa_arsredovisning_2024.pdf")
kontrollera("samma filnamn, olika föreningar → olika namn",
            analysera.filsakert_namn(URL_A) != analysera.filsakert_namn(URL_B), True)
kontrollera("parametrar påverkar inte namnet",
            analysera.filsakert_namn(URL_A + "?next=%2Fx"), "aaaaaaaaaaaa_arsredovisning_2024.pdf")
kontrollera("URL utan mappar får kontrollsumma som prefix",
            len(analysera.filsakert_namn("https://x.se/arsredovisning_2024.pdf").split("_")[0]), 12)

with tempfile.TemporaryDirectory() as tmp, mock.patch.object(analysera, "PDF_DIR", Path(tmp)), \
        mock.patch("builtins.print"):
    a = ladda_ner(URL_A, PDF_A)
    b = ladda_ner(URL_B, PDF_B)
    resultat = {
        "olika filer": a != b,
        "A innehåller A": a.read_bytes() == PDF_A,
        "B innehåller B": b.read_bytes() == PDF_B,
        "olika extraktioner": analysera.extract_report.utfil_for(a) != analysera.extract_report.utfil_for(b),
    }
    # Samma URL igen med samma innehåll → återanvänds
    resultat["samma PDF igen återanvänds"] = ladda_ner(URL_A, PDF_A) == a
    # Samma URL (samma namn) men ANNAT innehåll → får aldrig återanvända den gamla
    ny = ladda_ner(URL_A, b"%PDF-1.4 ny version")
    resultat["annat innehåll, samma namn → ny fil"] = ny != a
    resultat["gamla filen orörd"] = a.read_bytes() == PDF_A
    resultat["nya filen har nya innehållet"] = ny.read_bytes() == b"%PDF-1.4 ny version"
    resultat["antal PDF:er i mappen"] = len(list(Path(tmp).glob("*.pdf")))

print("\nNedladdning (påhittad)")
for namn, varde in resultat.items():
    kontrollera(namn, varde, 3 if namn == "antal PDF:er i mappen" else True)

print(f"\n{godkanda}/{totalt} tester godkända")
sys.exit(0 if godkanda == totalt else 1)
