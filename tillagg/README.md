# Chrome-tillägget Bostadsanalys

Booli visar föreningarnas årsredovisningar bara för inloggade. Tillägget låter appen
(http://localhost:8000) hämta Booli-annonsen och föreningssidan i din vanliga Chrome, där du
redan är inloggad. Då räcker det att dra in annonslänken i appen.

## Installera (en gång)
1. Öppna `chrome://extensions` i Chrome.
2. Slå på **Utvecklarläge** uppe till höger.
3. Klicka **Läs in okomprimerat** och välj den här mappen (`bostadsanalys/tillagg`).
4. Ladda om appen. Sidan `#/tillagg` i appen visar om tillägget fungerar.

## Vad det gör – och inte gör
- Får bara läsa sidor på `https://www.booli.se/` (host_permissions).
- Hämtar bara annonser (`/bostad/<id>`, `/annons/<id>`) och föreningssidor (`/bostadsrattsforening/<id>`).
- Svarar bara appen på `localhost:8000` (brygga.js körs bara där).
- Öppnar föreningssidan i en bakgrundsflik några sekunder (Booli lägger in dokumentlänken med
  JavaScript, bara för inloggade), läser sidan och stänger fliken.
- Sparar ingenting och skickar inga cookies – sidornas HTML lämnas till appen, som tolkar dem.
