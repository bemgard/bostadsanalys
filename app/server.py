"""
Webbappens backend – en tunn FastAPI-server runt den befintliga kedjan
(extract_report → bedomning → lagenhet). Ingen analyslogik finns här.

Data ligger i Supabase (se app/moln.py), inte i data/:
- varje anrop till /api/ kräver en inloggad användare (Supabase-JWT i Authorization-huvudet)
- hushållets objekt = rader i `annonser` (en uppladdad PDF utan annons är också ett objekt)
- årsredovisningar, extraktioner och bedömningar är en delad cache: samma PDF (kontrollsumma)
  extraheras aldrig två gånger, oavsett vem som laddade upp den

Regeln från CLAUDE.md gäller även här: extraktionen (Claude-API:t, ca 1–2 kr) körs bara när
användaren uttryckligen bekräftat kostnaden (bekrafta_kostnad = true, annars 402), och högst
MANADSTAK_EXTRAKTIONER gånger per användare och kalendermånad (annars 429).

Extraktionen tar ofta över en minut – längre än Netlifys proxy väntar – så den körs som ett
jobb i bakgrunden: /api/analysera svarar 202 med ett jobb-id och appen frågar /api/jobb/<id>.

Lokalt (från projektmappen, med Supabase-nycklarna i .env):
    venv/bin/python -m uvicorn app.server:app --port 8000
"""

import base64
import hashlib
import io
import os
import re
import sys
import threading
import urllib.error
import urllib.request
import uuid
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from fastapi import Body, Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROT))
os.chdir(ROT)
load_dotenv()

import analysera  # noqa: E402
import bedomning  # noqa: E402
import booli  # noqa: E402
import export_excel  # noqa: E402
import extract_report  # noqa: E402
import kriterier as k  # noqa: E402
from lagenhet import annonsnyckeltal  # noqa: E402

from app.moln import Moln, MolnFel  # noqa: E402

MAX_PDF_BYTES = 50 * 1024 * 1024
MAX_HTML_TECKEN = 6_000_000
STOCKHOLM = ZoneInfo("Europe/Stockholm")
UUID_MONSTER = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def manadstak() -> int:
    try:
        return int(os.getenv("MANADSTAK_EXTRAKTIONER", "10"))
    except ValueError:
        return 10


app = FastAPI(title="Bostadsanalys")

# Molnklienten skapas vid första anropet (testerna byter ut den mot en låtsasvariant)
_moln = None


def moln():
    global _moln
    if _moln is None:
        _moln = Moln.fran_env()
    return _moln


@app.exception_handler(MolnFel)
def molnfel(_request, e: MolnFel):
    print(f"Molnfel: {e}", file=sys.stderr)
    return JSONResponse(status_code=502, content={"detail": "Databasen svarade inte som väntat. Försök igen."})


# --- Inloggning --------------------------------------------------------------

class Anv(SimpleNamespace):
    """Inloggad användare: id, email, token, hushall_id, profil."""


def inloggad(request: Request) -> Anv:
    huvud = request.headers.get("authorization", "")
    if not huvud.lower().startswith("bearer "):
        raise HTTPException(401, "Logga in först.")
    token = huvud[7:].strip()
    m = moln()
    anv = m.anvandare(token)
    if anv is None:
        raise HTTPException(401, "Inloggningen har gått ut. Logga in igen.")
    inst = m.installningar(anv["id"])
    if not inst or not inst.get("hushall_id"):
        raise HTTPException(403, "Kontot saknar hushåll. Be Calle lägga till dig.")
    return Anv(id=anv["id"], email=anv.get("email"), token=token,
               hushall_id=inst["hushall_id"], profil=inst.get("koparprofil") or k.STANDARD_KOPARPROFIL)


# --- Hjälpfunktioner ---------------------------------------------------------

def kor(funktion, *args, **kwargs):
    """Kör en funktion ur kedjan. Kedjan avslutar med sys.exit("meddelande") vid fel –
    det blir ett 400-svar med meddelandet i stället för att servern stängs."""
    try:
        return funktion(*args, **kwargs)
    except SystemExit as e:
        raise HTTPException(400, str(e.code) if e.code not in (None, 0) else "Okänt fel")


