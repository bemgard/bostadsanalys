// Bostadsanalys – gränssnittet. Inga beroenden, inget byggsteg.
// Vyer (hash-adresser): #/ översikt · #/ny ny analys · #/objekt/<id> resultat · inloggning
// Inloggning: Supabase Auth med magisk länk (bara inbjudna). Adress och publik nyckel i config.js.
"use strict";

const vy = document.getElementById("vy");
const FARG = { "GÅ VIDARE": "grön", "AVVAKTA": "gul", "SORTERA BORT": "röd" };
const UTSLAGSTEXT = { "GÅ VIDARE": "Gå vidare", "AVVAKTA": "Avvakta", "SORTERA BORT": "Sortera bort" };
const HUS = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 11.5 12 4l9 7.5M5.5 10v9.5h13V10" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><path d="M10 19.5v-5h4v5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg>';

// --- Hjälpfunktioner ---------------------------------------------------------

// All text från servern går genom esc() – årsredovisningar och annonser är främmande data
function esc(x) {
  return String(x ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
const nf = new Intl.NumberFormat("sv-SE", { maximumFractionDigits: 0 });
function kr(x, enhet = "kr") { return x == null ? "–" : `${nf.format(Math.round(x))} ${enhet}`; }
function mkr(x) { return x == null ? "–" : `${(x / 1e6).toLocaleString("sv-SE", { maximumFractionDigits: 2 })} Mkr`; }

// --- Inloggning (Supabase Auth, magisk länk) ------------------------------------
const KONFIG = window.BOSTADSANALYS || {};
const SESSION = "session";

function lasSession() { try { return JSON.parse(localStorage.getItem(SESSION) || "null"); } catch { return null; } }
function sparaSession(s) { try { s ? localStorage.setItem(SESSION, JSON.stringify(s)) : localStorage.removeItem(SESSION); } catch { /* privat läge */ } }

// Efter klick på länken i mejlet kommer man tillbaka med #access_token=…&refresh_token=… i adressen
function taEmotInloggning() {
  const h = new URLSearchParams(location.hash.replace(/^#/, ""));
  if (h.get("access_token") && h.get("refresh_token")) {
    sparaSession({ access_token: h.get("access_token"), refresh_token: h.get("refresh_token"),
                   expires_at: Date.now() / 1000 + Number(h.get("expires_in") || 3600) });
    history.replaceState(null, "", location.pathname + "#/");
  } else if (h.get("error_description")) {
    history.replaceState(null, "", location.pathname + "#/");
    return h.get("error_description").replace(/\+/g, " ");
  }
  return null;
}

async function auth(sokvag, kropp) {
  const svar = await fetch(`${KONFIG.supabaseUrl}/auth/v1/${sokvag}`, {
    method: "POST", headers: { "Content-Type": "application/json", apikey: KONFIG.supabaseKey },
    body: JSON.stringify(kropp),
  });
  const data = await svar.json().catch(() => ({}));
  if (!svar.ok) throw new Error(data.msg || data.error_description || data.message || `Fel ${svar.status}`);
  return data;
}

let fornyar = null;
async function giltigToken(tvinga = false) {
  const s = lasSession();
  if (!s) return null;
  if (!tvinga && s.expires_at - Date.now() / 1000 > 60) return s.access_token;
  fornyar = fornyar || auth("token?grant_type=refresh_token", { refresh_token: s.refresh_token })
    .then((d) => { sparaSession({ access_token: d.access_token, refresh_token: d.refresh_token, expires_at: d.expires_at || Date.now() / 1000 + d.expires_in }); return d.access_token; })
    .catch(() => { sparaSession(null); return null; })
    .finally(() => { fornyar = null; });
  return fornyar;
}

function loggaUt() {
  const s = lasSession();
  if (s) fetch(`${KONFIG.supabaseUrl}/auth/v1/logout`, { method: "POST", headers: { apikey: KONFIG.supabaseKey, Authorization: `Bearer ${s.access_token}` } }).catch(() => {});
  sparaSession(null); PROFILER = null; visaLogin();
}

function visaLogin(meddelande) {
  satNav("");
  document.getElementById("konto").innerHTML = "";
  vy.innerHTML = `<div class="kort inlogg">
    <h1>Logga in</h1>
    <p class="dampad">Skriv din e-postadress så får du en inloggningslänk. Bara inbjudna kan logga in.</p>
    <form id="loggain"><label for="epost">E-post</label>
      <input type="email" id="epost" autocomplete="email" required>
      <div class="knapprad"><button class="knapp primar" type="submit">Skicka länk</button></div></form>
    <div id="status">${meddelande ? `<div class="fel">${esc(meddelande)}</div>` : ""}</div></div>`;
  document.getElementById("loggain").addEventListener("submit", async (e) => {
    e.preventDefault();
    const knapp = e.target.querySelector("button");
    knapp.disabled = true;
    try {
      // create_user: false – inga nya konton härifrån, bara inbjudna
      await auth(`otp?redirect_to=${encodeURIComponent(location.origin + location.pathname)}`,
                 { email: document.getElementById("epost").value.trim(), create_user: false });
      document.getElementById("status").innerHTML = '<div class="kort kostnad" style="margin-top:1rem">Kolla din e-post och klicka på länken. Du kan stänga den här fliken.</div>';
    } catch (err) { knapp.disabled = false; visaFel(err.message); }
  });
}

class EjInloggad extends Error {}

// Render (gratisnivån) somnar efter en kvarts stillhet och tar ungefär en minut att väcka.
// Under tiden svarar proxyn med fel 502–504 eller inte alls – då försöker vi igen en stund.
async function hamta(sokvag, alternativ, token) {
  const huvuden = { ...(alternativ.headers || {}), Authorization: `Bearer ${token}` };
  for (let forsok = 0; ; forsok++) {
    try {
      const svar = await fetch(sokvag, { ...alternativ, headers: huvuden });
      if (![502, 503, 504].includes(svar.status) || forsok >= 8) return svar;
    } catch (err) { if (forsok >= 8) throw new Error("Servern svarar inte. Försök igen om en stund."); }
    if (forsok === 0) document.getElementById("vackning").hidden = false;
    await new Promise((r) => setTimeout(r, 8000));
  }
}

async function api(sokvag, alternativ = {}, som = "json") {
  let token = await giltigToken();
  if (!token) throw new EjInloggad();
  let svar;
  try {
    svar = await hamta(sokvag, alternativ, token);
    if (svar.status === 401) {
      token = await giltigToken(true);
      if (!token) throw new EjInloggad();
      svar = await hamta(sokvag, alternativ, token);
      if (svar.status === 401) { sparaSession(null); throw new EjInloggad(); }
    }
  } finally { document.getElementById("vackning").hidden = true; }
  if (som === "blob" && svar.ok) return svar.blob();
  let data = null;
  try { data = await svar.json(); } catch { /* inte JSON */ }
  if (!svar.ok) {
    const fel = new Error((data && data.detail) || `Fel ${svar.status}`);
    fel.status = svar.status; fel.data = data;
    throw fel;
  }
  if (data && typeof data === "object" && !Array.isArray(data)) data._status = svar.status;
  return data;
}

function satNav(namn) {
  document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("aktiv", a.dataset.nav === namn));
}

// --- Köparprofil (köpartyp) --------------------------------------------------
// Profilerna och användarens val hämtas en gång från servern. Valet sparas på kontot.
let PROFILER = null;
async function lasProfiler() {
  if (!PROFILER) PROFILER = await api("/api/profiler");
  return PROFILER;
}
function hamtaLagrat(nyckel) { try { return localStorage.getItem(nyckel); } catch { return null; } }
function lagra(nyckel, varde) { try { localStorage.setItem(nyckel, varde); } catch { /* privat läge */ } }
function valdProfil() { return (PROFILER && (PROFILER.vald || PROFILER.standard)) || "par"; }
async function sparaProfil(id) {
  await api("/api/installningar", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ koparprofil: id }) });
  if (PROFILER) PROFILER.vald = id;
}
function profilnamn(id) { return (PROFILER && (PROFILER.profiler.find((p) => p.id === id) || {}).namn) || id; }

