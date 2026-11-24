// Bostadsanalys – brygga mellan appen (bostadsjakt.netlify.app eller localhost:8000) och tilläggets bakgrund.
// Appen skickar window.postMessage({ bostadsanalys: "ping" | "hamta", id, url }) och får svar
// tillbaka som { bostadsanalysSvar: id, ... }. Bara meddelanden från samma sida godtas.
"use strict";

window.addEventListener("message", (e) => {
  if (e.source !== window || e.origin !== location.origin) return;
  const m = e.data;
  if (!m || (m.bostadsanalys !== "ping" && m.bostadsanalys !== "hamta") || typeof m.id !== "string") return;
  chrome.runtime.sendMessage({ typ: m.bostadsanalys, url: m.url }, (svar) => {
    const fel = chrome.runtime.lastError ? chrome.runtime.lastError.message : null;
    window.postMessage({ bostadsanalysSvar: m.id, ...(svar || { ok: false, fel: fel || "Inget svar från tillägget." }) }, location.origin);
  });
});
document.documentElement.dataset.bostadsanalysTillagg = "1";