def kontrollera_id(x: str) -> str:
    if not UUID_MONSTER.match(x or ""):
        raise HTTPException(400, "Ogiltigt objekt-id.")
    return x


def validera_profil(profil):
    """None → standard. Okänd profil → 400 med namnen som finns."""
    try:
        k.los_profil(profil)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return profil or k.STANDARD_KOPARPROFIL


def med_vikter(b):
    """Lägg till vikt och om nyckeltalet är tungt, för att gruppera bubblorna."""
    _, vikter = k.los_profil(b.get("koparprofil"))
    for r in b["nyckeltal"]:
        r["vikt"] = vikter.get(r["nyckeltal"], k.UTSLAG_VIKT_STANDARD)
        r["tung"] = r["vikt"] >= k.UTSLAG_TUNG_VIKT
    return b


def varde(data, nyckel):
    x = (data or {}).get(nyckel)
    return x.get("varde") if isinstance(x, dict) else None


def bedom_och_spara(dok: dict, profil: str, idag: date | None = None) -> dict:
    """Bedöm en extraherad årsredovisning (gratis, ren Python) och spara i cachen."""
    idag = idag or date.today()
    resultat = kor(bedomning.bedom, dok["extraherad"], idag, profil)
    moln().spara_bedomning(dok["id"], profil, idag.isoformat(), resultat)
    return resultat


def bedomningar_for(dokument: dict[str, dict], profil: str) -> dict[str, dict]:
    """Bedömning per dokument för profilen: senaste sparade, annars bedöms den nu (gratis)."""
    extraherade = [d for d in dokument.values() if d.get("extraherad")]
    sparade = moln().senaste_bedomningar([d["id"] for d in extraherade], profil)
    ut = {}
    for d in extraherade:
        rad = sparade.get(d["id"])
        ut[d["id"]] = rad["resultat"] if rad else bedom_och_spara(d, profil)
    return ut


def till_lagenhet(a: dict | None) -> dict | None:
    """Annonsraden i den form lagenhet.py och gränssnittet väntar sig."""
    if not a:
        return None
    return {n: a.get(n) for n in ("annons_url", "adress", "pris", "avgift", "rum", "kvm", "org_nr")}


def objekt_rad(a: dict, b: dict) -> dict:
    t = annonsnyckeltal(till_lagenhet(a), b)
    return {
        "id": a["id"],
        "adress": a.get("adress"),
        "annons_url": a.get("annons_url"),
        "forening": b.get("forening"),
        "utslag": b.get("utslag"),
        "poang": b.get("poang"),
        "datakvalitet": b.get("datakvalitet"),
        "motivering": b.get("motivering"),
        "bedomd": b.get("idag"),
        "rakenskapsar_slut": b.get("rakenskapsar_slut"),
        **{n: t[n] for n in ("pris", "avgift", "rum", "kvm", "skuldjusterat_pris_per_kvm", "vantad_avgift")},
    }


def hushallets_objekt(anv: Anv):
    """[(annons, bedömning)] för hushållet, sorterade som i Excel: GÅ VIDARE först, högst poäng först."""
    annonser = [a for a in moln().annonser(anv.token, anv.hushall_id) if a.get("dokument_id")]
    dokument = moln().dokument(sorted({a["dokument_id"] for a in annonser}))
    bed = bedomningar_for(dokument, anv.profil)
    rader = [(a, bed[a["dokument_id"]]) for a in annonser if a["dokument_id"] in bed]
    return sorted(rader, key=lambda r: export_excel.sorteringsnyckel(r[1]))


def eget_objekt(anv: Anv, annons_id: str) -> tuple[dict, dict]:
    """Hushållets objekt och dess dokument. 404 om det inte finns – eller tillhör någon annan."""
    a = moln().annons(anv.token, kontrollera_id(annons_id))  # RLS: bara det egna hushållets rader
    if a is None or a.get("hushall_id") != anv.hushall_id or not a.get("dokument_id"):
        raise HTTPException(404, "Objektet finns inte.")
    dok = moln().dokument([a["dokument_id"]]).get(a["dokument_id"])
    if dok is None:
        raise HTTPException(404, "Årsredovisningen finns inte.")
    return a, dok


