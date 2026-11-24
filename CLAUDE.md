# CLAUDE.md

## Regler

- Kör aldrig extract_report.py eller något annat som anropar Claude-API:t utan att först fråga användaren. Det kostar pengar.
- Starta aldrig andra program på datorn (webbläsare, appar) och installera inget utan att fråga först.

## Projektet

Sållar bostadsrätter till salu på Booli genom att läsa föreningens årsredovisning och ge ett
utslag: GÅ VIDARE, AVVAKTA eller SORTERA BORT, med frågor till mäklaren.

**Princip: Claude extraherar – Python räknar och bedömer.** Claude-API:t läser bara av värden ur
PDF:en (med sidnummer, null om något saknas, aldrig gissat eller uträknat). Alla nyckeltal, färger
och utslag räknas i Python mot gränserna i kriterier.py.

**Webbappen** (`app/`): `venv/bin/python -m uvicorn app.server:app --port 8000` → http://localhost:8000.
FastAPI-server (`app/server.py`) runt samma kedja + statiskt gränssnitt (`app/static/`, inget byggsteg).
Extraktionen körs bara efter att användaren bekräftat kostnaden i appen. Excel är valfritt
(knapp i appen, `--excel` i terminalen).

**Arbetsflöde:** bokmärket på Booli (annons → föreningssida) kopierar ett kommando →
`analysera.py` laddar ner PDF:en, extraherar (frågar först, kostar ca 1–2 kr), bedömer och
uppdaterar Excel.

| Fil | Gör |
|---|---|
| `analysera.py` | Hela kedjan i ett kommando; sparar annonsuppgifter i `data/annonser.json` |
| `extract_report.py` | PDF → JSON med Claude (tool use + `validera()`); `--force` kör om |
| `bedomning.py` | Nyckeltal, färger, utslag och mäklarfrågor |
| `kriterier.py` | Alla gränsvärden och nyckelord – ändra gränser här, inte i koden |
| `utslag.py` | Utslaget: stoppfaktorer, viktad poäng 0–100, motivering och datakvalitet |
| `rimlighet.py` | Rimlighetskontroller av extraktionen (ytor, lånenot, typer, sidnummer) – varnar, ändrar inte färger |
| `lagenhet.py` | Nyckeltal för lägenheten (skuldjusterat pris, avgift efter beslutade höjningar) |
| `booli.py` | Läser Booli-annonsen och föreningssidan (samma logik som bokmärket) – för ett drag i appen |
| `tillagg/` | Chrome-tillägg: hämtar Booli-sidor i inloggad Chrome åt appen (ett drag med annonslänken) |
| `app/server.py` | Webbappens API – ingen analyslogik, bara kedjan ovan |
| `app/static/` | Gränssnittet: översikt, ny analys (dropzon), resultat med bubblor |
| `export_excel.py` | Bygger `output/bostadsanalys.xlsx` (en rad per annons) |
| `bokmarke/` | Bokmärket (`bostadsanalys.js`), `bygg.py` → `installera.html` |
| `app/server.py` | Webbappens backend (FastAPI): Supabase-JWT på varje anrop, extraktion som jobb, månadstak |
| `app/moln.py` | Supabase-lagret (PostgREST, Storage, Auth) med httpx |
| `app/static/` | Gränssnittet (inget byggsteg) – publiceras av Netlify; `config.js` = publik Supabase-nyckel |
| `tillagg/` | Chrome-tillägget som hämtar Booli-sidor med användarens inloggning |
| `migrera_till_moln.py` | Idempotent flytt av `data/` till Supabase (torrkörning utan `--kor`) |

**Molnet:** Netlify (`bostadsjakt`, `netlify.toml`) → `/api/*` proxas till Render (`render.yaml`) →
Supabase (projekt `uowaovwyyvbvdtgscyvu`, privat bucket `arsredovisningar`, RLS per hushåll).
Hemliga nycklar (service_role, Anthropic) bara som env-var på Render och i lokala `.env` – repot är publikt.
Se `docs/overlamning.md`.

**Data** (inte i git): `data/pdfs/` (PDF:er, prefix från URL:ens unika del), `data/extracted/`
(Claudes JSON), `data/bedomning/` (bedömningar), `data/annonser.json`, `output/` (Excel).
Samma filnamn (stam) följer PDF → extraktion → bedömning. Nya schemafält kräver `--force` på
äldre extraktioner – bedömningen säger då "Extraktionen är gjord med en äldre version".

**Tester** (inga API-anrop):
```
venv/bin/python tests/test_extraktion.py   # facit för Astrea 4 mot data/extracted/
venv/bin/python tests/test_byggdelar.py
venv/bin/python tests/test_skuld.py
venv/bin/python tests/test_pdf_namn.py
venv/bin/python tests/test_lagenhet.py
venv/bin/python tests/test_rimlighet.py
venv/bin/python tests/test_avgiftshojningar.py
venv/bin/python tests/test_avgiftsniva.py
venv/bin/python tests/test_utslag.py
venv/bin/python tests/test_booli.py
venv/bin/python tests/test_server.py   # API:t mot en låtsas-Supabase (fastapi + httpx)
node bokmarke/test_bokmarke.js
```
