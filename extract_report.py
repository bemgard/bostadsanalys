"""
Steg 2: Extrahera fakta ur en bostadsrättsförenings årsredovisning (PDF) till JSON.
Kör: python extract_report.py data/pdfs/<fil>.pdf [--force]
(--force kör om API-anropet även om filen redan är extraherad)
Resultatet sparas i data/extracted/<pdf-namn>.json
"""

import base64
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
import anthropic

MODEL = "claude-sonnet-5-5"
TOOL_NAME = "spara_arsredovisning"
OUTPUT_DIR = Path("data/extracted")


# --- JSON-schema -------------------------------------------------------------
# Varje värde har formen {"varde": ..., "sida": ...}. Både varde och sida får
# vara null, så att Claude kan markera att något saknas i stället för att gissa.

def nullable(typ):
    """Schema för en typ som också får vara null."""
    return {"anyOf": [{"type": typ}, {"type": "null"}]}


def falt(typ, beskrivning):
    """Schema för ett extraherat värde: {"varde": <typ eller null>, "sida": <int eller null>}."""
    return {
        "type": "object",
        "description": beskrivning,
        "properties": {
            "varde": nullable(typ),
            "sida": nullable("integer"),
        },
        "required": ["varde", "sida"],
        "additionalProperties": False,
    }


def lista(egenskaper, beskrivning):
    """Schema för en lista med objekt, där varje objekt har ett sidnummer."""
    egenskaper = {**egenskaper, "sida": {"type": "integer"}}
    return {
        "type": "array",
        "description": beskrivning,
        "items": {
            "type": "object",
            "properties": egenskaper,
            "required": list(egenskaper),
            "additionalProperties": False,
        },
    }


