// Bostadsanalys – tilläggets bakgrund. Hämtar BARA Booli-annonser och föreningssidor,
// med användarens vanliga inloggning i Chrome, och lämnar sidornas HTML till appen på
// localhost via brygga.js. Inget annat läses, skickas eller sparas.
"use strict";

const ANNONS = /^https:\/\/www\.booli\.se\/(bostad|annons)\/\d+$/;
const FORENING = /\/bostadsrattsforening\/\d+(?=["'?#\/\\]|$)/;

async function hamtaText(url) {
  const svar = await fetch(url, { credentials: "include", redirect: "follow" });
  if (!svar.ok) throw new Error(`Booli svarade ${svar.status}`);
  return svar.text();
}

async function hamtaAnnons(url) {
  url = String(url || "").split(/[?#]/)[0].replace(/\/$/, "");
  if (!ANNONS.test(url)) throw new Error("Ingen Booli-annons.");
  const annonsHtml = await hamtaText(url);
  const m = annonsHtml.match(FORENING);
  const foreningHtml = m ? await hamtaText("https://www.booli.se" + m[0]) : null;
  return { annons_url: url, annons_html: annonsHtml, forening_html: foreningHtml };
}

chrome.runtime.onMessage.addListener((meddelande, avsandare, svara) => {
  // Bara från tilläggets egen brygga på localhost
  if (!avsandare.tab || !/^http:\/\/(localhost|127\.0\.0\.1):8000\//.test(avsandare.url || "")) return;
  if (meddelande && meddelande.typ === "ping") { svara({ ok: true, version: chrome.runtime.getManifest().version }); return; }
  if (meddelande && meddelande.typ === "hamta") {
    hamtaAnnons(meddelande.url)
      .then((data) => svara({ ok: true, data }))
      .catch((fel) => svara({ ok: false, fel: String(fel.message || fel) }));
    return true; // svarar asynkront
  }
});
