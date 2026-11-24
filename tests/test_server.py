"""
Testar webbappens API (app/server.py) mot en låtsas-Supabase i minnet – inga nätverksanrop,
inga API-anrop till Claude (extraktionen byts ut mot en färdig extraktion ur data/extracted/).
Låtsasvarianten härmar RLS: annonser syns bara för medlemmar i hushållet.
Kör: venv/bin/python tests/test_server.py   (kräver fastapi och httpx)
"""

import hashlib
import json
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from fastapi.testclient import TestClient
except ImportError:
    sys.exit("Hoppar över: fastapi/httpx saknas (venv/bin/pip install -r requirements.txt).")
import app.server as server  # noqa: E402
import booli  # noqa: E402
import extract_report  # noqa: E402

godkanda = totalt = 0


def lika(namn, fick, vantat):
    global godkanda, totalt
    totalt += 1
    if fick == vantat:
        godkanda += 1
        print(f"  ✅ {namn}")
    else:
        print(f"  ❌ {namn}: fick {fick!r}, väntade {vantat!r}")


class LatsasMoln:
    """Samma metoder som app.moln.Moln, i minnet."""

    def __init__(self):
        self.tokens, self.inst, self.medlem = {}, {}, set()
        self.dok, self.bed, self.ann, self.logg, self.pdf = {}, {}, {}, [], {}

    def ny_anvandare(self, namn, hushall=None):
        uid, hushall = str(uuid.uuid4()), hushall or str(uuid.uuid4())
        self.tokens[f"token-{namn}"] = {"id": uid, "email": f"{namn}@exempel.se"}
        self.inst[uid] = {"hushall_id": hushall, "koparprofil": "par"}
        self.medlem.add((hushall, uid))
        return {"Authorization": f"Bearer token-{namn}"}, hushall

    def _uid(self, token):
        return self.tokens[token]["id"]

    def _ser(self, token, a):  # RLS: ar_medlem(hushall_id)
        return (a["hushall_id"], self._uid(token)) in self.medlem

    def anvandare(self, token):
        return self.tokens.get(token)

    def installningar(self, uid):
        return self.inst.get(uid)

    def satt_profil(self, uid, profil):
        self.inst[uid]["koparprofil"] = profil

    def dokument_med_hash(self, sha):
        return next((d for d in self.dok.values() if d["pdf_sha256"] == sha), None)

    def dokument(self, ids):
        return {i: dict(self.dok[i]) for i in ids if i in self.dok}

    def skapa_dokument(self, sha, innehall, uid):
        d = self.dokument_med_hash(sha)
        if d:
            return d
        d = {"id": str(uuid.uuid4()), "pdf_sha256": sha, "storage_sokvag": f"{sha}.pdf", "extraherad": None}
        self.dok[d["id"]], self.pdf[d["storage_sokvag"]] = d, innehall
        return d

    def pdf_innehall(self, d):
        return self.pdf[d["storage_sokvag"]]

    def signerad_lank(self, d, sek=300):
        return f"https://signerad.exempel/{d['storage_sokvag']}?giltig={sek}"

    def spara_extraktion(self, did, data, org_nr, namn, ar):
        self.dok[did].update(extraherad=data, org_nr=org_nr)

    def logga_extraktion(self, uid, did, ore):
        self.logg.append(uid)

    def extraktioner_sedan(self, uid, sedan):
        return self.logg.count(uid)

    def senaste_bedomningar(self, ids, profil):
        ut = {}
        for (did, p, idag), r in sorted(self.bed.items(), key=lambda x: x[0][2], reverse=True):
            if did in ids and p == profil:
                ut.setdefault(did, {"resultat": r})
        return ut

    def spara_bedomning(self, did, profil, idag, resultat):
        self.bed[(did, profil, idag)] = json.loads(json.dumps(resultat))

    def annonser(self, token, hushall, arkiverade=False):
        return [dict(a) for a in self.ann.values()
                if self._ser(token, a) and a["hushall_id"] == hushall and a["arkiverad"] == arkiverade]

    def annons(self, token, aid):
        a = self.ann.get(aid)
        return dict(a) if a and self._ser(token, a) else None

    def hitta_annons(self, token, hushall, url, did):
        for a in self.ann.values():
            if self._ser(token, a) and a["hushall_id"] == hushall and (
                    a["annons_url"] == url if url else (a["annons_url"] is None and a["dokument_id"] == did)):
                return dict(a)
        return None

    def skapa_annons(self, token, falt):
        assert (falt["hushall_id"], self._uid(token)) in self.medlem, "RLS: fel hushåll"
        a = {"id": str(uuid.uuid4()), "arkiverad": False, **falt}
        self.ann[a["id"]] = a
        return dict(a)

    def uppdatera_annons(self, token, aid, falt):
        assert self._ser(token, self.ann[aid]), "RLS: fel hushåll"
        self.ann[aid].update(falt)
        return dict(self.ann[aid])