// Segmenterad väljare för köpartyp. aktiv = markerad profil.
function profilvaljare(aktiv) {
  if (!PROFILER) return "";
  return `<div class="profilval" role="group" aria-label="Köpartyp">${PROFILER.profiler.map((p) =>
    `<button type="button" class="profilknapp${p.id === aktiv ? " vald" : ""}" data-profil="${esc(p.id)}" aria-pressed="${p.id === aktiv}">${esc(p.namn)}</button>`
  ).join("")}</div>`;
}

// Motiveringen börjar med "AVVAKTA (67/100)." – det visas redan i rubriken
function utanRubrik(motivering) {
  return String(motivering || "").replace(/^(GÅ VIDARE|AVVAKTA|SORTERA BORT)( \(\S+\/100\))?\.?\s*(–\s*)?/, "");
}

// --- Översikt ----------------------------------------------------------------

async function visaOversikt() {
  satNav("oversikt");
  vy.innerHTML = '<p class="dampad">Hämtar objekt…</p>';
  const objekt = await api("/api/objekt");
  if (!objekt.length) {
    vy.innerHTML = `<div class="kort tomt"><h1>Inga objekt än</h1>
      <p class="dampad">Ladda upp en årsredovisning eller dra in en Booli-annons på datorn.</p>
      <a class="knapp primar" href="#/ny">Ny analys</a></div>`;
    return;
  }
  vy.innerHTML = `
    <div class="rad"><div><h1>Översikt</h1><p class="dampad" style="margin:0">${objekt.length} objekt · bäst först</p></div>
      <div class="knapprad" style="margin:0">
        <button class="knapp" id="export">Exportera till Excel</button>
        <a class="knapp primar" href="#/ny">Ny analys</a>
      </div></div>
    <div class="rutnat" style="margin-top:1.25rem">${objekt.map(objektkort).join("")}</div>`;
  document.getElementById("export").addEventListener("click", async (e) => {
    e.target.disabled = true;
    try {
      const blob = await api("/api/export.xlsx", {}, "blob");
      const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: "bostadsanalys.xlsx" });
      a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 10000);
    } catch (err) { if (err instanceof EjInloggad) return visaLogin(); alert(err.message); }
    e.target.disabled = false;
  });
}