def detalj(anv: Anv, annons_id: str, profil: str | None = None):
    a, dok = eget_objekt(anv, annons_id)
    if not dok.get("extraherad"):
        raise HTTPException(409, "Årsredovisningen är inte läst än.")
    profil = profil or anv.profil
    b = bedomningar_for({dok["id"]: dok}, profil)[dok["id"]]
    return {
        "id": a["id"],
        "bedomning": med_vikter(b),
        "annons": till_lagenhet(a),
        "lagenhet": annonsnyckeltal(till_lagenhet(a), b),
        "pdf_finns": bool(dok.get("storage_sokvag")),
        "marknadsranta_procent": k.MARKNADSRANTA_FORENINGSLAN_PROCENT,
    }


def forbered(innehall: bytes, anv: Anv) -> dict:
    """PDF:en finns i minnet: spara den i molnet (om den är ny) och säg om den redan är läst."""
    if len(innehall) > MAX_PDF_BYTES:
        raise HTTPException(413, "Filen är för stor (max 50 MB).")
    if not innehall.startswith(b"%PDF"):
        raise HTTPException(400, "Filen är ingen PDF.")
    sha = hashlib.sha256(innehall).hexdigest()
    dok = moln().skapa_dokument(sha, innehall, anv.id)  # samma PDF finns redan → återanvänds
    return {"dokument_id": dok["id"], "redan_extraherad": bool(dok.get("extraherad"))}


def ladda_ner_pdf(url: str) -> bytes:
    """Hämta en PDF från en https-länk till minnet (gratis). Högst 50 MB."""
    if not url.startswith("https://"):
        raise HTTPException(400, "Länken måste börja med https://")
    try:
        begaran = urllib.request.Request(url, headers={"User-Agent": "bostadsanalys/1.0"})
        with urllib.request.urlopen(begaran, timeout=60) as svar:
            innehall = svar.read(MAX_PDF_BYTES + 1)
    except urllib.error.HTTPError as e:
        raise HTTPException(400, f"Nedladdningen misslyckades: servern svarade {e.code}.")
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise HTTPException(400, f"Kunde inte hämta länken: {getattr(e, 'reason', e)}")
    if not innehall.startswith(b"%PDF"):
        raise HTTPException(400, "Det nedladdade är ingen PDF (kanske en felsida eller inloggning).")
    return innehall


def manadens_start() -> str:
    nu = datetime.now(STOCKHOLM)
    return nu.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()


def kostnad_ore(usage) -> int | None:
    """Kostnaden i öre om priserna är satta (KOSTNAD_ORE_PER_MTOK_IN/_UT), annars None."""
    try:
        pris_in = float(os.environ["KOSTNAD_ORE_PER_MTOK_IN"])
        pris_ut = float(os.environ["KOSTNAD_ORE_PER_MTOK_UT"])
    except (KeyError, ValueError):
        return None
    return round(usage.input_tokens / 1e6 * pris_in + usage.output_tokens / 1e6 * pris_ut)


# --- Jobb (extraktionen i bakgrunden) -------------------------------------------

# En extraktion i taget, så att samma PDF aldrig extraheras (och betalas) två gånger samtidigt
extraktion_las = threading.Lock()
jobb: dict[str, dict] = {}
jobb_las = threading.Lock()


def satt_jobb(jobb_id, **falt):
    with jobb_las:
        jobb[jobb_id].update(falt)