SCHEMA_PROPERTIES = {
    "foreningens_namn": falt("string", "Föreningens namn."),
    "organisationsnummer": falt("string", "Organisationsnummer i formatet NNNNNN-NNNN (tio siffror med bindestreck)."),
    "rakenskapsar": {
        "type": "object",
        "description": "Räkenskapsårets start- och slutdatum (ÅÅÅÅ-MM-DD).",
        "properties": {
            "start": falt("string", "Startdatum, ÅÅÅÅ-MM-DD."),
            "slut": falt("string", "Slutdatum, ÅÅÅÅ-MM-DD."),
        },
        "required": ["start", "slut"],
        "additionalProperties": False,
    },
    "skulder_kreditinstitut_langfristiga": falt(
        "number",
        "Långfristiga skulder till kreditinstitut i kr vid räkenskapsårets slut, enligt balansräkningen.",
    ),
    "skulder_kreditinstitut_kortfristiga": falt(
        "number",
        "Kortfristiga skulder till kreditinstitut i kr vid räkenskapsårets slut, enligt balansräkningen.",
    ),
    "bostadsyta_kvm": falt("number", "Total bostadsyta för bostadsrätterna i kvm."),
    "lokalyta_kvm": falt("number", "Total lokalyta i kvm."),
    "total_yta_kvm": falt("number", "Byggnadernas totalyta i kvm (bostäder + lokaler), så som den står i dokumentet."),
    "antal_bostadsratter": falt(
        "integer", "Antal bostadsrätter – bara om antalet står uttryckligen. Räkna inte fram det."),
    "antal_hyresratter": falt(
        "integer", "Antal hyresrätter (hyreslägenheter) – bara om antalet står uttryckligen. Räkna inte fram det."),
    "antal_lagenheter_totalt": falt(
        "integer",
        "Totalt antal lägenheter när rapporten anger det (t.ex. \"I fastigheten finns 63 lägenheter\"). "
        "Räkna inte ihop bostadsrätter och hyresrätter själv.",
    ),
    "byggnadsar": falt(
        "integer",
        "Det år huset uppfördes (byggår, inte värdeår). Finns flera hus med olika byggår: ta det senaste.",
    ),
    "tomtratt": falt("boolean", "true om marken innehas med tomträtt, false om den ägs (äganderätt)."),
    "arsresultat": falt("number", "Årets resultat i kr för räkenskapsåret (negativt vid förlust)."),
    "likvida_medel_arets_slut": falt("number", "Likvida medel vid årets slut i kr, enligt kassaflödesanalysen."),
    "kassaflode_lopande_verksamhet": falt(
        "number",
        "\"Kassaflöde från den löpande verksamheten\" i kr för räkenskapsåret, enligt kassaflödesanalysen "
        "(efter förändring i rörelsekapital).",
    ),
    "arsavgifter_bostader": falt(
        "number",
        "Årsavgifternas totalbelopp i kr för räkenskapsåret (oftast i noten för nettoomsättning).",
    ),
    "lan": lista(
        {
            "langivare": nullable("string"),
            "belopp": nullable("number"),
            "rantesats_procent": nullable("number"),
            "villkorsandringsdag": nullable("string"),
        },
        "Varje enskilt lån i noten om skulder till kreditinstitut, ett objekt per lån (rad), utan summering. "
        "belopp = skulden vid räkenskapsårets slut i kr. villkorsandringsdag som ÅÅÅÅ-MM-DD. "
        "Ta inte med summeringsrader. Tom lista om inga lån redovisas.",
    ),
    "skuldsattning_per_kvm_bostadsratt": falt(
        "number",
        "Skuldsättning per kvm upplåten bostadsrättsyta (kr), enligt föreningens flerårsöversikt, för räkenskapsåret. "
        "null om föreningen inte redovisar just denna variant.",
    ),
    "skuldsattning_per_kvm_totalyta": falt(
        "number",
        "Skuldsättning per kvm totalyta (kr), enligt föreningens flerårsöversikt, för räkenskapsåret. "
        "null om föreningen inte redovisar just denna variant.",
    ),
    "sparande_per_kvm": falt("number", "Sparande per kvm (kr), enligt föreningens flerårsöversikt, för räkenskapsåret."),
    "rantekanslighet_procent": falt("number", "Räntekänslighet i procent, enligt föreningens flerårsöversikt, för räkenskapsåret."),
    "arsavgift_per_kvm": falt(
        "number",
        "Årsavgift per kvm upplåten bostadsrätt (kr), enligt föreningens flerårsöversikt, för räkenskapsåret.",
    ),
    "energikostnad_per_kvm": falt("number", "Energikostnad per kvm (kr), enligt föreningens flerårsöversikt, för räkenskapsåret."),
    "planerat_underhall": lista(
        {
            "atgard": {"type": "string"},
            "planerat_ar": nullable("string"),
            "uppskattad_kostnad": nullable("number"),
        },
        "Planerade (framtida) underhållsåtgärder, t.ex. stambyte, fönster, tak. "
        "planerat_ar som det står, t.ex. '2025' eller '2026-2027'. "
        "uppskattad_kostnad i kr bara om en kostnad uttryckligen anges för åtgärden, annars null – gissa aldrig. "
        "Tom lista om inget anges.",
    ),
    "genomforda_avgiftshojningar": lista(
        {
            "procent": nullable("number"),
            "fran_datum": nullable("string"),
        },
        "Höjningar av årsavgiften som trätt i kraft under eller före räkenskapsåret. "
        "fran_datum som ÅÅÅÅ-MM-DD om det anges. Tom lista om inget anges.",
    ),
    "planerade_avgiftshojningar": lista(
        {
            "procent": nullable("number"),
            "fran_datum": nullable("string"),
        },
        "Beslutade höjningar av årsavgiften som träder i kraft efter räkenskapsårets slut. "
        "fran_datum som ÅÅÅÅ-MM-DD om det anges. Tom lista om inget anges.",
    ),
    "revisorns_anmarkning": {
        "type": "object",
        "description": "Om revisionsberättelsen innehåller en anmärkning eller ett modifierat/avvikande uttalande. "
        "beskrivning handlar bara om anmärkningen (null om ingen anmärkning finns).",
        "properties": {
            "varde": nullable("boolean"),
            "beskrivning": nullable("string"),
            "sida": nullable("integer"),
        },
        "required": ["varde", "beskrivning", "sida"],
        "additionalProperties": False,
    },
    "revisorns_upplysning": {
        "type": "object",
        "description": "Om revisionsberättelsen innehåller en \"upplysning av särskild betydelse\" eller motsvarande "
        "upplysning som inte är en anmärkning eller ett modifierat uttalande. beskrivning = kort text om "
        "upplysningen (null om ingen finns).",
        "properties": {
            "varde": nullable("boolean"),
            "beskrivning": nullable("string"),
            "sida": nullable("integer"),
        },
        "required": ["varde", "beskrivning", "sida"],
        "additionalProperties": False,
    },
    "akta_forening": falt(
        "boolean",
        "true om föreningen anges vara en äkta bostadsrättsförening (privatbostadsföretag), "
        "false om den anges vara oäkta. null om det inte framgår.",
    ),
    "underhallsplan_finns": falt(
        "boolean",
        "true om årsredovisningen anger att föreningen har en underhållsplan, false om den anger att "
        "plan saknas. null om det inte nämns.",
    ),
    "underhallsplan_till_ar": falt(
        "integer",
        "Det år underhållsplanen sträcker sig till, så som det står (t.ex. 2053). null om det inte anges.",
    ),
    "utfort_underhall": lista(
        {
            "atgard": {"type": "string"},
            "ar": nullable("string"),
        },
        "ALLA utförda (historiska) underhållsåtgärder som årsredovisningen nämner, en post per åtgärd – "
        "både i listor/tabeller och i löpande text (t.ex. \"stambyte genomfördes 1998\"). "
        "atgard med dokumentets egen formulering, ar exakt som det står (t.ex. '2002' eller '2019-2020'). "
        "Tolka, sammanfatta eller slå inte ihop något. Tom lista om inget anges.",
    ),
    "grundlaggning": {
        "type": "object",
        "description": "Om årsredovisningen nämner problem med byggnadens grund: grundförstärkning, sättningar, "
        "pålar (t.ex. rötskadade träpålar) eller liknande – historiskt, pågående eller planerat. Gäller "
        "byggnadens grund, inte t.ex. markarbeten eller beläggning på gården. varde = false om inget sådant "
        "nämns. beskrivning = kort text om vad som nämns (null om inget). status = om problemet är "
        "\"planerad\" (åtgärd planerad), \"pågående\" (pågår eller ej åtgärdat), \"åtgärdad\" (redan "
        "åtgärdat) eller \"okänd\" (framgår inte); null om varde är false.",
        "properties": {
            "varde": nullable("boolean"),
            "beskrivning": nullable("string"),
            "status": {"anyOf": [
                {"type": "string", "enum": ["planerad", "pågående", "åtgärdad", "okänd"]},
                {"type": "null"},
            ]},
            "sida": nullable("integer"),
        },
        "required": ["varde", "beskrivning", "status", "sida"],
        "additionalProperties": False,
    },
}

