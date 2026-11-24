// Bostadsanalys – gränssnittet. Inga beroenden, inget byggsteg.
// Vyer (hash-adresser): #/ översikt · #/ny ny analys · #/objekt/<id> resultat
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

async function api(sokvag, alternativ = {}) {
  const svar = await fetch(sokvag, alternativ);
  let data = null;
  try { data = await svar.json(); } catch { /* inte JSON */ }
  if (!svar.ok) {
    const fel = new Error((data && data.detail) || `Fel ${svar.status}`);
    fel.status = svar.status; fel.data = data;
    throw fel;
  }
  return data;
}

function satNav(namn) {
  document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("aktiv", a.dataset.nav === namn));
}

// --- Köparprofil (köpartyp) --------------------------------------------------
// Profilerna hämtas en gång från servern. Valet på Ny analys sparas i webbläsaren.
let PROFILER = null;
async function lasProfiler() {
  if (!PROFILER) PROFILER = await api("/api/profiler");
  return PROFILER;
}
function hamtaLagrat(nyckel) { try { return localStorage.getItem(nyckel); } catch { return null; } }
function lagra(nyckel, varde) { try { localStorage.setItem(nyckel, varde); } catch { /* privat läge */ } }
function valdProfil() { return hamtaLagrat("profil") || (PROFILER && PROFILER.standard) || "par"; }
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
      <p class="dampad">Dra in en årsredovisning eller använd bokmärket på en Booli-annons.</p>
      <a class="knapp primar" href="#/ny">Ny analys</a></div>`;
    return;
  }
  vy.innerHTML = `
    <div class="rad"><div><h1>Översikt</h1><p class="dampad" style="margin:0">${objekt.length} objekt · bäst först</p></div>
      <div class="knapprad" style="margin:0">
        <a class="knapp" href="/api/export.xlsx" download>Exportera till Excel</a>
        <a class="knapp primar" href="#/ny">Ny analys</a>
      </div></div>
    <div class="rutnat" style="margin-top:1.25rem">${objekt.map(objektkort).join("")}</div>`;
}

function objektkort(o) {
  const farg = FARG[o.utslag] || "saknas";
  return `<a class="kort objektkort ${farg}" href="#/objekt/${encodeURIComponent(o.stam)}">
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

async function visaObjekt(stam) {
  satNav("");
  vy.innerHTML = '<p class="dampad">Hämtar analysen…</p>';
  await lasProfiler();
  const d = await api(`/api/objekt/${encodeURIComponent(stam)}`);
  const b = d.bedomning, a = d.annons || {}, t = d.lagenhet;
  const farg = FARG[b.utslag] || "saknas";
  const profil = b.koparprofil || (PROFILER && PROFILER.standard);
  const rader = b.nyckeltal.filter((r) => r.farg !== "info");
  const ordning = { "röd": 0, "gul": 1, "saknas": 2, "grön": 3 };
  const sortera = (lista) => lista.slice().sort((x, y) => (ordning[x.farg] ?? 9) - (ordning[y.farg] ?? 9));
  const tunga = sortera(rader.filter((r) => r.tung));
  const ovriga = sortera(rader.filter((r) => !r.tung));
  const bocka = JSON.parse(localStorage.getItem(`bocka:${stam}`) || "[]");

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
      ${d.pdf_finns ? `<a class="knapp" href="/api/pdf/${encodeURIComponent(stam)}" target="_blank" rel="noopener">Öppna årsredovisningen</a>` : ""}
      ${a.annons_url ? `<a class="knapp" href="${esc(a.annons_url)}" target="_blank" rel="noopener">Visa på Booli</a>` : ""}
      <button class="knapp" id="bedomOm" title="Gratis – inget API-anrop">Bedöm om med dagens datum</button>
      <button class="knapp" id="arkivera">Arkivera</button>
    </div>
    <p class="dampad">Bedömd ${esc(b.idag)} · marknadsränta ${esc(d.marknadsranta_procent)} %</p>`;

  vy.querySelectorAll(".fragor input").forEach((cb) => cb.addEventListener("change", () => {
    const valda = [...vy.querySelectorAll(".fragor input:checked")].map((x) => Number(x.dataset.i));
    localStorage.setItem(`bocka:${stam}`, JSON.stringify(valda));
  }));
  document.getElementById("bedomOm").addEventListener("click", async (e) => {
    e.target.disabled = true;
    try {
      await api(`/api/objekt/${encodeURIComponent(stam)}/bedom-om`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profil }),
      });
      visaObjekt(stam);
    } catch (err) { alert(err.message); e.target.disabled = false; }
  });
  // Byt köpartyp: kör om bedömningen (gratis) med den valda profilen
  vy.querySelector(".profilrad .profilval")?.addEventListener("click", async (e) => {
    const knapp = e.target.closest("[data-profil]");
    if (!knapp || knapp.classList.contains("vald")) return;
    vy.querySelectorAll(".profilrad .profilknapp").forEach((x) => (x.disabled = true));
    try {
      await api(`/api/objekt/${encodeURIComponent(stam)}/bedom-om`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profil: knapp.dataset.profil }),
      });
      visaObjekt(stam);
    } catch (err) { alert(err.message); vy.querySelectorAll(".profilrad .profilknapp").forEach((x) => (x.disabled = false)); }
  });
  document.getElementById("arkivera").addEventListener("click", async () => {
    if (!confirm("Flytta objektet till arkivet? Inget raderas – det ligger kvar i data/arkiv/.")) return;
    try { await api(`/api/objekt/${encodeURIComponent(stam)}/arkivera`, { method: "POST" }); location.hash = "#/"; }
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
    <p class="dampad">Dra in länken till Booli-annonsen (eller klistra in den med Cmd+V) – då hämtas pris, avgift, storlek och årsredovisning automatiskt. Det går också att dra in årsredovisningens PDF. <a href="#/tillagg">Tillägget i Chrome</a> behövs för att hämta årsredovisningen automatiskt.</p>
    <div class="kort profilkort">
      <div class="rad"><div><strong>Köpartyp</strong>
        <div class="dampad">Styr vikten på riskerna och hur långt fram underhåll räknas – föreningens gränser är lika för alla.</div></div>
        ${profilvaljare(valdProfil())}</div>
    </div>
    <div class="dropp" id="dropp" tabindex="0" role="button" aria-label="Välj eller dra in en PDF">
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 15V4m0 0L8 8m4-4 4 4M5 15v4h14v-4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>
      <strong id="droppText">Dra in annonsen från Booli här</strong>
      <span>eller klistra in länken · dra in en PDF · klicka för att välja fil</span>
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
    lagra("profil", knapp.dataset.profil);
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
    <p class="dampad" style="margin-bottom:0">Tillägget får bara läsa sidor på booli.se och bara svara den här appen på din dator. Se till att du är inloggad på Booli i Chrome.</p></div>`}
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
  const klar = await api("/api/analysera", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ stam: forberedd.stam, bekrafta_kostnad: bekrafta, annons, profil: valdProfil() }),
  });
  location.hash = `#/objekt/${encodeURIComponent(klar.stam)}`;
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
      ? await api(`/api/ladda-upp?filnamn=${encodeURIComponent(valdFil.name)}`, { method: "POST", headers: { "Content-Type": "application/pdf" }, body: valdFil })
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
      Claude läser den – det kostar ca 1–2 kr och tar ungefär en minut.
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
    vy.innerHTML = `<div class="fel">${esc(err.message)}</div><p><a href="#/">Till översikten</a></p>`;
  }
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", route);
route();
