# Överlämning – Bostadsanalys i molnet (Fas 3)

Senast uppdaterad 2026-11-24.

## Så hänger det ihop

```
Mobil/dator ──► bostadsjakt.netlify.app (app/static, inget byggsteg)
                   │  /api/*  (proxy i netlify.toml – samma adress, ingen CORS)
                   ▼
                bostadsjakt.onrender.com (app/server.py, Render Free, Frankfurt)
                   │  service_role (env-var) / användarens JWT
                   ▼
                Supabase uowaovwyyvbvdtgscyvu (eu-west-1)
                  Auth (magisk länk, bara inbjudna) · Postgres med RLS · Storage "arsredovisningar" (privat)
Chrome-tillägget (tillagg/) ── hämtar Booli-sidor med din inloggning ──► appen på Netlify
```

- **Inloggning:** Supabase Auth med magisk länk direkt från `app.js` (inga bibliotek). Backenden
  verifierar token på varje `/api/`-anrop mot `/auth/v1/user` (cache 1 min).
- **Hushåll:** varje ny användare får ett eget hushåll (trigger `ny_anvandare`). Objekten är rader
  i `annonser` och läses med användarens token, så RLS (`ar_medlem`) gäller även om backenden har en bugg.
- **Delad cache:** `dokument` (PDF via kontrollsumma), `bedomningar`, `foreningar`. Samma PDF
  extraheras aldrig två gånger, oavsett vem som laddar upp den.
- **Kostnad:** extraktion kräver bekräftelse (402) och plats under `MANADSTAK_EXTRAKTIONER`
  per användare och kalendermånad (429). Varje anrop till Claude loggas i `extraktionslogg`.
- **Extraktionen körs som jobb** (`/api/analysera` → 202, appen frågar `/api/jobb/<id>`), eftersom
  Netlifys proxy inte väntar en hel minut. Jobben ligger i minnet. Startas servern om under en
  extraktion får man försöka igen (PDF:en ligger kvar).
- **PDF:er** lämnas bara ut via `/api/pdf/<id>` → signerad länk som gäller 5 minuter.

## Hemligheter (repot är PUBLIKT)

| Nyckel | Var | I git? |
|---|---|---|
| `SUPABASE_SERVICE_ROLE_KEY` | Render (env), lokala `.env` | Aldrig |
| `ANTHROPIC_API_KEY` | Render (env), lokala `.env` | Aldrig |
| `SUPABASE_PUBLISHABLE_KEY` | `app/static/config.js`, `render.yaml` | Ja – publik, skyddas av RLS |

## Status

- [x] Schema, RLS och trigger (`bostadsanalys_schema_och_rls`, `harda_hjalpfunktioner`)
- [x] Privat bucket `arsredovisningar`, unika nycklar och index för månadstaket (`fas3_storage_och_tak`)
- [x] Migration `annons_pekar_pa_dokument` (kolumnen `annonser.dokument_id`)
- [ ] Auth: stäng av öppen registrering, magisk länk, Site URL/Redirect URL = https://bostadsjakt.netlify.app (Calle i dashboarden)
- [ ] Bjud in Calle och sambon; flytta sambon till Calles hushåll (SQL nedan)
- [x] Backend mot Supabase, med tester (`tests/test_server.py` mot en låtsas-Supabase)
- [x] Gränssnitt med inloggning, köpartyp på kontot, uppladdning från mobilen och jobbkö
- [x] Tillägget: brödsmulan går först, servern kontrollerar föreningssidan, Netlify-adressen tillåten (v1.2)
- [x] Migreringsskript `migrera_till_moln.py` (idempotent, torrkörning som standard)
- [ ] Kör migreringen (torrt, sedan `--kor`)
- [x] Pushat till GitHub (hela trädet och historiken genomsökta efter nycklar först – rent)
- [x] Render: tjänsten `bostadsjakt` (srv-dc2pevtg1s2s739hlf0g, Frankfurt, Free, auto-deploy från main) – live
- [ ] Render: sätt `SUPABASE_SERVICE_ROLE_KEY` och `ANTHROPIC_API_KEY` under Environment (Calle)
- [x] Netlify: sajten `bostadsjakt` skapad (bostadsjakt.netlify.app)
- [ ] Netlify: koppla repot bemgard/bostadsanalys, gren main (Calle i UI:t – `netlify.toml` sköter resten)
- [ ] Ladda om tillägget i Chrome (chrome://extensions → uppdatera)
- [ ] Prova: mobil-inloggning → köpartyp → ladda upp PDF → resultat; tillägget på datorn; sambo ser samma; vän ser bara sitt

## Sambon i samma hushåll (efter inbjudan)

```sql
-- byt e-postadresserna
with calle as (select i.hushall_id from auth.users u join anvandar_installningar i on i.user_id = u.id
               where u.email = 'CALLE@…'),
     sambo as (select u.id, i.hushall_id as eget from auth.users u join anvandar_installningar i on i.user_id = u.id
               where u.email = 'SAMBO@…'),
     flytt as (update hushall_medlemmar m set hushall_id = (select hushall_id from calle), roll = 'medlem'
               from sambo where m.user_id = sambo.id returning sambo.eget),
     inst  as (update anvandar_installningar i set hushall_id = (select hushall_id from calle)
               from sambo where i.user_id = sambo.id returning 1)
delete from hushall where id in (select eget from flytt)
  and not exists (select 1 from annonser a where a.hushall_id = hushall.id);
```

## Drift

- **Render Free somnar** efter 15 minuters stillhet. Första anropet tar då upp till en minut och
  appen visar "Väcker servern…".
- **Byta backendadress:** ändra `to` i `netlify.toml` (står bara där).
- **Ändra månadstaket:** env-varen `MANADSTAK_EXTRAKTIONER` på Render.
- **Lokalt:** `venv/bin/python -m uvicorn app.server:app --port 8000` med Supabase-nycklarna i `.env`.
  Det går mot samma databas som molnet.
- **CLI-kedjan** (`analysera.py`, `extract_report.py`, `bedomning.py`, `export_excel.py`) jobbar
  fortfarande mot `data/` lokalt och påverkas inte av molnet.

## Utredning: Frejgatan 53 och Sveavägen 99 → samma förening

Båda annonserna pekar på HSB Brf Nejlikan 31 & 33 (702001-5199) och samma PDF. **Troligen en äkta
hörnfastighet**: föreningen består av två fastigheter (8 258 kvm bostadsyta, byggd 1926), och
avgiften per kvm stämmer för båda (705 och 731 kr/kvm/år mot 673 kr/kvm 2025 + 5 % 2026 ≈ 707).
Det är olika lägenheter (olika pris, yta och annons-id). Adresserna gick inte att bekräfta i PDF:en
(inskannad) eller på Booli (403 för automatiska hämtningar). Kontrollera föreningslänken på
de två annonserna.

Utredningen hittade en riktig lucka: tillägget tog *första* föreningslänken i annonsens HTML,
medan servern läste annonsens förening ur brödsmulorna, och ingen kontrollerade att de var samma.
Nu läser tillägget brödsmulan först och skickar med vilken föreningssida det läste. Servern
avvisar svaret om sidan inte är annonsens förening.