TOOL = {
    "name": TOOL_NAME,
    "description": "Spara de fakta som lästs av ur årsredovisningen.",
    "input_schema": {
        "type": "object",
        "properties": SCHEMA_PROPERTIES,
        "required": list(SCHEMA_PROPERTIES),
        "additionalProperties": False,
    },
}

INSTRUKTION = f"""Du får en bostadsrättsförenings årsredovisning som PDF.
Läs av fakta ur dokumentet och anropa verktyget {TOOL_NAME} exakt en gång med resultatet.

Regler:
- Läs bara av det som faktiskt står i dokumentet. Gissa aldrig, och räkna aldrig fram värden själv
  (summera, dividera, omvandla eller uppskatta inte). Står värdet inte uttryckligen: varde = null och sida = null.
- "sida" är sidnumret i PDF-filen, räknat från 1 för PDF:ens första sida (inklusive försättsblad).
  Använd INTE det tryckta sidnumret (t.ex. "Sida 6 av 18").
- Belopp anges som tal i kronor utan mellanslag eller enhet (t.ex. -1864103). Procent som tal (t.ex. 7.8).
- Nyckeltal ska tas från föreningens egen flerårsöversikt/förvaltningsberättelse och avse räkenskapsåret.
- Skulder till kreditinstitut: läs av lång- och kortfristig del var för sig, så som de står i balansräkningen.
  Summera inte. Står den ena delen uttryckligen som 0, ange 0.
- Revisorns anmärkning: varde = true bara om revisorn gör en anmärkning, avstyrker, eller lämnar ett
  modifierat/avvikande uttalande. beskrivning handlar bara om anmärkningen (null om ingen finns).
- Revisorns upplysning: varde = true om revisionsberättelsen innehåller en "upplysning av särskild betydelse"
  eller motsvarande upplysning som inte är en anmärkning eller ett modifierat uttalande. En sådan upplysning
  ska INTE påverka revisorns anmärkning. beskrivning = kort text om upplysningen (null om ingen finns).
- Saknas revisionsberättelsen helt: varde = null i båda revisorsfälten.
- Utfört underhåll: ta med VARJE utförd åtgärd, även gamla – både från listor/tabeller och från
  löpande text i hela dokumentet (t.ex. "stambyte genomfördes 1998" eller "taket lades om 2015" ger
  egna poster). Skriv av åtgärd och år ordagrant; slå inte ihop, förkorta eller tolka.
- Antal lägenheter: antal_bostadsratter, antal_hyresratter och antal_lagenheter_totalt läses bara av
  när de står uttryckligen. Räkna aldrig fram något av dem ur de andra.
- Byggår: året huset uppfördes, inte värdeåret. Flera hus med olika byggår: ta det senaste.
- Grundläggning: bara byggnadens grund (grundförstärkning, sättningar, pålar o.d.), inte markarbeten på gården."""