def extrahera_jobb(jobb_id: str, anv: Anv, dokument_id: str, annons: dict | None, profil: str):
    try:
        with extraktion_las:
            dok = moln().dokument([dokument_id])[dokument_id]
            if not dok.get("extraherad"):  # någon annan kan ha hunnit före – då är det gratis
                pdf = moln().pdf_innehall(dok)
                try:
                    data, usage = extract_report.extrahera_data(base64.standard_b64encode(pdf).decode(), dok["pdf_sha256"][:12])
                except SystemExit as e:
                    # Räknas mot taket även när svaret var ogiltigt – anropet kan ha kostat
                    moln().logga_extraktion(anv.id, dokument_id, None)
                    raise RuntimeError(str(e.code))
                moln().logga_extraktion(anv.id, dokument_id, kostnad_ore(usage))
                moln().spara_extraktion(dokument_id, data, varde(data, "organisationsnummer"),
                                        varde(data, "foreningens_namn"), varde(data, "byggnadsar"))
                dok = moln().dokument([dokument_id])[dokument_id]
        resultat = bedom_och_spara(dok, profil)
        annons_id = spara_objekt(anv, dok, annons, resultat.get("org_nr"))
        satt_jobb(jobb_id, status="klar", id=annons_id)
    except HTTPException as e:
        satt_jobb(jobb_id, status="fel", fel=e.detail)
    except Exception as e:  # noqa: BLE001 – felet visas för användaren i appen
        print(f"Jobb {jobb_id} misslyckades: {e!r}", file=sys.stderr)
        satt_jobb(jobb_id, status="fel", fel=str(e) or "Analysen misslyckades.")


def spara_objekt(anv: Anv, dok: dict, annons: dict | None, org_nr: str | None) -> str:
    """Lägg till objektet i hushållet, eller uppdatera det om samma annons/PDF redan finns.
    Uppgifter som inte angavs denna gång behåller sitt tidigare värde."""
    annons = annons or {}
    url = annons.get("annons_url")
    falt = {n: annons.get(n) for n in ("annons_url", "adress", "pris", "avgift", "rum", "kvm")}
    falt.update({"org_nr": org_nr, "dokument_id": dok["id"]})
    befintlig = moln().hitta_annons(anv.token, anv.hushall_id, url, dok["id"])
    if befintlig:
        andrat = {n: v for n, v in falt.items() if v is not None}
        andrat["arkiverad"] = False
        return moln().uppdatera_annons(anv.token, befintlig["id"], andrat)["id"]
    return moln().skapa_annons(anv.token, {**falt, "hushall_id": anv.hushall_id, "skapad_av": anv.id})["id"]


# --- API ---------------------------------------------------------------------

@app.get("/api/halsa")
def halsa():
    """Utan inloggning – för Render och för att väcka servern."""
    return {"ok": True}


@app.get("/api/jag")
def jag(anv: Anv = Depends(inloggad)):
    anvanda = moln().extraktioner_sedan(anv.id, manadens_start())
    return {"email": anv.email, "profil": anv.profil, "extraktioner_kvar": max(0, manadstak() - anvanda),
            "manadstak": manadstak()}


@app.get("/api/profiler")
def lista_profiler(anv: Anv = Depends(inloggad)):
    """Köparprofilerna för väljaren och användarens valda profil."""
    return {
        "standard": k.STANDARD_KOPARPROFIL,
        "vald": anv.profil,
        "profiler": [
            {"id": pid, "namn": p["namn"], "horisont": p["renoveringshorisont_ar"]}
            for pid, p in k.KOPARPROFILER.items()
        ],
    }


@app.put("/api/installningar")
def spara_installningar(koparprofil: str = Body(..., embed=True), anv: Anv = Depends(inloggad)):
    """Spara användarens köpartyp (gäller i mobilen och på datorn)."""
    moln().satt_profil(anv.id, validera_profil(koparprofil))
    return {"profil": koparprofil}


@app.get("/api/objekt")
def lista_objekt(anv: Anv = Depends(inloggad)):
    return [objekt_rad(a, b) for a, b in hushallets_objekt(anv)]


@app.get("/api/objekt/{annons_id}")
def hamta_objekt(annons_id: str, anv: Anv = Depends(inloggad)):
    return detalj(anv, annons_id)


class Forbered(BaseModel):
    pdf_url: str