m = LatsasMoln()
server._moln = m
c = TestClient(server.app)
calle, hushall = m.ny_anvandare("calle")
sambo, _ = m.ny_anvandare("sambo", hushall)
van, _ = m.ny_anvandare("van")

# --- Inloggning ---
lika("hälsa utan inloggning", c.get("/api/halsa").status_code, 200)
lika("utan token → 401", c.get("/api/objekt").status_code, 401)
lika("okänd token → 401", c.get("/api/objekt", headers={"Authorization": "Bearer fel"}).status_code, 401)
lika("tom lista", c.get("/api/objekt", headers=calle).json(), [])
lika("jag: tak och kvar", {n: c.get("/api/jag", headers=calle).json()[n] for n in ("manadstak", "extraktioner_kvar")},
     {"manadstak": 10, "extraktioner_kvar": 10})
lika("startsidan (lokalt)", c.get("/").status_code, 200)

# --- Uppladdning och kostnadsspärr ---
lika("ej PDF avvisas", c.post("/api/ladda-upp", content=b"hej", headers=calle).status_code, 400)
lika("http-länk avvisas", c.post("/api/forbered", json={"pdf_url": "http://x"}, headers=calle).status_code, 400)
pdf = b"%PDF-1.4 test " + b"x" * 64
svar = c.post("/api/ladda-upp", content=pdf, headers=calle).json()
lika("ny PDF är inte extraherad", svar["redan_extraherad"], False)
lika("samma PDF igen → samma dokument", c.post("/api/ladda-upp", content=pdf, headers=sambo).json()["dokument_id"],
     svar["dokument_id"])
r = c.post("/api/analysera", json={"dokument_id": svar["dokument_id"]}, headers=calle)
lika("analys utan bekräftelse → 402", (r.status_code, r.json().get("kostar")), (402, True))
lika("ogiltigt id → 400", c.post("/api/analysera", json={"dokument_id": "../x"}, headers=calle).status_code, 400)

m.logg = [m.tokens["token-calle"]["id"]] * 10
r = c.post("/api/analysera", json={"dokument_id": svar["dokument_id"], "bekrafta_kostnad": True}, headers=calle)
lika("över månadstaket → 429", r.status_code, 429)
m.logg = []

# --- Extraktion som jobb (Claude byts ut mot en färdig extraktion) ---
facit = Path("data/extracted/astrea4_2024.json")
if not facit.exists():
    print("  (hoppar över jobbtesterna: data/extracted/astrea4_2024.json saknas)")
