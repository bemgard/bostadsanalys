"""
Webbgränssnittet för bostadsanalysen – en tunn FastAPI-server runt den befintliga kedjan
(analysera.py → extract_report.py → bedomning.py). Ingen analyslogik finns här.

Kör från projektmappen:
    venv/bin/python -m uvicorn app.server:app --port 8000
och öppna http://localhost:8000

Regeln från CLAUDE.md gäller även här: extraktionen (Claude-API:t, ca 1–2 kr) körs bara
när användaren uttryckligen bekräftat kostnaden i gränssnittet (bekrafta_kostnad = true).
Servern lyssnar bara på den egna datorn (127.0.0.1) och har ingen inloggning.
"""

import hashlib
import json
import os
import re
import shutil
import sys
import threading
import unicodedata
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROT))
os.chdir(ROT)  # kedjan använder sökvägar relativt projektmappen (data/, output/)

import analysera  # noqa: E402
import bedomning  # noqa: E402
import export_excel  # noqa: E402
import extract_report  # noqa: E402
import kriterier as k  # noqa: E402
from lagenhet import annonsnyckeltal  # noqa: E402

STAM_MONSTER = re.compile(r"^[A-Za-z0-9._-]{1,200}$")
MAX_PDF_BYTES = 50 * 1024 * 1024
ARKIV_DIR = Path("data/arkiv")

# En analys i taget, så att samma PDF aldrig extraheras (och betalas) två gånger samtidigt
analys_las = threading.Lock()

app = FastAPI(title="Bostadsanalys")


# --- Hjälpfunktioner ---------------------------------------------------------

def kor(funktion, *args, **kwargs):
    """Kör en funktion ur kedjan. Kedjan avslutar med sys.exit("meddelande") vid fel –
    det blir ett 400-svar med meddelandet i stället för att servern stängs."""
    try:
        return funktion(*args, **kwargs)
    except SystemExit as e:
        raise HTTPException(400, str(e.code) if e.code not in (None, 0) else "Okänt fel")


def kontrollera_stam(stam: str) -> str:
    if not STAM_MONSTER.match(stam):
        raise HTTPException(400, "Ogiltigt objekt-id.")
    return stam


def pdf_for(stam: str) -> Path:
    return analysera.PDF_DIR / f"{kontrollera_stam(stam)}.pdf"


def las_bedomning(stam: str):
    fil = bedomning.OUTPUT_DIR / f"{kontrollera_stam(stam)}.json"
    if not fil.exists():
        return None
    b = json.loads(fil.read_text(encoding="utf-8"))
    b["_stam"] = stam
    return b


def annons_for(b, annonser):
    """Senast tillagda annonsen för föreningen (kopplas via org.nr), eller None."""
    if not b or not b.get("org_nr"):
        return None
    traffar = [a for a in annonser if a.get("org_nr") == b["org_nr"]]
    return traffar[-1] if traffar else None


def med_vikter(b):
    """Lägg till vikt och om nyckeltalet är tungt, för att gruppera bubblorna."""
    for r in b["nyckeltal"]:
        r["vikt"] = k.UTSLAG_VIKTER.get(r["nyckeltal"], k.UTSLAG_VIKT_STANDARD)
        r["tung"] = r["vikt"] >= k.UTSLAG_TUNG_VIKT
    return b


def detalj(stam: str):
    b = las_bedomning(stam)
    if b is None:
        raise HTTPException(404, "Objektet finns inte.")
    a = annons_for(b, export_excel.las_annonser())
    return {
        "stam": stam,
        "bedomning": med_vikter(b),
        "annons": a,
        "lagenhet": annonsnyckeltal(a, b),
        "pdf_finns": pdf_for(stam).exists(),
        "marknadsranta_procent": k.MARKNADSRANTA_FORENINGSLAN_PROCENT,
    }


