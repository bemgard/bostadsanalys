"""
Flytta befintlig data från data/ till Supabase – idempotent (kan köras om hur många gånger
som helst; det som redan finns hoppas över eller kompletteras, inget dubbleras eller raderas).

Kör från projektmappen, med SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY och
SUPABASE_SERVICE_ROLE_KEY i .env:

    venv/bin/python migrera_till_moln.py --epost du@exempel.se          # torrkörning: visar planen
    venv/bin/python migrera_till_moln.py --epost du@exempel.se --kor    # skriver

Inga anrop till Claude-API:t. Det som flyttas:
- data/pdfs/*.pdf            → Storage-bucketen + tabellen dokument (nyckel: kontrollsumman)
- data/extracted/<stam>.json → dokument.extraherad (+ föreningar)
- data/bedomning/, data/arkiv/*/bedomning/ → bedomningar (nyckel: dokument, köparprofil, datum)
- data/annonser.json         → annonser i ditt hushåll (nyckel: hushåll + annonslänk)
- data/arkiv/*/annonser.json → annonser, arkiverade (om annonsen inte också är aktiv)
- en bedömd PDF utan annons  → ett objekt utan annonslänk (som i den gamla översikten)
Extraktionsloggen lämnas tom: gamla extraktioner räknas inte mot månadstaket.
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from app.moln import Moln

DATA = Path("data")


def las_json(fil: Path):
    return json.loads(fil.read_text(encoding="utf-8"))


def varde(data, nyckel):
    x = (data or {}).get(nyckel)
    return x.get("varde") if isinstance(x, dict) else None


def tid(fil: Path) -> str:
    return datetime.fromtimestamp(fil.stat().st_mtime, timezone.utc).isoformat()


def samla():
    """Allt lokalt, utan nätverk: {stam: {...}} och annonserna."""
    objekt = {}
    for pdf in sorted((DATA / "pdfs").glob("*.pdf")):
        innehall = pdf.read_bytes()
        ext = DATA / "extracted" / f"{pdf.stem}.json"
        objekt[pdf.stem] = {"pdf": pdf, "sha": hashlib.sha256(innehall).hexdigest(),
                            "extraktion": ext if ext.exists() else None, "bedomningar": []}
    for fil in sorted(DATA.glob("bedomning/*.json")) + sorted(DATA.glob("arkiv/*/bedomning/*.json")):
        if fil.stem in objekt:
            objekt[fil.stem]["bedomningar"].append((fil, fil.parent == DATA / "bedomning"))  # (fil, aktiv)
        else:
            print(f"  ⚠️  {fil}: ingen PDF med samma namn – hoppas över")
    aktiva = las_json(DATA / "annonser.json") if (DATA / "annonser.json").exists() else []
    aktiva_url = {a["annons_url"] for a in aktiva}
    arkiverade = []
    for fil in sorted(DATA.glob("arkiv/*/annonser.json")):
        for a in las_json(fil):
            if a["annons_url"] not in aktiva_url and a["annons_url"] not in {x["annons_url"] for x in arkiverade}:
                arkiverade.append(a)
    return objekt, [(a, False) for a in aktiva] + [(a, True) for a in arkiverade]


def hushall_for(m: Moln, epost: str):
    r = m.http.get(f"{m.url}/auth/v1/admin/users", headers=m._admin(), params={"per_page": 1000})
    anv = next((u for u in m._svar(r).get("users", []) if (u.get("email") or "").lower() == epost.lower()), None)
    if anv is None:
        sys.exit(f"Hittar ingen användare med e-post {epost}. Bjud in dig själv först.")
    inst = m.installningar(anv["id"])
    if not inst or not inst.get("hushall_id"):
        sys.exit(f"{epost} saknar hushåll.")
    return anv["id"], inst["hushall_id"]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--epost", required=True, help="din inloggning – annonserna hamnar i ditt hushåll")
    p.add_argument("--kor", action="store_true", help="skriv på riktigt (annars bara torrkörning)")
    args = p.parse_args()
    load_dotenv()

    objekt, annonser = samla()
    m = Moln.fran_env()
    user_id, hushall = hushall_for(m, args.epost)
    skriv = args.kor
    print(f"{'SKRIVER' if skriv else 'TORRKÖRNING (inget skrivs – lägg till --kor)'} · hushåll {hushall}\n")

    # 1. Dokument, PDF:er, extraktioner och föreningar
    dok_id = {}  # sha → dokument-id
    for stam, o in objekt.items():
        befintlig = m.dokument_med_hash(o["sha"])
        data = las_json(o["extraktion"]) if o["extraktion"] else None
        if befintlig and (befintlig.get("extraherad") or not data):
            print(f"  = dokument finns: {stam}")
            dok_id[o["sha"]] = befintlig["id"]
            continue
        print(f"  + dokument{'' if befintlig else ' + PDF'}{' + extraktion' if data else ' (ej extraherad)'}: {stam}")
        if not skriv:
            dok_id[o["sha"]] = befintlig["id"] if befintlig else f"(nytt:{stam})"
            continue
        dok = befintlig or m.skapa_dokument(o["sha"], o["pdf"].read_bytes(), user_id)
        dok_id[o["sha"]] = dok["id"]
        if data:
            m.spara_extraktion(dok["id"], data, varde(data, "organisationsnummer"),
                               varde(data, "foreningens_namn"), varde(data, "byggnadsar"))
            m._rest("PATCH", "dokument", m._admin(), {"id": f"eq.{dok['id']}"},
                    {"extraherad_at": tid(o["extraktion"])})

    # 2. Bedömningar
    for stam, o in objekt.items():
        # Arkiverade först, aktiva sist: har båda samma datum vinner den aktiva (nyare) bedömningen
        for fil, _ in sorted(o["bedomningar"], key=lambda x: x[1]):
            b = las_json(fil)
            profil, idag = b.get("koparprofil") or "par", b.get("idag")
            if not idag:
                print(f"  ⚠️  {fil}: saknar datum – hoppas över")
                continue
            # Gamla formatet (före utslaget med poäng/motivering/datakvalitet) flyttas inte – appen
            # skulle visa en trasig bedömning. Den räknas om gratis med dagens kriterier vid behov.
            if not {"poang", "motivering", "datakvalitet"} <= set(b):
                print(f"  - bedömning {stam} ({idag}): gammalt format – flyttas inte, räknas om vid behov")
                continue
            print(f"  ~ bedömning {stam} ({profil}, {idag})")
            if skriv:
                m.spara_bedomning(dok_id[o["sha"]], profil, idag, b)

    # 3. Annonser (via PDF:ens kontrollsumma, inte org.nr – en förening kan ha flera PDF:er)
    sha_for_fil = {str(o["pdf"]): o["sha"] for o in objekt.values()}
    befintliga = m._rest("GET", "annonser", m._admin(), {"hushall_id": f"eq.{hushall}", "select": "*"})
    per_url = {a["annons_url"]: a for a in befintliga if a.get("annons_url")}
    med_annons = set()
    for a, arkiverad in annonser:
        sha = sha_for_fil.get(a.get("pdf_fil") or "")
        if sha is None:
            print(f"  ⚠️  {a['annons_url']}: PDF:en {a.get('pdf_fil')} finns inte – hoppas över")
            continue
        med_annons.add(sha)
        falt = {n: a.get(n) for n in ("annons_url", "adress", "pris", "avgift", "rum", "kvm", "org_nr")}
        falt.update({"dokument_id": dok_id[sha], "arkiverad": arkiverad})
        if a["annons_url"] in per_url:
            fanns = per_url[a["annons_url"]]
            saknas = {n: v for n, v in falt.items() if v is not None and fanns.get(n) is None}
            print(f"  {'~' if saknas else '='} annons {a.get('adress')} {'kompletteras' if saknas else 'finns'}")
            if skriv and saknas:
                m._rest("PATCH", "annonser", m._admin(), {"id": f"eq.{fanns['id']}"}, saknas)
            continue
        print(f"  + annons {a.get('adress')}{' (arkiverad)' if arkiverad else ''}")
        if skriv:
            m._rest("POST", "annonser", m._admin(), json={
                **falt, "hushall_id": hushall, "skapad_av": user_id,
                **({"skapad_at": f"{a['tillagd_datum']}T12:00:00+00:00"} if a.get("tillagd_datum") else {})})

    # 4. Bedömda PDF:er utan annons → objekt utan annonslänk (bara aktiva bedömningar)
    for stam, o in objekt.items():
        if o["sha"] in med_annons or not any(aktiv for _, aktiv in o["bedomningar"]):
            continue
        finns = any(a.get("annons_url") is None and a.get("dokument_id") == dok_id[o["sha"]] for a in befintliga)
        print(f"  {'=' if finns else '+'} objekt utan annons: {stam}")
        if skriv and not finns:
            org = varde(las_json(o["extraktion"]), "organisationsnummer") if o["extraktion"] else None
            m._rest("POST", "annonser", m._admin(), json={
                "hushall_id": hushall, "dokument_id": dok_id[o["sha"]], "org_nr": org, "skapad_av": user_id})

    print("\nKlart." if skriv else "\nTorrkörning klar – inget skrevs. Kör med --kor för att skriva.")


if __name__ == "__main__":
    main()