function objektkort(o) {
  const farg = FARG[o.utslag] || "saknas";
  return `<a class="kort objektkort ${farg}" href="#/objekt/${encodeURIComponent(o.id)}">
    <div class="rad"><span class="pill ${farg}">${esc(UTSLAGSTEXT[o.utslag] || o.utslag)}</span>
      <span class="poang" style="font-size:20px">${esc(o.poang ?? "–")}<small>/100</small></span></div>
    <h3>${esc(o.adress || o.forening)}</h3>
    <div class="dampad">${esc(o.forening)}${o.kvm ? ` · ${esc(o.rum ?? "?")} rum · ${esc(o.kvm)} kvm` : ""}</div>
    <div class="siffror">
      <div><span class="dampad">Pris</span><b>${mkr(o.pris)}</b></div>
      <div><span class="dampad">Skuldjusterat</span><b>${kr(o.skuldjusterat_pris_per_kvm, "kr/kvm")}</b></div>
      <div><span class="dampad">Väntad avgift</span><b>${kr(o.vantad_avgift, "kr/mån")}</b></div>
      <div><span class="dampad">Data</span><b>${esc(o.datakvalitet || "–")}</b></div>
    </div></a>`;
}

// --- Resultat ----------------------------------------------------------------

async function visaObjekt(id) {
  satNav("");
  vy.innerHTML = '<p class="dampad">Hämtar analysen…</p>';
  await lasProfiler();
  const d = await api(`/api/objekt/${encodeURIComponent(id)}`);
  const b = d.bedomning, a = d.annons || {}, t = d.lagenhet;
  const farg = FARG[b.utslag] || "saknas";
  const profil = b.koparprofil || (PROFILER && PROFILER.standard);
  const rader = b.nyckeltal.filter((r) => r.farg !== "info");
  const ordning = { "röd": 0, "gul": 1, "saknas": 2, "grön": 3 };
  const sortera = (lista) => lista.slice().sort((x, y) => (ordning[x.farg] ?? 9) - (ordning[y.farg] ?? 9));
  const tunga = sortera(rader.filter((r) => r.tung));
  const ovriga = sortera(rader.filter((r) => !r.tung));
  const bocka = JSON.parse(hamtaLagrat(`bocka:${id}`) || "[]");

  vy.innerHTML = `
    <div class="kort ${farg}">
      <div class="rad">
        <div><h1>${esc(a.adress || b.forening)}</h1>
          <div class="dampad">${esc(b.forening)}${t.kvm ? ` · ${esc(t.rum ?? "?")} rum · ${esc(t.kvm)} kvm` : ""} · årsredovisning t.o.m. ${esc(b.rakenskapsar_slut || "?")}</div></div>
        <div style="display:flex;align-items:center;gap:.75rem">
          <span class="pill ${farg}" style="font-size:16px">${esc(UTSLAGSTEXT[b.utslag] || b.utslag)}</span>
          <span class="poang">${esc(b.poang ?? "–")}<small>/100</small></span></div>
      </div>
      <div class="prat"><div class="figur">${HUS}</div>
        <div class="text">${esc(utanRubrik(b.motivering))}</div></div>
      <div class="knapprad">
        <span class="pill ${b.datakvalitet === "Säker" ? "grön" : "gul"}" title="${esc(b.datakvalitet_forklaring)}">Data: ${esc(b.datakvalitet || "–")}</span>
        <span class="dampad" style="align-self:center">${esc(b.datakvalitet_forklaring || "")}</span>
      </div>
    </div>

    <div class="rad profilrad">
      <div class="dampad">Köpartyp: <b>${esc(profilnamn(profil))}</b>${b.renoveringshorisont_ar ? ` · räknar underhåll ~${esc(b.renoveringshorisont_ar)} år fram` : ""}</div>
      ${profilvaljare(profil)}
    </div>

    ${t.pris || t.avgift ? `<h2>Lägenheten</h2>
    <div class="tal">
      <div><span>Pris</span><b>${kr(t.pris)}</b></div>
      <div><span>Pris per kvm</span><b>${kr(t.pris_per_kvm)}</b></div>
      <div><span>Skuldjusterat per kvm</span><b>${kr(t.skuldjusterat_pris_per_kvm)}</b></div>
      <div><span>Avgift</span><b>${kr(t.avgift, "kr/mån")}</b></div>
      <div><span>Väntad avgift</span><b>${kr(t.vantad_avgift, "kr/mån")}</b></div>
    </div>` : `<p class="kort dampad" style="margin-top:1.5rem">Inga annonsuppgifter – analysera från annonsen för att få pris, skuldjusterat pris och väntad avgift.</p>`}

    <h2>Det viktigaste</h2>
    <div class="bubblor">${tunga.map(bubbla).join("")}</div>
    <h2>Övrigt</h2>
    <div class="bubblor">${ovriga.map(bubbla).join("")}</div>

    ${b.varningar && b.varningar.length ? `<h2>Kontrollera i årsredovisningen</h2>
      <div class="kort varning"><ul style="margin:0;padding-left:1.2rem">${b.varningar.map((v) => `<li>${esc(v)}</li>`).join("")}</ul></div>` : ""}

    ${b.fragor_till_maklare.length ? `<h2>Frågor till mäklaren</h2>
      <div class="kort fragor">${b.fragor_till_maklare.map((f, i) =>
        `<label><input type="checkbox" data-i="${i}" ${bocka.includes(i) ? "checked" : ""}><span>${esc(f)}</span></label>`).join("")}</div>` : ""}

    <div class="knapprad" style="margin-top:2rem">
      ${d.pdf_finns ? '<button class="knapp" id="oppnaPdf">Öppna årsredovisningen</button>' : ""}
      ${a.annons_url ? `<a class="knapp" href="${esc(a.annons_url)}" target="_blank" rel="noopener">Visa på Booli</a>` : ""}
      <button class="knapp" id="bedomOm" title="Gratis – inget API-anrop">Bedöm om med dagens datum</button>
      <button class="knapp" id="arkivera">Arkivera</button>
    </div>
    <p class="dampad">Bedömd ${esc(b.idag)} · marknadsränta ${esc(d.marknadsranta_procent)} %</p>`;

  vy.querySelectorAll(".fragor input").forEach((cb) => cb.addEventListener("change", () => {
    const valda = [...vy.querySelectorAll(".fragor input:checked")].map((x) => Number(x.dataset.i));
    lagra(`bocka:${id}`, JSON.stringify(valda));
  }));
  // Årsredovisningen ligger i en privat bucket: hämta en kortlivad länk och öppna den.
  // Fönstret öppnas direkt vid klicket (annars stoppar mobilens popup-spärr det).
  document.getElementById("oppnaPdf")?.addEventListener("click", async () => {
    const fonster = window.open("", "_blank");
    try {
      const { url } = await api(`/api/pdf/${encodeURIComponent(id)}`);
      if (fonster) { fonster.opener = null; fonster.location = url; } else location.href = url;
    } catch (err) { if (fonster) fonster.close(); alert(err.message); }
  });
  document.getElementById("bedomOm").addEventListener("click", async (e) => {
    e.target.disabled = true;
    try {
      await api(`/api/objekt/${encodeURIComponent(id)}/bedom-om`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profil }),
      });
      visaObjekt(id);
    } catch (err) { alert(err.message); e.target.disabled = false; }
  });
  // Byt köpartyp: kör om bedömningen (gratis) med den valda profilen
  vy.querySelector(".profilrad .profilval")?.addEventListener("click", async (e) => {
    const knapp = e.target.closest("[data-profil]");
    if (!knapp || knapp.classList.contains("vald")) return;
    vy.querySelectorAll(".profilrad .profilknapp").forEach((x) => (x.disabled = true));
    try {
      await api(`/api/objekt/${encodeURIComponent(id)}/bedom-om`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profil: knapp.dataset.profil }),
      });
      if (PROFILER) PROFILER.vald = knapp.dataset.profil;
      visaObjekt(id);
    } catch (err) { alert(err.message); vy.querySelectorAll(".profilrad .profilknapp").forEach((x) => (x.disabled = false)); }
  });
  document.getElementById("arkivera").addEventListener("click", async () => {
    if (!confirm("Arkivera objektet? Det försvinner från översikten för hela hushållet. Inget raderas.")) return;
    try { await api(`/api/objekt/${encodeURIComponent(id)}/arkivera`, { method: "POST" }); location.hash = "#/"; }
    catch (err) { alert(err.message); }
  });
}