# --- Hjälpfunktioner ---------------------------------------------------------

def las_pdf(sokvag: Path) -> str:
    """Kontrollera filen och returnera innehållet som base64-sträng."""
    if not sokvag.exists():
        sys.exit(f"Filen finns inte: {sokvag}")
    if not sokvag.is_file():
        sys.exit(f"Inte en fil: {sokvag}")
    data = sokvag.read_bytes()
    # En PDF börjar alltid med "%PDF"
    if sokvag.suffix.lower() != ".pdf" or not data.startswith(b"%PDF"):
        sys.exit(f"Filen är inte en PDF: {sokvag}")
    return base64.standard_b64encode(data).decode("utf-8")


def validera(data, schema, sokvag="") -> str | None:
    """Kontrollera att alla fält i schemat finns och har rätt form.
    Returnerar ett felmeddelande som namnger fältet, eller None om allt är OK."""
    namn = sokvag or "svaret"
    if schema.get("type") == "object":
        if not isinstance(data, dict):
            return f"Fältet '{namn}' ska vara ett objekt men är {type(data).__name__}."
        for nyckel in schema["required"]:
            delsokvag = f"{sokvag}.{nyckel}" if sokvag else nyckel
            if nyckel not in data:
                return f"Fältet '{delsokvag}' saknas i svaret."
            fel = validera(data[nyckel], schema["properties"][nyckel], delsokvag)
            if fel:
                return fel
    elif schema.get("type") == "array":
        if not isinstance(data, list):
            return f"Fältet '{namn}' ska vara en lista men är {type(data).__name__}."
        for i, post in enumerate(data):
            fel = validera(post, schema["items"], f"{sokvag}[{i}]")
            if fel:
                return fel
    return None


def rakna_falt(varde) -> tuple[int, int]:
    """Räkna (hittade, null) fält. Ett {varde, sida}-objekt eller en lista räknas som ett fält."""
    if isinstance(varde, list):
        return (1, 0) if varde else (0, 1)
    if isinstance(varde, dict):
        if "varde" in varde:
            return (0, 1) if varde["varde"] is None else (1, 0)
        hittade = saknade = 0
        for v in varde.values():
            h, s = rakna_falt(v)
            hittade += h
            saknade += s
        return hittade, saknade
    return 0, 0


# --- Huvudprogram ------------------------------------------------------------

def main():
    argument = sys.argv[1:]
    force = "--force" in argument
    argument = [a for a in argument if a != "--force"]
    if len(argument) != 1:
        sys.exit("Användning: python extract_report.py data/pdfs/<fil>.pdf [--force]")

    pdf_sokvag = Path(argument[0])
    las_pdf(pdf_sokvag)  # kontrollera filen innan något annat

    # Hoppa över API-anropet (som kostar pengar) om filen redan är extraherad
    if utfil_for(pdf_sokvag).exists() and not force:
        print("Redan extraherad – använd --force för att köra om.")
        return

    extrahera(pdf_sokvag)


