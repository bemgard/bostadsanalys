"""
Bygg bokmärket: gör om bostadsanalys.js till en javascript:-URL och skapar installera.html.
Kör: python bokmarke/bygg.py
Öppna sedan bokmarke/installera.html i webbläsaren och dra länken till bokmärkesfältet.
"""

import html
from pathlib import Path
from urllib.parse import quote

MAPP = Path(__file__).resolve().parent
KALLKOD = MAPP / "bostadsanalys.js"
UTFIL = MAPP / "installera.html"

SIDA = """<!doctype html>
<html lang="sv">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Installera bokmärket Bostadsanalys</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; max-width: 640px; margin: 40px auto;
         padding: 0 16px; line-height: 1.5; color: #1d1d1f; background: #fff; }}
  .bokmarke {{ display: inline-block; padding: 10px 18px; border-radius: 8px; background: #0b57d0;
              color: #fff; font-weight: 600; text-decoration: none; cursor: grab; }}
  code {{ background: #f2f2f2; padding: 1px 5px; border-radius: 4px; }}
  li {{ margin-bottom: 8px; }}
  .liten {{ color: #666; font-size: 0.9em; }}
</style>
</head>
<body>
<h1>Bokmärket Bostadsanalys</h1>

<p>Dra den blå knappen till bokmärkesfältet:</p>
<p><a class="bokmarke" href="{href}" onclick="alert('Dra knappen till bokmärkesfältet i stället för att klicka på den.'); return false;">Bostadsanalys</a></p>
<p class="liten">Syns inget bokmärkesfält? Tryck <code>Cmd+Shift+B</code> (Chrome) eller välj Visa → Visa favoritfältet (Safari).</p>

<h2>Så används det</h2>
<ol>
  <li>Logga in på Booli.</li>
  <li>Öppna en <b>annons</b> och klicka på <b>Bostadsanalys</b>. Annonsens uppgifter läses och
      föreningens årsredovisning hämtas i bakgrunden.</li>
  <li>En ruta visar ett färdigt kommando, redan markerat. Tryck <code>Cmd+C</code>.
      <span class="liten">(Kan föreningssidan inte läsas i bakgrunden öppnas den i stället –
      klicka då på <b>Bostadsanalys</b> en gång till där.)</span></li>
  <li>Klistra in kommandot i Terminalen och tryck Enter.</li>
</ol>
<p>Du kan också klicka på bokmärket direkt på en föreningssida, men då kommer pris, avgift och boarea
inte med – och skuldjusterat pris och väntad avgift kan inte räknas. Börja hellre från annonsen.</p>

<p class="liten">Byggt från <code>bostadsanalys.js</code> ({storlek} tecken). Har du ändrat källkoden:
kör <code>python bokmarke/bygg.py</code>, ladda om den här sidan och dra in bokmärket på nytt.</p>
</body>
</html>
"""


def main():
    kallkod = KALLKOD.read_text(encoding="utf-8")
    # Allt kodas (även radbrytningar), så kommentarer och citattecken klarar sig i URL:en
    bokmarke = "javascript:" + quote(kallkod, safe="")
    UTFIL.write_text(SIDA.format(href=html.escape(bokmarke), storlek=len(bokmarke)), encoding="utf-8")
    print(f"✅ Bokmärke byggt ({len(bokmarke)} tecken) → {UTFIL}")


if __name__ == "__main__":
    main()