function forstaMening(text) {
  const t = String(text || "");
  const m = t.match(/^.+?[.!?](\s|$)/);
  return (m ? m[0] : t).trim();
}

const MAX_VARDE = 26;  // längre värden kortas så att bubblan förblir en bubbla

// Det stora talet i bubblan: värdet om det är kort, annars den korta risktexten,
// annars första ledet ("100 % inom 24 mån, snitt …" → "100 % inom 24 mån").
// Den korta risktexten visas under om den inte redan blev värdet.
function bubbelvarde(r) {
  const vart = String(r.vart_varde ?? "–");
  let varde = vart;
  if (vart.length > MAX_VARDE) {
    varde = r.kort && r.kort.length <= 40 ? r.kort : vart.split(/[,;]/)[0];
  }
  varde = varde.charAt(0).toUpperCase() + varde.slice(1);
  const extra = r.kort && r.farg !== "grön" && r.kort.toLowerCase() !== varde.toLowerCase() ? r.kort : "";
  return { varde, extra };
}

function bubbla(r, i) {
  const sidor = r.sidor && r.sidor.length ? `s. ${r.sidor.join(", ")}` : "";
  const { varde, extra } = bubbelvarde(r);
  return `<div class="bubbla ${esc(r.farg)}" style="animation-delay:${i * 40}ms" title="${esc(r.kommentar)}">
    <div class="namn"><span>${esc(r.nyckeltal)}</span><span class="sida">${esc(sidor)}</span></div>
    <div class="varde">${esc(varde)}</div>
    <div class="kommentar">${esc(forstaMening(r.kommentar))}</div>
    ${extra ? `<div class="kommentar detalj">${esc(extra.charAt(0).toUpperCase() + extra.slice(1))}</div>` : ""}
  </div>`;
}

