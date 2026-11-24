"""
Molnlagret: Supabase (Auth, Postgres via PostgREST, Storage) med httpx. Inga andra beroenden.

Två sorters anrop:
- som användaren (dennes JWT + publik nyckel) för hushållets objekt i `annonser`. Då gäller
  RLS-policyerna i databasen, så en bugg i backenden kan ändå inte visa ett annat hushålls objekt.
- som backenden (service_role) för den delade cachen: dokument, extraktioner, bedömningar,
  föreningar, extraktionsloggen och PDF:erna i Storage. Nyckeln finns bara som env-var på servern.

Env-variabler: SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, SUPABASE_SERVICE_ROLE_KEY.
"""

import hashlib
import os
import threading
import time
from datetime import datetime, timezone

import httpx

BUCKET = "arsredovisningar"
TOKEN_CACHE_SEK = 60


def nu_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MolnFel(Exception):
    """Fel från Supabase som inte är användarens fel (svaret blir 502)."""


class Moln:
    def __init__(self, url: str, publik_nyckel: str, service_nyckel: str):
        if not (url and publik_nyckel and service_nyckel):
            raise MolnFel("SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY och SUPABASE_SERVICE_ROLE_KEY måste vara satta.")
        self.url = url.rstrip("/")
        self.publik = publik_nyckel
        self.service = service_nyckel
        self.http = httpx.Client(timeout=30)
        self._tokens: dict[str, tuple[float, dict]] = {}
        self._tokens_las = threading.Lock()

    @classmethod
    def fran_env(cls):
        return cls(os.getenv("SUPABASE_URL", ""), os.getenv("SUPABASE_PUBLISHABLE_KEY", ""),
                   os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""))

    # --- Huvuden ---------------------------------------------------------------

    def _admin(self, extra=None):
        # Nya nycklar (sb_secret_…) skickas bara som apikey; äldre service_role-JWT även som Bearer
        h = {"apikey": self.service}
        if not self.service.startswith("sb_"):
            h["Authorization"] = f"Bearer {self.service}"
        return {**h, **(extra or {})}

    def _som(self, token, extra=None):
        return {"apikey": self.publik, "Authorization": f"Bearer {token}", **(extra or {})}

    def _svar(self, r: httpx.Response):
        if r.status_code >= 400:
            raise MolnFel(f"Supabase svarade {r.status_code}: {r.text[:300]}")
        if not r.content:
            return None
        return r.json()

    def _rest(self, metod, tabell, huvuden, params=None, json=None):
        r = self.http.request(metod, f"{self.url}/rest/v1/{tabell}", headers=huvuden, params=params, json=json)
        return self._svar(r)

    # --- Inloggning ------------------------------------------------------------

    def anvandare(self, token: str) -> dict | None:
        """Verifiera token hos Supabase Auth. {"id", "email"} eller None. Cachas en minut."""
        nyckel = hashlib.sha256(token.encode()).hexdigest()
        nu = time.monotonic()
        with self._tokens_las:
            traff = self._tokens.get(nyckel)
            if traff and nu - traff[0] < TOKEN_CACHE_SEK:
                return traff[1]
        r = self.http.get(f"{self.url}/auth/v1/user", headers=self._som(token))
        if r.status_code in (401, 403):
            return None
        data = self._svar(r)
        anv = {"id": data["id"], "email": data.get("email")}
        with self._tokens_las:
            if len(self._tokens) > 1000:
                self._tokens.clear()
            self._tokens[nyckel] = (nu, anv)
        return anv

    def installningar(self, user_id: str) -> dict | None:
        rader = self._rest("GET", "anvandar_installningar", self._admin(),
                           {"user_id": f"eq.{user_id}", "select": "hushall_id,koparprofil"})
        return rader[0] if rader else None

    def satt_profil(self, user_id: str, profil: str):
        self._rest("PATCH", "anvandar_installningar", self._admin(), {"user_id": f"eq.{user_id}"},
                   {"koparprofil": profil})

    # --- Dokument (delad cache, service_role) -------------------------------------

    def dokument_med_hash(self, sha: str) -> dict | None:
        rader = self._rest("GET", "dokument", self._admin(), {"pdf_sha256": f"eq.{sha}", "select": "*"})
        return rader[0] if rader else None

    def dokument(self, ids: list[str]) -> dict[str, dict]:
        if not ids:
            return {}
        rader = self._rest("GET", "dokument", self._admin(),
                           {"id": f"in.({','.join(ids)})", "select": "*"})
        return {r["id"]: r for r in rader}

    def skapa_dokument(self, sha: str, innehall: bytes, user_id: str | None) -> dict:
        """Ladda upp PDF:en (namn = kontrollsumman) och skapa raden. Finns den redan: återanvänd."""
        befintlig = self.dokument_med_hash(sha)
        if befintlig:
            return befintlig
        sokvag = f"{sha}.pdf"
        r = self.http.post(f"{self.url}/storage/v1/object/{BUCKET}/{sokvag}", content=innehall,
                           headers=self._admin({"Content-Type": "application/pdf", "x-upsert": "true"}))
        self._svar(r)
        rader = self._rest("POST", "dokument",
                           self._admin({"Prefer": "return=representation,resolution=ignore-duplicates"}),
                           {"on_conflict": "pdf_sha256"},
                           {"pdf_sha256": sha, "storage_sokvag": sokvag, "skapad_av": user_id})
        return rader[0] if rader else self.dokument_med_hash(sha)

    def pdf_innehall(self, dok: dict) -> bytes:
        r = self.http.get(f"{self.url}/storage/v1/object/{BUCKET}/{dok['storage_sokvag']}", headers=self._admin())
        if r.status_code >= 400:
            raise MolnFel(f"Kunde inte hämta PDF:en ({r.status_code}).")
        return r.content

    def signerad_lank(self, dok: dict, sekunder: int = 300) -> str:
        r = self.http.post(f"{self.url}/storage/v1/object/sign/{BUCKET}/{dok['storage_sokvag']}",
                           headers=self._admin(), json={"expiresIn": sekunder})
        data = self._svar(r)
        return f"{self.url}/storage/v1{data['signedURL']}"

    def spara_extraktion(self, dokument_id: str, data: dict, org_nr: str | None, namn: str | None,
                         byggnadsar: int | None):
        if org_nr:
            self._rest("POST", "foreningar", self._admin({"Prefer": "resolution=merge-duplicates"}),
                       {"on_conflict": "org_nr"},
                       {"org_nr": org_nr, "namn": namn, "byggnadsar": byggnadsar, "uppdaterad_at": nu_iso()})
        self._rest("PATCH", "dokument", self._admin(), {"id": f"eq.{dokument_id}"},
                   {"extraherad": data, "org_nr": org_nr, "extraherad_at": nu_iso()})

    # --- Extraktionsloggen (månadstaket) --------------------------------------------

    def logga_extraktion(self, user_id: str, dokument_id: str, kostnad_ore: int | None):
        self._rest("POST", "extraktionslogg", self._admin(),
                   json={"user_id": user_id, "dokument_id": dokument_id, "kostnad_ore": kostnad_ore})

    def extraktioner_sedan(self, user_id: str, sedan_iso: str) -> int:
        r = self.http.get(f"{self.url}/rest/v1/extraktionslogg",
                          headers=self._admin({"Prefer": "count=exact", "Range": "0-0"}),
                          params={"user_id": f"eq.{user_id}", "skapad_at": f"gte.{sedan_iso}", "select": "id"})
        self._svar(r)
        return int(r.headers.get("content-range", "*/0").split("/")[-1])

    # --- Bedömningar (delad cache, service_role) --------------------------------------

    def senaste_bedomningar(self, dokument_ids: list[str], profil: str) -> dict[str, dict]:
        """Senaste bedömningen per dokument för köparprofilen: {dokument_id: rad}."""
        if not dokument_ids:
            return {}
        rader = self._rest("GET", "bedomningar", self._admin(),
                           {"dokument_id": f"in.({','.join(dokument_ids)})", "koparprofil": f"eq.{profil}",
                            "select": "dokument_id,idag,resultat,skapad_at", "order": "idag.desc,skapad_at.desc"})
        ut = {}
        for r in rader:
            ut.setdefault(r["dokument_id"], r)
        return ut

    def spara_bedomning(self, dokument_id: str, profil: str, idag: str, resultat: dict):
        self._rest("POST", "bedomningar", self._admin({"Prefer": "resolution=merge-duplicates"}),
                   {"on_conflict": "dokument_id,koparprofil,idag"},
                   {"dokument_id": dokument_id, "koparprofil": profil, "idag": idag, "resultat": resultat})

    # --- Hushållets objekt (som användaren – RLS gäller) ------------------------------

    def annonser(self, token: str, hushall_id: str, arkiverade: bool = False) -> list[dict]:
        return self._rest("GET", "annonser", self._som(token),
                          {"hushall_id": f"eq.{hushall_id}", "arkiverad": f"eq.{str(arkiverade).lower()}",
                           "select": "*", "order": "skapad_at.asc"})

    def annons(self, token: str, annons_id: str) -> dict | None:
        rader = self._rest("GET", "annonser", self._som(token), {"id": f"eq.{annons_id}", "select": "*"})
        return rader[0] if rader else None

    def hitta_annons(self, token: str, hushall_id: str, annons_url: str | None, dokument_id: str) -> dict | None:
        """Samma objekt finns redan: samma annonslänk, eller (utan länk) samma årsredovisning."""
        params = {"hushall_id": f"eq.{hushall_id}", "select": "*"}
        if annons_url:
            params["annons_url"] = f"eq.{annons_url}"
        else:
            params.update({"annons_url": "is.null", "dokument_id": f"eq.{dokument_id}"})
        rader = self._rest("GET", "annonser", self._som(token), params)
        return rader[0] if rader else None

    def skapa_annons(self, token: str, falt: dict) -> dict:
        return self._rest("POST", "annonser", self._som(token, {"Prefer": "return=representation"}), json=falt)[0]

    def uppdatera_annons(self, token: str, annons_id: str, falt: dict) -> dict:
        return self._rest("PATCH", "annonser", self._som(token, {"Prefer": "return=representation"}),
                          {"id": f"eq.{annons_id}"}, falt)[0]
