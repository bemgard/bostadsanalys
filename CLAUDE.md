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

**Arbetsflöde:** bokmärket på Booli (annons → föreningssida) kopierar ett kommando →
`analysera.py` laddar ner PDF:en, extraherar (frågar först, kostar ca 1–2 kr), bedömer och
uppdaterar Excel.

| Fil | Gör |
|---|---|
| `analysera.py` | Hela kedjan i ett kommando; sparar annonsuppgifter i `data/annonser.json` |
| `extract_report.py` | PDF → JSON med Claude (tool use + `validera()`); `--force` kör om |
| `bedomning.py` | Nyckeltal, färger, utslag och mäklarfrågor |
| `kriterier.py` | Alla gränsvärden och nyckelord – ändra gränser här, inte i koden |
| `rimlighet.py` | Rimlighetskontroller av extraktionen (ytor, lånenot, typer, sidnummer) – varnar, ändrar inte färger |
| `lagenhet.py` | Nyckeltal för lägenheten (skuldjusterat pris, avgift efter beslutade höjningar) |
| `export_excel.py` | Bygger `output/bostadsanalys.xlsx` (en rad per annons) |
| `bokmarke/` | Bokmärket (`bostadsanalys.js`), `bygg.py` → `installera.html` |

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
node bokmarke/test_bokmarke.js
```
