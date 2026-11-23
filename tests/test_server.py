"""
Testar webbappens API (app/server.py) mot befintlig data, utan API-anrop.
Kör: venv/bin/python tests/test_server.py   (kräver fastapi och httpx)
Testet ändrar inga data: bara läsningar, plus en tillfällig PDF som tas bort igen.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from fastapi.testclient import TestClient
except ImportError:
    sys.exit("Hoppar över: fastapi/httpx saknas (venv/bin/pip install -r requirements.txt).")
from app.server import app  # noqa: E402

c = TestClient(app)
godkanda = totalt = 0


def lika(namn, fick, vantat):
    global godkanda, totalt
    totalt += 1
    if fick == vantat:
        godkanda += 1
        print(f"  ✅ {namn}")
    else:
        print(f"  ❌ {namn}: fick {fick!r}, väntade {vantat!r}")


lika("startsidan", c.get("/").status_code, 200)
lika("app.js", c.get("/app.js").status_code, 200)
objekt = c.get("/api/objekt").json()
lika("listan är en lista", isinstance(objekt, list), True)
if objekt:
    stam = objekt[0]["stam"]
    d = c.get(f"/api/objekt/{stam}").json()
    lika("detalj har bedömning och lägenhet", {"bedomning", "lagenhet", "annons"} <= set(d), True)
    lika("nyckeltalen har vikt", all("tung" in r for r in d["bedomning"]["nyckeltal"]), True)
lika("okänt objekt → 404", c.get("/api/objekt/finnsinte").status_code, 404)
lika("sökväg med ../ avvisas", c.get("/api/pdf/..%2F..%2Fetc").status_code in (400, 404), True)
lika("ogiltigt id → 400", c.get("/api/pdf/a b").status_code, 400)
lika("ej PDF avvisas", c.post("/api/ladda-upp", content=b"hej").status_code, 400)
lika("http-länk avvisas", c.post("/api/forbered", json={"pdf_url": "http://x"}).status_code, 400)

# En ny PDF får aldrig extraheras (kosta pengar) utan bekräftelse
svar = c.post("/api/ladda-upp?filnamn=testfil.pdf", content=b"%PDF-1.4 test " + b"x" * 64).json()
lika("ny PDF är inte extraherad", svar["redan_extraherad"], False)
r = c.post("/api/analysera", json={"stam": svar["stam"]})
lika("analys utan bekräftelse → 402", (r.status_code, r.json().get("kostar")), (402, True))
(Path("data/pdfs") / f"{svar['stam']}.pdf").unlink()

# Ett drag med annonslänken – utan nätverk: Booli-sidorna och nedladdningen låtsas
import analysera  # noqa: E402
import booli  # noqa: E402
annons_html = ('<script type="application/ld+json">{"@type":"Product","offers":{"price":5495000}}</script>'
               '<a href="/bostadsrattsforening/1">f</a><p>Avgift</p><p>3 272 kr</p><p>Boarea</p><p>44 m²</p>')
forening_html = '<h3>Årsredovisning</h3><a href="https://documents.bcdn.se/a/b/A_rsredovisning.pdf">x</a>'
sidor = {"https://www.booli.se/bostad/1": annons_html, "https://www.booli.se/bostadsrattsforening/1": forening_html}
booli.hamta = lambda url, cookie=None: sidor[url]
befintlig = next(Path("data/pdfs").glob("*.pdf"), None)
if befintlig:
    analysera.ladda_ner = lambda url: befintlig
    r = c.post("/api/fran-annons", json={"annons_url": "https://www.booli.se/bostad/1"}).json()
    lika("ett drag: annonsen läst", (r["annons"]["pris"], r["annons"]["avgift"], r["annons"]["kvm"]), ("5495000", "3272", "44"))
    lika("ett drag: PDF förberedd", r["forberedd"]["stam"], befintlig.stem)
    sidor["https://www.booli.se/bostadsrattsforening/1"] = "<p>Logga in</p>"
    r = c.post("/api/fran-annons", json={"annons_url": "https://www.booli.se/bostad/1"}).json()
    lika("ett drag utan PDF: annonsen ändå med", (r["forberedd"], r["annons"]["kvm"], bool(r["meddelande"])), (None, "44", True))
lika("fel länk till fran-annons → 400", c.post("/api/fran-annons", json={"annons_url": "https://evil.example/1"}).status_code, 400)

print(f"\n{godkanda}/{totalt} godkända")
sys.exit(0 if godkanda == totalt else 1)