def utfil_for(pdf_sokvag: Path) -> Path:
    """Sökvägen där extraktionen av en PDF sparas: data/extracted/<pdf-namn>.json"""
    return OUTPUT_DIR / f"{pdf_sokvag.stem}.json"


def extrahera(pdf_sokvag: Path) -> Path:
    """Skicka PDF:en till API:t (KOSTAR PENGAR), validera och spara svaret.
    Returnerar sökvägen till JSON-filen. Avslutar med felmeddelande vid fel."""
    pdf_base64 = las_pdf(pdf_sokvag)

    load_dotenv()
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("Hittar ingen ANTHROPIC_API_KEY. Har du skapat .env-filen?")

    client = anthropic.Anthropic(api_key=api_key)

    print(f"Skickar {pdf_sokvag.name} till {MODEL} ...")
    try:
        # Sonnet 5.5 tillåter inte tvingad tool_choice ("any"/"tool"), så vi använder
        # "auto" + instruktion. Svarets form kontrolleras med validera() nedan.
        response = client.messages.create(
            model=MODEL,
            max_tokens=16000,
            tools=[TOOL],
            tool_choice={"type": "auto"},
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_base64,
                        },
                    },
                    {"type": "text", "text": INSTRUKTION},
                ],
            }],
        )
    except anthropic.AuthenticationError:
        sys.exit("API-nyckeln är ogiltig. Kontrollera den i .env.")
    except anthropic.BadRequestError as e:
        sys.exit(f"API:t avvisade anropet (t.ex. för stor PDF): {e.message}")
    except anthropic.RateLimitError:
        sys.exit("För många anrop just nu (rate limit). Försök igen om en stund.")
    except anthropic.APIConnectionError:
        sys.exit("Kunde inte nå API:t. Kontrollera internetanslutningen.")
    except anthropic.APIStatusError as e:
        sys.exit(f"API-fel ({e.status_code}): {e.message}")

    # Kontrollera att svaret är komplett innan vi läser det
    if response.stop_reason == "refusal":
        sys.exit("Modellen avböjde att behandla dokumentet.")
    if response.stop_reason == "max_tokens":
        sys.exit("Svaret blev för långt och klipptes av (max_tokens).")

    tool_use = next(
        (b for b in response.content if b.type == "tool_use" and b.name == TOOL_NAME), None
    )
    if tool_use is None:
        sys.exit("Modellen anropade inte verktyget – ingen data extraherades. Försök igen.")

    resultat = tool_use.input
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Kontrollera att alla fält finns med rätt form. Vid fel sparas råsvaret
    # så att det går att felsöka utan att göra (och betala för) ett nytt anrop.
    fel = validera(resultat, TOOL["input_schema"])
    if fel:
        rafil = OUTPUT_DIR / f"{pdf_sokvag.stem}_raw.json"
        rafil.write_text(response.to_json(), encoding="utf-8")
        sys.exit(f"Ogiltigt svar från modellen: {fel}\nRåsvaret sparat till: {rafil}")

    # Spara resultatet som JSON
    utfil = utfil_for(pdf_sokvag)
    utfil.write_text(json.dumps(resultat, ensure_ascii=False, indent=2), encoding="utf-8")

    # Kort sammanfattning
    hittade, saknade = rakna_falt(resultat)
    namn = resultat["foreningens_namn"]["varde"] or "(okänt namn)"
    start = resultat["rakenskapsar"]["start"]["varde"] or "?"
    slut = resultat["rakenskapsar"]["slut"]["varde"] or "?"

    print("\n✅ Klart!")
    print(f"Förening:     {namn}")
    print(f"Räkenskapsår: {start} – {slut}")
    print(f"Fält:         {hittade} hittade, {saknade} null")
    print(f"Tokens:       {response.usage.input_tokens} in, {response.usage.output_tokens} ut")
    print(f"Sparat till:  {utfil}")
    return utfil


if __name__ == "__main__":
    main()