// --- Ny analys ---------------------------------------------------------------

async function visaNy(param) {
  satNav("ny");
  await lasProfiler();
  const v = (n) => esc(param.get(n) || "");
  vy.innerHTML = `
    <h1>Ny analys</h1>
    <p class="dampad">Välj årsredovisningens PDF – i mobilen eller på datorn. På datorn kan du också dra in länken till Booli-annonsen (eller klistra in den med Cmd+V); då hämtas pris, avgift, storlek och årsredovisning automatiskt med <a href="#/tillagg">tillägget i Chrome</a>.</p>
    <div class="kort profilkort">
      <div class="rad"><div><strong>Köpartyp</strong>
        <div class="dampad">Styr vikten på riskerna och hur långt fram underhåll räknas – föreningens gränser är lika för alla.</div></div>
        ${profilvaljare(valdProfil())}</div>
    </div>
    <div class="dropp" id="dropp" tabindex="0" role="button" aria-label="Välj eller dra in en PDF">
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 15V4m0 0L8 8m4-4 4 4M5 15v4h14v-4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>
      <strong id="droppText">Välj årsredovisningen (PDF)</strong>
      <span>tryck för att välja fil · eller dra in en PDF eller en Booli-annons</span>
      <input type="file" id="fil" accept="application/pdf" hidden>
    </div>
    <div class="kort" style="margin-top:1rem">
      <label class="dampad" for="pdfUrl">Länk till årsredovisningen (PDF)</label>
      <input type="url" id="pdfUrl" placeholder="https://documents.bcdn.se/…/arsredovisning.pdf" value="${v("pdf")}">
      <h2 style="margin-top:1.25rem">Annonsen <span class="dampad" style="font-weight:400">– valfritt men ger lägenhetens nyckeltal</span></h2>
      <div class="falt">
        <div><label for="annons">Booli-länk</label><input type="url" id="annons" value="${v("annons")}" placeholder="https://www.booli.se/bostad/…"></div>
        <div><label for="adress">Adress</label><input type="text" id="adress" value="${v("adress")}"></div>
        <div><label for="pris">Pris (kr)</label><input type="text" id="pris" inputmode="numeric" value="${v("pris")}"></div>
        <div><label for="avgift">Avgift (kr/mån)</label><input type="text" id="avgift" inputmode="numeric" value="${v("avgift")}"></div>
        <div><label for="rum">Rum</label><input type="text" id="rum" inputmode="decimal" value="${v("rum")}"></div>
        <div><label for="kvm">Boarea (kvm)</label><input type="text" id="kvm" inputmode="decimal" value="${v("kvm")}"></div>
      </div>
      <div class="knapprad"><button class="knapp primar" id="starta">Starta analys</button></div>
      <div id="status"></div>
    </div>`;

  let valdFil = null;
  const dropp = document.getElementById("dropp"), fil = document.getElementById("fil");
  const droppText = document.getElementById("droppText");
  const valjFil = (f) => {
    if (!f) return;
    if (f.type !== "application/pdf" && !/\.pdf$/i.test(f.name)) { visaFel("Det där är ingen PDF."); return; }
    valdFil = f; droppText.textContent = `Vald fil: ${f.name}`; document.getElementById("pdfUrl").value = "";
  };
  dropp.addEventListener("click", () => fil.click());
  dropp.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fil.click(); } });
  fil.addEventListener("change", () => valjFil(fil.files[0]));
  ["dragenter", "dragover"].forEach((h) => dropp.addEventListener(h, (e) => { e.preventDefault(); dropp.classList.add("over"); }));
  ["dragleave", "drop"].forEach((h) => dropp.addEventListener(h, () => dropp.classList.remove("over")));
  dropp.addEventListener("drop", (e) => {
    e.preventDefault();
    if (e.dataTransfer.files.length) { valjFil(e.dataTransfer.files[0]); return; }
    const lank = (e.dataTransfer.getData("text/uri-list") || e.dataTransfer.getData("text/plain") || "").trim().split("\n")[0];
    if (/^https:\/\/www\.booli\.se\//.test(lank)) {
      franAnnons(lank);
    } else if (/^https:\/\//.test(lank)) {
      document.getElementById("pdfUrl").value = lank; valdFil = null; droppText.textContent = "Länk ifylld";
    }
  });

  document.getElementById("starta").addEventListener("click", () => starta(valdFil));
  // Köpartyp: spara valet så det används vid analysen och nästa gång
  vy.querySelector(".profilkort .profilval")?.addEventListener("click", (e) => {
    const knapp = e.target.closest("[data-profil]");
    if (!knapp) return;
    sparaProfil(knapp.dataset.profil).catch((err) => visaFel(err.message));
    vy.querySelectorAll(".profilkort .profilknapp").forEach((b) => {
      const vald = b === knapp;
      b.classList.toggle("vald", vald);
      b.setAttribute("aria-pressed", vald);
    });
  });
  // Klistra in en annonslänk var som helst på sidan (utom i ett textfält)
  document.onpaste = (e) => {
    if (!location.hash.startsWith("#/ny") || /^(INPUT|TEXTAREA)$/.test(e.target.tagName)) return;
    const text = (e.clipboardData.getData("text") || "").trim();
    if (/^https:\/\/www\.booli\.se\//.test(text)) { e.preventDefault(); franAnnons(text); }
  };
  if (param.get("pdf")) document.getElementById("starta").focus();
}

