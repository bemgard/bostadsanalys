"""
Läs en Booli-annons och föreningens sida – samma logik som bokmärket (bokmarke/bostadsanalys.js),
men på servern, så att det räcker att dra in annonslänken i appen.

Från annonsen: adress (JSON-LD Place), pris (JSON-LD Product), avgift/rum/boarea (rubrik → värde
i sidans text) och länken till bostadsrättsföreningen. Från föreningssidan: årsredovisningens PDF.

Kräver föreningssidan inloggning för dokumenten kan en Booli-cookie anges i .env (BOOLI_COOKIE),
annars returneras pdf_url = None och användaren får dra in PDF:en själv.
Allt som läses kontrolleras strikt – det är främmande data.
"""

import json
import os
import re
import urllib.error
import urllib.request
from html import unescape
from html.parser import HTMLParser

ANNONS_MONSTER = re.compile(r"^https://www\.booli\.se/(bostad|annons)/\d+$")
FORENING_MONSTER = re.compile(r"^/bostadsrattsforening/\d+$")
PDF_MONSTER = re.compile(r"^https://documents\.bcdn\.se/[A-Za-z0-9/_.\-]+\.pdf$")
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")
ADRESS_MAX_TECKEN = 100


class BooliFel(Exception):
    """Fel med ett meddelande som kan visas för användaren."""


# --- Hämtning ----------------------------------------------------------------

def hamta(url: str, cookie: str | None = None) -> str:
    """Hämta en sida på www.booli.se som text. cookie = Booli-inloggning (valfri)."""
    huvud = {"User-Agent": USER_AGENT, "Accept-Language": "sv-SE,sv;q=0.9"}
    if cookie:
        huvud["Cookie"] = cookie
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=huvud), timeout=30) as svar:
            return svar.read(5_000_000).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raise BooliFel(f"Booli svarade {e.code} för {url}.")
    except (urllib.error.URLError, TimeoutError) as e:
        raise BooliFel(f"Kunde inte nå Booli: {getattr(e, 'reason', e)}")


def booli_cookie() -> str | None:
    """Booli-inloggning från miljön/.env (BOOLI_COOKIE), eller None."""
    try:
        from dotenv import load_dotenv
        load_dotenv()  # skriver inte över en redan satt miljövariabel (appen sätter den direkt)
    except ImportError:
        pass
    cookie = (os.getenv("BOOLI_COOKIE") or "").strip().strip("'")
    return cookie if cookie and "\n" not in cookie else None


# --- Tolkning ----------------------------------------------------------------

