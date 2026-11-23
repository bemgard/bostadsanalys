"""
Testar läsningen av Booli-sidor (booli.py) utan nätverk: små HTML-exempel, plus de
sparade sidorna i data/exempel/ om de finns.
Kör: python tests/test_booli.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import booli  # noqa: E402

godkanda = totalt = 0


def lika(namn, fick, vantat):
    global godkanda, totalt
    totalt += 1
    if fick == vantat:
        godkanda += 1
        print(f"  ✅ {namn}")
    else:
        print(f"  ❌ {namn}\n       väntat: {vantat!r}\n       fick:   {fick!r}")


ANNONS = """<html><head>
<script type="application/ld+json">{"@type":"Place","address":{"streetAddress":"Teknologgatan 9C"}}</script>
<script type="application/ld+json">{"@type":"Product","offers":{"@type":"Offer","price":5495000}}</script>
<script type="application/ld+json">{"@type":"BreadcrumbList","itemListElement":[
  {"item":"https://www.booli.se/sok"},{"item":"https://www.booli.se/bostadsrattsforening/12345"}]}</script>
<script>var annat = "Avgift";</script></head><body>
<div><p>Boarea</p><p>44 m²</p></div><div><p>Rum</p><p>2 rum</p></div>
<div><p>Avgift</p><p>3 272 kr/mån</p></div></body></html>"""

FORENING = """<html><body><h3>Energideklaration</h3>
<a href="https://documents.bcdn.se/aa/bb/111/Energideklaration.pdf?x=1">Ladda ner</a>
<h3>Årsredovisning</h3><a href="https://documents.bcdn.se/cc/dd/222/A_rsredovisning_2025.pdf?token=abc">Ladda ner</a>
</body></html>"""

print("Annonsen")
a = booli.las_annons(ANNONS, "https://www.booli.se/bostad/1")
lika("alla uppgifter", a, {"annons": "https://www.booli.se/bostad/1", "adress": "Teknologgatan 9C",
                           "pris": "5495000", "avgift": "3272", "rum": "2", "kvm": "44",
                           "forening_sokvag": "/bostadsrattsforening/12345"})
lika("text i <script> räknas inte som rubrik", booli.las_annons("<script>Avgift</script><p>1 kr</p>", "x")["avgift"], None)
lika("föreningslänk via vanlig länk", booli.las_annons('<a href="/bostadsrattsforening/9?a=1">x</a>', "x")["forening_sokvag"],
     "/bostadsrattsforening/9")
lika("konstig föreningslänk avvisas", booli.las_annons('<a href="/bostadsrattsforening/9/../../x">x</a>', "x")["forening_sokvag"], None)
lika("adress tvättas", booli.tvatta_adress("Gata 1'; rm -rf ~ $(x)"), "Gata 1 rm -rf x")
lika("ogiltigt pris → None", booli.heltal("Pris saknas"), None)
lika("decimal med komma", booli.decimaltal("63,5 m²"), "63.5")

print("\nFöreningssidan")
lika("årsredovisningen efter rubriken, utan parametrar", booli.las_forening_pdf(FORENING),
     "https://documents.bcdn.se/cc/dd/222/A_rsredovisning_2025.pdf")
lika("ingen årsredovisning → None", booli.las_forening_pdf("<h3>Stadgar</h3><a href='https://documents.bcdn.se/a/Stadgar.pdf'>x</a>"), None)
lika("länk på annan domän avvisas", booli.las_forening_pdf("<h3>Årsredovisning</h3><a href='https://evil.example/a.pdf'>x</a>"), None)
lika("reserv: filnamn med rsredovisning",
     booli.las_forening_pdf("<a href='https://documents.bcdn.se/a/b/A_rsredovisning_2024.pdf'>x</a>"),
     "https://documents.bcdn.se/a/b/A_rsredovisning_2024.pdf")

print("\nHela flödet (utan nätverk)")
sidor = {"https://www.booli.se/bostad/1": ANNONS, "https://www.booli.se/bostadsrattsforening/12345": FORENING}
booli.hamta = lambda url, cookie=None: sidor[url]
booli.booli_cookie = lambda: None
r = booli.fran_annons("https://www.booli.se/bostad/1?utm=x")
lika("PDF hittad", (r["pdf_url"], r["meddelande"], r["annons"]["pris"]),
     ("https://documents.bcdn.se/cc/dd/222/A_rsredovisning_2025.pdf", None, "5495000"))
sidor["https://www.booli.se/bostadsrattsforening/12345"] = "<p>Logga in för att se dokumenten</p>"
r = booli.fran_annons("https://www.booli.se/bostad/1")
lika("PDF saknas → annonsen ändå med, och ett meddelande", (r["pdf_url"], r["annons"]["kvm"], "inloggade" in r["meddelande"]),
     (None, "44", True))
try:
    booli.fran_annons("https://evil.example/bostad/1")
    lika("annan domän avvisas", False, True)
except booli.BooliFel:
    lika("annan domän avvisas", True, True)

# Sparade riktiga sidor (finns bara lokalt – data/ är inte i git)
exempel = Path(__file__).resolve().parent.parent / "data" / "exempel"
# Filnamn på macOS kan ha "ä" som två tecken (NFD) – jämför normaliserat
import unicodedata  # noqa: E402
filer = [f for f in exempel.glob("*.html")] if exempel.exists() else []
namn = lambda f: unicodedata.normalize("NFC", f.name)  # noqa: E731
annonsfil = next((f for f in filer if namn(f).startswith("Lägenhet till salu")), None)
foreningsfil = next((f for f in filer if namn(f).startswith("BRF ")), None)
if annonsfil and foreningsfil:
    print("\nSparade Booli-sidor")
    a = booli.las_annons(annonsfil.read_text(encoding="utf-8"), "https://www.booli.se/bostad/684022")
    lika("Norra Stationsgatan 117", (a["adress"], a["pris"], a["avgift"], a["rum"], a["kvm"]),
         ("Norra Stationsgatan 117", "5995000", "4648", "2", "63"))
    lika("Brf SKÅLEN: årsredovisningen", booli.las_forening_pdf(foreningsfil.read_text(encoding="utf-8")),
         "https://documents.bcdn.se/c0/39/6db004c20371/A_rsredovisning_2024_BRF_Ska_len_16-17.pdf")

print(f"\n{godkanda}/{totalt} godkända")
sys.exit(0 if godkanda == totalt else 1)