function visaInfo(text) {
  document.getElementById("status").innerHTML = `<div class="kort kostnad" style="margin-top:1rem">${esc(text)}</div>`;
}

function fyllAnnons(a) {
  ["annons", "adress", "pris", "avgift", "rum", "kvm"].forEach((n) => {
    if (a[n] != null) document.getElementById(n).value = a[n];
  });
}

// Ett drag: läs annonsen, hämta årsredovisningen och kör analysen
async function franAnnons(url) {
  const knapp = document.getElementById("starta");
  const steg = ["Läser annonsen och hittar årsredovisningen", "Läser årsredovisningen", "Räknar nyckeltal och utslag"];
  knapp.disabled = true;
  document.getElementById("droppText").textContent = "Annonsen inläst";
  try {
    visaSteg(steg, 0);
    const harTillagg = await tillaggFinns();
    let svar;
    if (harTillagg) {
      // Tillägget hämtar sidorna i din inloggade Chrome – servern tolkar dem
      const sidor = await tillagg("hamta", url);
      svar = await api("/api/fran-html", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(sidor),
      });
    } else {
      svar = await api("/api/fran-annons", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ annons_url: url }),
      });
    }
    fyllAnnons(svar.annons);
    if (svar.pdf_url) document.getElementById("pdfUrl").value = svar.pdf_url;
    if (!svar.forberedd) {
      knapp.disabled = false;
      if (harTillagg) {
        visaInfo(svar.meddelande || "Hittade inte årsredovisningen. Dra in PDF:en.");
      } else {
        visaInfo("Annonsen är inläst. För att hämta årsredovisningen automatiskt behövs tillägget Bostadsanalys i Chrome – det installeras en gång.");
        document.getElementById("status").insertAdjacentHTML("beforeend",
          '<div class="knapprad"><a class="knapp primar" href="#/tillagg">Installera tillägget</a><span class="dampad" style="align-self:center">eller dra in PDF:en</span></div>');
      }
      return;
    }
    await korAnalys(svar.forberedd, lasAnnonsfalt(), steg);
  } catch (err) {
    knapp.disabled = false;
    visaFel(err.message);
  }
}