class _Text(HTMLParser):
    """Sidans synliga textbitar i ordning, samt JSON-LD och länkar (href)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text, self.jsonld, self.lankar = [], [], []
        self._i_jsonld = self._hoppa = False
        self._buffert = ""

    def handle_starttag(self, tagg, attr):
        a = dict(attr)
        if tagg == "script":
            self._i_jsonld = a.get("type") == "application/ld+json"
            self._hoppa = not self._i_jsonld
            self._buffert = ""
        elif tagg == "style":
            self._hoppa = True
        if tagg == "a" and a.get("href"):
            self.lankar.append((len(self.text), a["href"]))

    def handle_endtag(self, tagg):
        if tagg == "script" and self._i_jsonld:
            self.jsonld.append(self._buffert)
        if tagg in ("script", "style"):
            self._i_jsonld = self._hoppa = False

    def handle_data(self, data):
        if self._i_jsonld:
            self._buffert += data
        elif not self._hoppa and data.strip():
            self.text.append(" ".join(data.split()))


def _tolka(html_text: str) -> _Text:
    p = _Text()
    p.feed(html_text)
    return p


def _jsonld_objekt(p: _Text):
    objekt = []
    for block in p.jsonld:
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        for d in data if isinstance(data, list) else [data]:
            if isinstance(d, dict):
                objekt.append(d)
                objekt.extend(x for x in d.get("@graph", []) if isinstance(x, dict))
    return objekt


def _av_typ(objekt, typ):
    return next((o for o in objekt if o.get("@type") == typ), None)


def forsta_tal(text) -> str | None:
    """Första talet i en text som sträng: "4 648 kr/mån" → "4648", "63,5 m²" → "63.5"."""
    if text is None:
        return None
    m = re.search(r"\d+(?:[.,]\d+)?", re.sub(r"[\s ]", "", str(text)))
    return m.group(0).replace(",", ".") if m else None


def heltal(text) -> str | None:
    t = forsta_tal(text)
    return t if t and t.isdigit() and int(t) > 0 else None


def decimaltal(text) -> str | None:
    t = forsta_tal(text)
    return t if t and re.fullmatch(r"\d+(\.\d+)?", t) and float(t) > 0 else None


def tvatta_adress(text) -> str | None:
    """Bara bokstäver, siffror, mellanslag, komma, punkt och bindestreck (som i bokmärket)."""
    if not text:
        return None
    ren = re.sub(r"[^\w ,.\-]", "", " ".join(str(text).split()), flags=re.UNICODE).replace("_", "")
    ren = re.sub(r" +", " ", ren).strip()[:ADRESS_MAX_TECKEN].strip()
    return ren or None


def _rubrikvarde(p: _Text, etikett: str) -> str | None:
    """Texten direkt efter en textbit som är exakt etiketten, t.ex. "Avgift" → "4 648 kr/mån"."""
    for i, t in enumerate(p.text[:-1]):
        if t == etikett:
            return p.text[i + 1]
    return None


def las_annons(html_text: str, url: str) -> dict:
    """Annonsens uppgifter. Saknade/ogiltiga värden blir None."""
    p = _tolka(html_text)
    ld = _jsonld_objekt(p)
    plats, produkt, stig = _av_typ(ld, "Place"), _av_typ(ld, "Product"), _av_typ(ld, "BreadcrumbList")

    forening = None
    for post in (stig or {}).get("itemListElement", []) or []:
        item = post.get("item") if isinstance(post, dict) else None
        item = item.get("@id") if isinstance(item, dict) else item
        if isinstance(item, str) and "/bostadsrattsforening/" in item:
            forening = re.sub(r"^https://www\.booli\.se", "", item.split("?")[0]).rstrip("/")
    if not forening:
        lank = next((h for _, h in p.lankar if "/bostadsrattsforening/" in h), None)
        if lank:
            forening = re.sub(r"^https://www\.booli\.se", "", lank.split("?")[0]).rstrip("/")
    if forening and not FORENING_MONSTER.match(forening):
        forening = None

    adress = ((plats or {}).get("address") or {}) if isinstance((plats or {}).get("address"), dict) else {}
    erbjudande = (produkt or {}).get("offers")
    erbjudande = erbjudande[0] if isinstance(erbjudande, list) and erbjudande else erbjudande
    return {
        "annons": url,
        "adress": tvatta_adress(adress.get("streetAddress")),
        "pris": heltal((erbjudande or {}).get("price") if isinstance(erbjudande, dict) else None),
        "avgift": heltal(_rubrikvarde(p, "Avgift")),
        "rum": decimaltal(_rubrikvarde(p, "Rum")),
        "kvm": decimaltal(_rubrikvarde(p, "Boarea")),
        "forening_sokvag": forening,
    }


def _inbaddade_dokument(html_text: str) -> list[str]:
    """Dokumentlänkar i sidans inbäddade data (Next.js skickar datan som JSON-strängar i
    <script>, med / skrivet som \\/ eller \\u002F). I den ordning de förekommer, utan dubbletter."""
    text = html_text.replace("\\u002F", "/").replace("\\/", "/").replace("\\\\", "\\")
    traffar = re.findall(r"https://documents\.bcdn\.se/[A-Za-z0-9/_.\-]+\.pdf", text)
    return list(dict.fromkeys(traffar))


def las_forening_pdf(html_text: str) -> str | None:
    """Årsredovisningens PDF-länk: första dokumentlänken efter rubriken "Årsredovisning",
    annars en dokumentlänk vars filnamn innehåller "rsredovisning" – först bland sidans länkar,
    sedan i den inbäddade datan. None om ingen finns."""
    p = _tolka(html_text)
    dokument = [(pos, unescape(h).split("?")[0]) for pos, h in p.lankar if "documents.bcdn.se" in h]
    rubriker = [i for i, t in enumerate(p.text) if t == "Årsredovisning"]
    kandidater = [h for r in rubriker for pos, h in dokument if pos >= r][:1]
    kandidater += [h for _, h in dokument if re.search(r"rsredovisning", h, re.I)]
    kandidater += [h for h in _inbaddade_dokument(html_text) if re.search(r"rsredovisning", h, re.I)]
    return next((h for h in kandidater if PDF_MONSTER.match(h)), None)


# --- Hela flödet ---------------------------------------------------------------

FELSOKNING_FIL = "output/booli_felsokning.txt"


def _spara_felsokning(html_text: str, med_cookie: bool):
    """Spara en sammanfattning av föreningssidan när årsredovisningen inte hittas – för att
    se vad Booli skickar. Inga cookies sparas; bara sidans innehåll (som vem som helst ser
    när den är inloggad) och några markörer. Skrivs över varje gång."""
    try:
        os.makedirs("output", exist_ok=True)
        rader = [f"med_cookie={med_cookie}", f"längd={len(html_text)}",
                 f"logga_in_text={'Logga in' in html_text}",
                 f"documents.bcdn.se_förekomster={html_text.count('documents.bcdn.se')}",
                 f"rsredovisning_förekomster={html_text.count('rsredovisning')}", ""]
        for m in re.finditer(r".{0,300}(documents\.bcdn|rsredovisning|graphql|document).{0,300}", html_text):
            rader.append(m.group(0))
            if len(rader) > 80:
                break
        with open(FELSOKNING_FIL, "w", encoding="utf-8") as f:
            f.write("\n".join(rader))
    except OSError:
        pass

def tolka_sidor(url: str, annons_html: str, forening_html: str | None,
                forening_url: str | None = None) -> dict:
    """Samma resultat som fran_annons, men från sidor som redan hämtats – av Chrome-tillägget
    i användarens inloggade webbläsare (Booli visar dokumentlänkarna bara för inloggade).
    forening_url = föreningssidan tillägget faktiskt läste. Den måste vara annonsens förening
    (brödsmulorna), annars kan annonsen få en annan förenings årsredovisning."""
    url = url.strip().split("?")[0].split("#")[0].rstrip("/")
    if not ANNONS_MONSTER.match(url):
        raise BooliFel("Det där är ingen Booli-annons (https://www.booli.se/bostad/… eller /annons/…).")
    annons = las_annons(annons_html, url)
    sokvag = annons.pop("forening_sokvag")
    if not sokvag:
        return {"annons": annons, "pdf_url": None, "forening_url": None,
                "meddelande": "Annonsen har ingen länk till en bostadsrättsförening."}
    if forening_url is not None:
        last = re.sub(r"^https://www\.booli\.se", "", forening_url.split("?")[0].split("#")[0]).rstrip("/")
        if last != sokvag:
            raise BooliFel(f"Tillägget läste fel föreningssida ({last}, annonsen hör till {sokvag}). "
                           "Försök igen eller dra in PDF:en.")
    pdf = las_forening_pdf(forening_html or "")
    meddelande = None
    if not pdf:
        _spara_felsokning(forening_html or "", True)
        meddelande = ("Hittade inte årsredovisningen på föreningssidan. Är du inloggad på Booli i Chrome? "
                      "Annars kan föreningen sakna årsredovisning – dra in PDF:en.")
    return {"annons": annons, "pdf_url": pdf, "forening_url": "https://www.booli.se" + sokvag,
            "meddelande": meddelande}


def forening_sokvag(annons_html: str) -> str | None:
    """Bara föreningslänken ur en annons (för tillägget, som hämtar föreningssidan härnäst)."""
    return las_annons(annons_html, "").get("forening_sokvag")


def fran_annons(url: str) -> dict:
    """Läs annonsen och försök hitta årsredovisningen. Returnerar annonsuppgifterna,
    pdf_url (eller None) och ett meddelande om något saknas."""
    url = url.strip().split("?")[0].split("#")[0].rstrip("/")
    if not ANNONS_MONSTER.match(url):
        raise BooliFel("Det där är ingen Booli-annons (https://www.booli.se/bostad/… eller /annons/…).")
    cookie = booli_cookie()
    annons = las_annons(hamta(url, cookie), url)
    sokvag = annons.pop("forening_sokvag")
    if not sokvag:
        return {"annons": annons, "pdf_url": None,
                "meddelande": "Annonsen har ingen länk till en bostadsrättsförening."}
    forening_html = hamta("https://www.booli.se" + sokvag, cookie)
    pdf = las_forening_pdf(forening_html)
    meddelande = None
    if not pdf:
        _spara_felsokning(forening_html, bool(cookie))
        meddelande = ("Hittade annonsen men inte årsredovisningen – Booli visar troligen dokumenten bara "
                      "för inloggade. Dra in PDF:en, eller koppla din Booli-inloggning."
                      if not cookie else
                      "Hittade inte årsredovisningen, trots Booli-inloggningen. Dra in PDF:en så länge – "
                      "felsökningen är sparad i output/booli_felsokning.txt.")
    return {"annons": annons, "pdf_url": pdf, "forening_url": "https://www.booli.se" + sokvag,
            "meddelande": meddelande}