def filnamn_for_uppladdning(namn: str, innehall: bytes) -> str:
    """Filsäkert namn för en uppladdad PDF, med kontrollsumma som prefix (som för nedladdade)."""
    namn = unicodedata.normalize("NFKD", Path(namn or "arsredovisning.pdf").name)
    namn = namn.encode("ascii", "ignore").decode("ascii")
    namn = re.sub(r"[^A-Za-z0-9._-]+", "_", namn).strip("._") or "arsredovisning"
    namn = namn if namn.lower().endswith(".pdf") else f"{namn}.pdf"
    return f"{hashlib.sha256(innehall).hexdigest()[:12]}_{namn}"


def forberedd(pdf: Path):
    """Svar efter att PDF:en finns lokalt: är den redan extraherad (gratis) eller inte?"""
    stam = pdf.stem
    extraherad = extract_report.utfil_for(pdf).exists()
    return {"stam": stam, "redan_extraherad": extraherad, "redan_bedomd": las_bedomning(stam) is not None}


# --- API ---------------------------------------------------------------------

@app.get("/api/objekt")
def lista_objekt():
    """Alla bedömda objekt, sorterade som i Excel: GÅ VIDARE först, högst poäng först."""
    bedomningar = export_excel.las_bedomningar()
    annonser = export_excel.las_annonser()
    objekt = []
    for a, b in export_excel.rader_for_oversikt(bedomningar, annonser):
        if b is None:
            continue  # annons vars förening saknar bedömning
        t = annonsnyckeltal(a, b)
        objekt.append({
            "stam": b["_stam"],
            "adress": (a or {}).get("adress"),
            "annons_url": (a or {}).get("annons_url"),
            "forening": b.get("forening"),
            "utslag": b.get("utslag"),
            "poang": b.get("poang"),
            "datakvalitet": b.get("datakvalitet"),
            "motivering": b.get("motivering"),
            "bedomd": b.get("idag"),
            "rakenskapsar_slut": b.get("rakenskapsar_slut"),
            **{n: t[n] for n in ("pris", "avgift", "rum", "kvm", "skuldjusterat_pris_per_kvm", "vantad_avgift")},
        })
    return objekt


@app.get("/api/objekt/{stam}")
def hamta_objekt(stam: str):
    return detalj(stam)


class Forbered(BaseModel):
    pdf_url: str


@app.post("/api/forbered")
def forbered_lank(data: Forbered):
    """Ladda ner årsredovisningen från en länk (gratis). Extraherar inget."""
    url = data.pdf_url.strip()
    if not url.startswith("https://"):
        raise HTTPException(400, "Länken måste börja med https://")
    pdf = kor(analysera.ladda_ner, url)
    kor(extract_report.las_pdf, pdf)
    return forberedd(pdf)


@app.post("/api/ladda-upp")
async def ladda_upp(request: Request, filnamn: str = "arsredovisning.pdf"):
    """Ta emot en PDF (rå bytes i anropet) och spara den i data/pdfs/. Extraherar inget."""
    innehall = await request.body()
    if len(innehall) > MAX_PDF_BYTES:
        raise HTTPException(413, "Filen är för stor (max 50 MB).")
    if not innehall.startswith(b"%PDF"):
        raise HTTPException(400, "Filen är ingen PDF.")
    analysera.PDF_DIR.mkdir(parents=True, exist_ok=True)
    pdf = analysera.identisk_pdf(innehall)  # samma PDF finns redan → återanvänd (och extraktionen)
    if pdf is None:
        pdf = analysera.PDF_DIR / filnamn_for_uppladdning(filnamn, innehall)
        pdf.write_bytes(innehall)
    return forberedd(pdf)


class Annons(BaseModel):
    annons: str | None = None
    adress: str | None = None
    pris: str | None = None
    avgift: str | None = None
    rum: str | None = None
    kvm: str | None = None


class Analysera(BaseModel):
    stam: str
    bekrafta_kostnad: bool = False
    annons: Annons | None = None