// --- Chrome-tillägget ------------------------------------------------------------
// Tillägget (mappen tillagg/) hämtar Booli-sidor med din inloggning. Appen pratar med det via
// window.postMessage; tilläggets brygga sätter data-bostadsanalys-tillagg på <html>.
let tillaggRaknare = 0;
function tillagg(typ, url, timeoutMs = 45000) {
  return new Promise((svara, avvisa) => {
    const id = `t${++tillaggRaknare}`;
    const timer = setTimeout(() => { window.removeEventListener("message", lyssna); avvisa(new Error("Tillägget svarade inte.")); }, timeoutMs);
    function lyssna(e) {
      if (e.source !== window || !e.data || e.data.bostadsanalysSvar !== id) return;
      clearTimeout(timer); window.removeEventListener("message", lyssna);
      e.data.ok ? svara(e.data.data ?? e.data) : avvisa(new Error(e.data.fel || "Tillägget kunde inte hämta sidan."));
    }
    window.addEventListener("message", lyssna);
    window.postMessage({ bostadsanalys: typ, id, url }, location.origin);
  });
}
async function tillaggFinns() {
  if (document.documentElement.dataset.bostadsanalysTillagg !== "1") return false;
  try { await tillagg("ping", null, 1500); return true; } catch { return false; }
}

async function visaTillagg() {
  satNav("");
  const finns = await tillaggFinns();
  vy.innerHTML = `
    <h1>Tillägget Bostadsanalys</h1>
    <p class="dampad">Booli visar årsredovisningen bara för inloggade. Tillägget låter appen hämta den i din Chrome, där du redan är inloggad – sedan räcker det att dra in annonsen.</p>
    <div class="kort ${finns ? "grön" : ""}" style="${finns ? "border-color:var(--gron-kant);background:var(--gron-bg)" : ""}">
      ${finns ? "<strong>Tillägget är installerat och fungerar.</strong> Gå till Ny analys och dra in en annons."
              : "<strong>Tillägget är inte installerat än.</strong> Det tar en minut och görs en gång."}
    </div>
    ${finns ? "" : `<div class="kort" style="margin-top:1rem"><ol style="padding-left:1.2rem;margin:0;line-height:2">
      <li>Öppna en ny flik i Chrome och skriv <b>chrome://extensions</b> i adressfältet.</li>
      <li>Slå på <b>Utvecklarläge</b> (Developer mode) uppe till höger.</li>
      <li>Klicka på <b>Läs in okomprimerat</b> (Load unpacked).</li>
      <li>Välj mappen <b>Projects → bostadsanalys → tillagg</b> och klicka Välj.</li>
      <li>Kom tillbaka hit och <b>ladda om sidan</b> (Cmd + R).</li>
    </ol>
    <p class="dampad" style="margin-bottom:0">Tillägget får bara läsa sidor på booli.se och bara svara den här appen. Se till att du är inloggad på Booli i Chrome. Har du en äldre version installerad: klicka på pilen (Uppdatera) på tilläggets kort.</p></div>`}
    <div class="knapprad"><a class="knapp primar" href="#/ny">Till Ny analys</a></div>`;
}

function lasAnnonsfalt() {
  const annons = {};
  ["annons", "adress", "pris", "avgift", "rum", "kvm"].forEach((n) => { annons[n] = document.getElementById(n).value.trim() || null; });
  return Object.values(annons).some(Boolean) ? annons : null;
}