@app.post("/api/forbered")
def forbered_lank(data: Forbered, anv: Anv = Depends(inloggad)):
    """Hämta årsredovisningen från en länk (gratis). Extraherar inget."""
    return forbered(ladda_ner_pdf(data.pdf_url.strip()), anv)


@app.post("/api/ladda-upp")
async def ladda_upp(request: Request, anv: Anv = Depends(inloggad)):
    """Ta emot en PDF (rå bytes i anropet). Extraherar inget."""
    innehall = await request.body()
    return forbered(innehall, anv)


class FranAnnons(BaseModel):
    annons_url: str


def med_pdf(resultat: dict, anv: Anv) -> dict:
    resultat["forberedd"] = forbered(ladda_ner_pdf(resultat["pdf_url"]), anv) if resultat["pdf_url"] else None
    return resultat


@app.post("/api/fran-annons")
def fran_annons(data: FranAnnons, anv: Anv = Depends(inloggad)):
    """Läs Booli-annonsen från servern (utan tillägget). Gratis – extraherar inget.
    Årsredovisningen visas bara för inloggade på Booli, så utan tillägget hittas den sällan."""
    try:
        resultat = booli.fran_annons(data.annons_url)
    except booli.BooliFel as e:
        raise HTTPException(400, str(e))
    return med_pdf(resultat, anv)


class FranHtml(BaseModel):
    annons_url: str
    annons_html: str
    forening_html: str | None = None
    forening_url: str | None = None
    inloggad: bool | None = None


@app.post("/api/fran-html")
def fran_html(data: FranHtml, anv: Anv = Depends(inloggad)):
    """Som /api/fran-annons, men sidorna har hämtats av Chrome-tillägget i användarens inloggade
    webbläsare. Servern tolkar dem med samma kod (booli.py) och hämtar PDF:en. Gratis."""
    if len(data.annons_html) > MAX_HTML_TECKEN or len(data.forening_html or "") > MAX_HTML_TECKEN:
        raise HTTPException(413, "Sidan är för stor.")
    try:
        resultat = booli.tolka_sidor(data.annons_url, data.annons_html, data.forening_html, data.forening_url)
    except booli.BooliFel as e:
        raise HTTPException(400, str(e))
    if not resultat["pdf_url"] and data.inloggad is False:
        resultat["meddelande"] = ("Du verkar inte vara inloggad på Booli i Chrome. Logga in på booli.se "
                                  "och dra in annonsen igen.")
    return med_pdf(resultat, anv)


class Annons(BaseModel):
    annons: str | None = None
    adress: str | None = None
    pris: str | None = None
    avgift: str | None = None
    rum: str | None = None
    kvm: str | None = None


class Analysera(BaseModel):
    dokument_id: str
    bekrafta_kostnad: bool = False
    annons: Annons | None = None
    profil: str | None = None


@app.post("/api/analysera")
def analysera_objekt(data: Analysera, anv: Anv = Depends(inloggad)):
    """Redan läst: bedöm och spara objektet direkt (200). Inte läst: kräver bekräftelse (402)
    och plats under månadstaket (429); startar då ett jobb (202) som appen frågar efter."""
    dokument_id = kontrollera_id(data.dokument_id)
    dok = moln().dokument([dokument_id]).get(dokument_id)
    if dok is None:
        raise HTTPException(404, "Årsredovisningen finns inte – ladda upp eller ange länken igen.")
    profil = validera_profil(data.profil or anv.profil)

    # Validera annonsuppgifterna innan något kostar pengar
    annons = None
    if data.annons:
        falt = {n: (v.strip() if isinstance(v, str) and v.strip() else None)
                for n, v in data.annons.model_dump().items()}
        annons = kor(analysera.validera_annons, SimpleNamespace(**falt))

    if dok.get("extraherad"):
        resultat = bedom_och_spara(dok, profil)
        return {"status": "klar", "id": spara_objekt(anv, dok, annons, resultat.get("org_nr"))}

    if not data.bekrafta_kostnad:
        return JSONResponse(status_code=402, content={
            "detail": "Extraktionen kostar ca 1–2 kr och kräver bekräftelse.", "kostar": True})
    if moln().extraktioner_sedan(anv.id, manadens_start()) >= manadstak():
        raise HTTPException(429, f"Du har använt månadens {manadstak()} analyser av nya årsredovisningar. "
                                 "Redan lästa årsredovisningar går fortfarande att analysera.")
    with jobb_las:
        if any(j["dokument_id"] == dokument_id and j["status"] == "pagar" for j in jobb.values()):
            raise HTTPException(409, "Årsredovisningen läses redan. Vänta en stund.")
        jobb_id = uuid.uuid4().hex
        jobb[jobb_id] = {"user_id": anv.id, "dokument_id": dokument_id, "status": "pagar"}
    threading.Thread(target=extrahera_jobb, args=(jobb_id, anv, dokument_id, annons, profil), daemon=True).start()
    return JSONResponse(status_code=202, content={"status": "pagar", "jobb": jobb_id})


