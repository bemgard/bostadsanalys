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

// Booli lägger in dokumentlänkarna med sidans JavaScript, och bara för inloggade. Därför
// öppnas föreningssidan i en bakgrundsflik, vi väntar tills en dokumentlänk syns (som när du
// själv tittar på sidan), läser sidan och stänger fliken.
async function lasRenderadSida(url, maxMs = 15000) {
  const flik = await chrome.tabs.create({ url, active: false });
  try {
    await new Promise((klar) => {
      const lyssna = (id, info) => {
        if (id === flik.id && info.status === "complete") { chrome.tabs.onUpdated.removeListener(lyssna); klar(); }
      };
      chrome.tabs.onUpdated.addListener(lyssna);
      setTimeout(() => { chrome.tabs.onUpdated.removeListener(lyssna); klar(); }, maxMs);
    });
    const [resultat] = await chrome.scripting.executeScript({
      target: { tabId: flik.id },
      args: [maxMs],
      func: async (vantaMs) => {
        const start = Date.now();
        while (Date.now() - start < vantaMs) {
          if (document.querySelector('a[href^="https://documents.bcdn.se/"]')) break;
          await new Promise((r) => setTimeout(r, 300));
        }
        return { html: document.documentElement.outerHTML,
                 inloggad: !document.querySelector('a[aria-label^="Logga in"]') };
      },
    });
    return resultat.result;
  } finally {
    chrome.tabs.remove(flik.id).catch(() => {});
  }
}

async function hamtaAnnons(url) {
  url = String(url || "").split(/[?#]/)[0].replace(/\/$/, "");
  if (!ANNONS.test(url)) throw new Error("Ingen Booli-annons.");
  const annonsHtml = await hamtaText(url);
  const m = annonsHtml.match(FORENING);
  let foreningHtml = null, inloggad = null;
  if (m) {
    const sida = await lasRenderadSida("https://www.booli.se" + m[0]);
    foreningHtml = sida.html; inloggad = sida.inloggad;
  }
  return { annons_url: url, annons_html: annonsHtml, forening_html: foreningHtml, inloggad };
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