else:
    extraktion = json.loads(facit.read_text(encoding="utf-8"))
    anrop = []

    def latsas_extrahera(pdf_b64, namn="", rafil=None):
        anrop.append(namn)
        return extraktion, SimpleNamespace(input_tokens=1000, output_tokens=100)

    extract_report.extrahera_data = latsas_extrahera
    annons = {"annons": "https://www.booli.se/bostad/4368716", "adress": "Teknologgatan 9C",
              "pris": "5495000", "avgift": "3272", "rum": "2", "kvm": "44"}
    r = c.post("/api/analysera", json={"dokument_id": svar["dokument_id"], "bekrafta_kostnad": True,
                                       "annons": annons}, headers=calle)
    lika("bekräftad → 202 med jobb", (r.status_code, r.json()["status"]), (202, "pagar"))
    jobb_id = r.json()["jobb"]
    lika("annans jobb syns inte", c.get(f"/api/jobb/{jobb_id}", headers=van).status_code, 404)
    for _ in range(50):
        j = c.get(f"/api/jobb/{jobb_id}", headers=calle).json()
        if j["status"] != "pagar":
            break
        time.sleep(0.05)
    lika("jobbet klart", j["status"], "klar")
    objekt_id = j["id"]
    lika("en extraktion, loggad", (len(anrop), len(m.logg)), (1, 1))

    # Samma PDF igen (även från annan användare) → gratis, direkt
    r = c.post("/api/analysera", json={"dokument_id": svar["dokument_id"]}, headers=van)
    lika("redan läst → 200 utan bekräftelse", (r.status_code, r.json()["status"]), (200, "klar"))
    van_id = r.json()["id"]
    lika("fortfarande en extraktion", len(anrop), 1)

    # --- Hushåll ---
    lista = c.get("/api/objekt", headers=calle).json()
    lika("calle ser objektet med annonsdata", [(o["id"], o["pris"], o["adress"]) for o in lista],
         [(objekt_id, 5495000, "Teknologgatan 9C")])
    lika("sambon ser samma objekt", [o["id"] for o in c.get("/api/objekt", headers=sambo).json()], [objekt_id])
    lika("vännen ser bara sitt", [o["id"] for o in c.get("/api/objekt", headers=van).json()], [van_id])
    lika("vännen når inte calles objekt", c.get(f"/api/objekt/{objekt_id}", headers=van).status_code, 404)
    lika("vännen får ingen PDF-länk till calles objekt", c.get(f"/api/pdf/{objekt_id}", headers=van).status_code, 404)
    lika("vännen kan inte arkivera calles objekt",
         c.post(f"/api/objekt/{objekt_id}/arkivera", headers=van).status_code, 404)

    d = c.get(f"/api/objekt/{objekt_id}", headers=sambo).json()
    lika("detalj har bedömning och lägenhet", {"bedomning", "lagenhet", "annons"} <= set(d), True)
    lika("nyckeltalen har vikt", all("tung" in r for r in d["bedomning"]["nyckeltal"]), True)
    lika("PDF via signerad länk", c.get(f"/api/pdf/{objekt_id}", headers=calle).json()["url"].startswith("https://signerad"), True)

    # Samma annons igen → samma objekt, uppdaterat
    r = c.post("/api/analysera", json={"dokument_id": svar["dokument_id"],
                                       "annons": {**annons, "pris": "5395000"}}, headers=sambo)
    lika("samma annons → samma objekt", r.json()["id"], objekt_id)
    lika("priset uppdaterat", c.get(f"/api/objekt/{objekt_id}", headers=calle).json()["lagenhet"]["pris"], 5395000)

    # Köpartyp
    r = c.post(f"/api/objekt/{objekt_id}/bedom-om", json={"profil": "barnfamilj"}, headers=calle)
    if r.status_code == 400:  # profilnamnen kan ändras i kriterier.py
        andra = next(p["id"] for p in c.get("/api/profiler", headers=calle).json()["profiler"] if p["id"] != "par")
        r = c.post(f"/api/objekt/{objekt_id}/bedom-om", json={"profil": andra}, headers=calle)
    lika("bedöm om med annan köpartyp", r.status_code, 200)
    lika("köpartypen sparas för användaren", c.get("/api/profiler", headers=calle).json()["vald"] != "par", True)
    lika("okänd köpartyp → 400",
         c.put("/api/installningar", json={"koparprofil": "okänd"}, headers=calle).status_code, 400)

    r = c.get("/api/export.xlsx", headers=calle)
    lika("Excel-export", (r.status_code, r.content[:2]), (200, b"PK"))

    lika("arkivera", c.post(f"/api/objekt/{objekt_id}/arkivera", headers=sambo).status_code, 200)
    lika("arkiverat syns inte", c.get("/api/objekt", headers=calle).json(), [])

# --- Tillägget ---
annons_html = ('<script type="application/ld+json">{"@type":"Product","offers":{"price":5495000}}</script>'
               '<a href="/bostadsrattsforening/1">f</a><p>Avgift</p><p>3 272 kr</p><p>Boarea</p><p>44 m²</p>')
forening_html = '<h3>Årsredovisning</h3><a href="https://documents.bcdn.se/a/b/A_rsredovisning.pdf">x</a>'
server.ladda_ner_pdf = lambda url: b"%PDF-1.4 tillagg"
r = c.post("/api/fran-html", headers=calle, json={
    "annons_url": "https://www.booli.se/bostad/1", "annons_html": annons_html, "forening_html": forening_html,
    "forening_url": "https://www.booli.se/bostadsrattsforening/1"}).json()
lika("tillägget: sidorna tolkas och PDF:en sparas",
     (r["annons"]["pris"], r["forberedd"]["dokument_id"] == m.dokument_med_hash(
         hashlib.sha256(b"%PDF-1.4 tillagg").hexdigest())["id"]), ("5495000", True))
r = c.post("/api/fran-html", headers=calle, json={
    "annons_url": "https://www.booli.se/bostad/1", "annons_html": annons_html, "forening_html": forening_html,
    "forening_url": "https://www.booli.se/bostadsrattsforening/2"})
lika("tillägget läste fel förening → 400", (r.status_code, "fel föreningssida" in r.json()["detail"]), (400, True))
lika("tillägget: fel annonslänk → 400", c.post("/api/fran-html", headers=calle, json={
    "annons_url": "https://evil.example/1", "annons_html": ""}).status_code, 400)
lika("fran-html kräver inloggning", c.post("/api/fran-html", json={
    "annons_url": "https://www.booli.se/bostad/1", "annons_html": ""}).status_code, 401)
_ = booli  # används indirekt via servern

print(f"\n{godkanda}/{totalt} godkända")
sys.exit(0 if godkanda == totalt else 1)