@app.post("/api/analysera")
def analysera_objekt(data: Analysera):
    """Extrahera (bara om bekräftat – kostar pengar), bedöm och spara annonsen."""
    pdf = pdf_for(data.stam)
    if not pdf.exists():
        raise HTTPException(404, "PDF:en finns inte – ladda upp eller ange länken igen.")

    # Validera annonsuppgifterna innan något kostar pengar
    annons = None
    if data.annons:
        falt = {n: (v.strip() if isinstance(v, str) and v.strip() else None)
                for n, v in data.annons.model_dump().items()}
        annons = kor(analysera.validera_annons, SimpleNamespace(**falt))

    if not analys_las.acquire(blocking=False):
        raise HTTPException(409, "En annan analys pågår. Vänta tills den är klar.")
    try:
        json_fil = extract_report.utfil_for(pdf)
        if not json_fil.exists():
            if not data.bekrafta_kostnad:
                return JSONResponse(status_code=402, content={
                    "detail": "Extraktionen kostar ca 1–2 kr och kräver bekräftelse.", "kostar": True})
            kor(extract_report.extrahera, pdf)
        resultat = kor(bedomning.bedom_fil, json_fil, date.today())
        if annons:
            analysera.spara_annons(annons, resultat.get("org_nr"), pdf)
    finally:
        analys_las.release()
    return detalj(data.stam)


@app.post("/api/objekt/{stam}/bedom-om")
def bedom_om(stam: str):
    """Bedöm om med dagens datum och nuvarande kriterier. Gratis – inget API-anrop."""
    json_fil = extract_report.OUTPUT_DIR / f"{kontrollera_stam(stam)}.json"
    if not json_fil.exists():
        raise HTTPException(404, "Ingen extraktion finns för objektet.")
    kor(bedomning.bedom_fil, json_fil, date.today())
    return detalj(stam)


@app.post("/api/objekt/{stam}/arkivera")
def arkivera(stam: str):
    """Flytta bedömningen och föreningens annonser till data/arkiv/<dagens datum>/.
    Inget raderas. PDF och extraktion ligger kvar (gratis om föreningen dyker upp igen)."""
    b = las_bedomning(stam)
    if b is None:
        raise HTTPException(404, "Objektet finns inte.")
    mapp = ARKIV_DIR / date.today().isoformat()
    (mapp / "bedomning").mkdir(parents=True, exist_ok=True)
    shutil.move(str(bedomning.OUTPUT_DIR / f"{stam}.json"), str(mapp / "bedomning" / f"{stam}.json"))
    annonser = export_excel.las_annonser()
    flyttas = [a for a in annonser if b.get("org_nr") and a.get("org_nr") == b["org_nr"]]
    if flyttas:
        arkivfil = mapp / "annonser.json"
        arkiverade = json.loads(arkivfil.read_text(encoding="utf-8")) if arkivfil.exists() else []
        arkivfil.write_text(json.dumps(arkiverade + flyttas, ensure_ascii=False, indent=2), encoding="utf-8")
        kvar = [a for a in annonser if a not in flyttas]
        export_excel.ANNONSER_FIL.write_text(json.dumps(kvar, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"arkiverad": stam, "mapp": str(mapp)}


@app.get("/api/pdf/{stam}")
def hamta_pdf(stam: str):
    pdf = pdf_for(stam)
    if not pdf.exists():
        raise HTTPException(404, "PDF:en finns inte.")
    return FileResponse(pdf, media_type="application/pdf")


@app.get("/api/export.xlsx")
def exportera_excel():
    """Bygg Excel-filen (valfritt – görs bara när användaren ber om det) och ladda ner den."""
    kor(export_excel.main)
    return FileResponse(export_excel.UTFIL, filename="bostadsanalys.xlsx",
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# Gränssnittet (statiska filer) – sist, så att /api/ går före
app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