@app.get("/api/jobb/{jobb_id}")
def hamta_jobb(jobb_id: str, anv: Anv = Depends(inloggad)):
    with jobb_las:
        j = jobb.get(jobb_id)
        if j is None or j["user_id"] != anv.id:
            raise HTTPException(404, "Jobbet finns inte (servern kan ha startats om). Försök igen.")
        return {n: j.get(n) for n in ("status", "id", "fel")}


@app.post("/api/objekt/{annons_id}/bedom-om")
def bedom_om(annons_id: str, profil: str | None = Body(None, embed=True), anv: Anv = Depends(inloggad)):
    """Bedöm om med dagens datum och nuvarande kriterier, valfritt med en annan köparprofil
    (som då blir användarens val). Gratis – inget API-anrop."""
    _, dok = eget_objekt(anv, annons_id)
    if not dok.get("extraherad"):
        raise HTTPException(409, "Årsredovisningen är inte läst än.")
    profil = validera_profil(profil or anv.profil)
    if profil != anv.profil:
        moln().satt_profil(anv.id, profil)
    bedom_och_spara(dok, profil)
    return detalj(anv, annons_id, profil)


@app.post("/api/objekt/{annons_id}/arkivera")
def arkivera(annons_id: str, anv: Anv = Depends(inloggad)):
    """Dölj objektet för hushållet. Inget raderas – årsredovisningen och analysen ligger kvar."""
    a, _ = eget_objekt(anv, annons_id)
    moln().uppdatera_annons(anv.token, a["id"], {"arkiverad": True})
    return {"arkiverad": a["id"]}


@app.get("/api/pdf/{annons_id}")
def hamta_pdf(annons_id: str, anv: Anv = Depends(inloggad)):
    """En kortlivad signerad länk till årsredovisningen (bucketen är privat)."""
    _, dok = eget_objekt(anv, annons_id)
    return {"url": moln().signerad_lank(dok, 300)}


@app.get("/api/export.xlsx")
def exportera_excel(anv: Anv = Depends(inloggad)):
    """Hushållets objekt som Excel, byggd i minnet med samma kod som export_excel.py."""
    from openpyxl import Workbook
    rader = hushallets_objekt(anv)
    if not rader:
        raise HTTPException(404, "Inga objekt att exportera.")
    annonser = [till_lagenhet(a) for a, _ in rader]
    unika = {}
    for a, b in rader:
        unika.setdefault(a["dokument_id"], {**b, "_stam": a["dokument_id"]})
    bedomningar = sorted(unika.values(), key=export_excel.sorteringsnyckel)
    bok = Workbook()
    oversikt = bok.active
    oversikt.title = "Översikt"
    export_excel.bygg_oversikt(oversikt, bedomningar, annonser)
    export_excel.bygg_fragor(bok.create_sheet("Frågor till mäklaren"), bedomningar)
    ut = io.BytesIO()
    bok.save(ut)
    ut.seek(0)
    return StreamingResponse(ut, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": 'attachment; filename="bostadsanalys.xlsx"'})


# Gränssnittet (statiska filer) för lokal körning – i molnet serverar Netlify dem
app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