// Efter att PDF:en finns lokalt: bekräfta kostnaden om den inte är läst förut, analysera, visa
async function korAnalys(forberedd, annons, steg) {
  const knapp = document.getElementById("starta");
  let bekrafta = false;
  if (!forberedd.redan_extraherad) {
    // Regeln: aldrig ett betalt API-anrop utan att användaren bekräftat
    bekrafta = await fragaKostnad();
    if (!bekrafta) { knapp.disabled = false; visaFel("Avbrutet – ingen extraktion gjord."); return; }
  }
  visaSteg(steg, forberedd.redan_extraherad ? 2 : 1);
  let klar = await api("/api/analysera", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dokument_id: forberedd.dokument_id, bekrafta_kostnad: bekrafta, annons, profil: valdProfil() }),
  });
  // Läsningen tar ofta över en minut och körs som ett jobb på servern – fråga tills det är klart
  const jobbId = klar.jobb;
  while (klar.status === "pagar") {
    await new Promise((r) => setTimeout(r, 4000));
    klar = await api(`/api/jobb/${encodeURIComponent(jobbId)}`);
    if (klar.status === "fel") throw new Error(klar.fel || "Analysen misslyckades.");
  }
  location.hash = `#/objekt/${encodeURIComponent(klar.id)}`;
}

function visaFel(text) {
  document.getElementById("status").innerHTML = `<div class="fel">${esc(text)}</div>`;
}

function visaSteg(steg, aktivt) {
  document.getElementById("status").innerHTML = `<ul class="steg">${steg.map((s, i) =>
    `<li class="${i < aktivt ? "klar" : i === aktivt ? "pagar" : ""}">${i < aktivt ? "✓ " : ""}${esc(s)}</li>`).join("")}</ul>`;
}

async function starta(valdFil) {
  const knapp = document.getElementById("starta");
  const pdfUrl = document.getElementById("pdfUrl").value.trim();
  const annons = lasAnnonsfalt();
  if (!valdFil && !pdfUrl) {
    if (annons && annons.annons) { franAnnons(annons.annons); return; }
    visaFel("Dra in annonsen, en PDF eller ange länken till årsredovisningen först.");
    return;
  }
  if (annons && !annons.annons) { visaFel("Ange Booli-länken till annonsen när du fyller i annonsuppgifter."); return; }

  const steg = ["Hämtar årsredovisningen", "Läser årsredovisningen", "Räknar nyckeltal och utslag"];
  knapp.disabled = true;
  try {
    visaSteg(steg, 0);
    const forberedd = valdFil
      ? await api("/api/ladda-upp", { method: "POST", headers: { "Content-Type": "application/pdf" }, body: valdFil })
      : await api("/api/forbered", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pdf_url: pdfUrl }) });
    await korAnalys(forberedd, annons, steg);
  } catch (err) {
    knapp.disabled = false;
    visaFel(err.message);
  }
}

function fragaKostnad() {
  return new Promise((svara) => {
    document.getElementById("status").innerHTML = `<div class="kort kostnad" style="margin-top:1rem">
      <strong>Den här årsredovisningen är inte läst förut.</strong><br>
      Claude läser den – det kostar ca 1–2 kr och tar ungefär en minut.${PROFILER && PROFILER.kvar != null ? ` Du har ${esc(PROFILER.kvar)} sådana kvar den här månaden.` : ""}
      <div class="knapprad"><button class="knapp primar" id="ja">Kör analysen</button><button class="knapp" id="nej">Avbryt</button></div></div>`;
    document.getElementById("ja").addEventListener("click", () => svara(true));
    document.getElementById("nej").addEventListener("click", () => svara(false));
  });
}

// --- Navigering --------------------------------------------------------------

async function route() {
  const [sokvag, fraga = ""] = location.hash.replace(/^#/, "").split("?");
  const param = new URLSearchParams(fraga);
  try {
    if (sokvag.startsWith("/objekt/")) await visaObjekt(decodeURIComponent(sokvag.slice(8)));
    else if (sokvag === "/ny") await visaNy(param);
    else if (sokvag === "/tillagg") await visaTillagg();
    else await visaOversikt();
  } catch (err) {
    if (err instanceof EjInloggad) { visaLogin(); return; }
    vy.innerHTML = `<div class="fel">${esc(err.message)}</div><p><a href="#/">Till översikten</a></p>`;
  }
  window.scrollTo(0, 0);
}

async function visaKonto() {
  const jag = await api("/api/jag");
  if (PROFILER) PROFILER.kvar = jag.extraktioner_kvar;
  document.getElementById("konto").innerHTML = `<span class="dampad" title="${esc(jag.email)}">${esc(jag.email)}</span>
    <button class="knapp" id="loggaUt">Logga ut</button>`;
  document.getElementById("loggaUt").addEventListener("click", loggaUt);
}

async function starta_app() {
  const fel = taEmotInloggning();
  if (!lasSession()) { visaLogin(fel); return; }
  window.addEventListener("hashchange", route);
  try { await lasProfiler(); await visaKonto(); } catch (err) { if (err instanceof EjInloggad) { visaLogin(); return; } }
  route();
}
starta_app();
