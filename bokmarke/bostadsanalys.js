// Bokmärke för bostadsanalys.
//
// På en annons på Booli: läser adress, pris, avgift, rum och boarea, hämtar
// föreningssidan i bakgrunden, hittar årsredovisningens PDF och visar ett färdigt
// terminalkommando för analysera.py som du kopierar med Cmd+C – ett enda klick.
// Går föreningssidan inte att läsa i bakgrunden öppnas den i stället, och du
// klickar på bokmärket en gång till där (annonsuppgifterna följer med).
// På en föreningssida: samma kommando, men utan annonsuppgifter om du inte
// kom dit via bokmärket från annonsen.
//
// Allt som hamnar i kommandot kontrolleras strikt, eftersom det klistras in i
// en terminal. Byggs till ett bokmärke med: python bokmarke/bygg.py

(function () {
  "use strict";

  var PROJEKTKATALOG = "~/Projects/bostadsanalys";
  var LAGRINGSNYCKEL = "bostadsanalys_annons";
  var MAX_ALDER_MS = 30 * 60 * 1000; // annonsuppgifter äldre än 30 min används inte
  var ADRESS_MAX_TECKEN = 100;

  // Godkända format – allt annat avvisas
  var PDF_MONSTER = /^https:\/\/documents\.bcdn\.se\/[A-Za-z0-9\/_.\-]+\.pdf$/;
  var ANNONS_MONSTER = /^https:\/\/www\.booli\.se\/(bostad|annons)\/\d+$/;
  var FORENING_SOKVAG = /^\/bostadsrattsforening\/\d+$/;

  // --- Hjälpfunktioner -------------------------------------------------------

  // Vilken sorts sida är vi på? "annons", "forening" eller "annat".
  function sidtyp(url) {
    var u = new URL(url);
    if (u.hostname !== "www.booli.se") return "annat";
    var sokvag = u.pathname.replace(/\/$/, "");
    if (/^\/(bostad|annons)\/\d+$/.test(sokvag)) return "annons";
    if (FORENING_SOKVAG.test(sokvag)) return "forening";
    return "annat";
  }

  // Ta bort ?parametrar och #ankare från en adress.
  function utanParametrar(url) {
    return String(url).split(/[?#]/)[0];
  }

  // Alla JSON-LD-objekt på sidan (även listor och @graph), ogiltiga block hoppas över.
  function jsonLd(doc) {
    var objekt = [];
    doc.querySelectorAll('script[type="application/ld+json"]').forEach(function (s) {
      try {
        var data = JSON.parse(s.textContent);
        (Array.isArray(data) ? data : [data]).forEach(function (d) {
          objekt.push(d);
          if (d && Array.isArray(d["@graph"])) objekt.push.apply(objekt, d["@graph"]);
        });
      } catch (e) { /* trasigt block – hoppa över */ }
    });
    return objekt;
  }

  function avTyp(objekt, typ) {
    return objekt.filter(function (o) { return o && o["@type"] === typ; })[0] || null;
  }

  // Värdet efter en rubrik i synlig HTML, t.ex. "Avgift" → "4 648 kr/mån".
  // Rubriken ska vara ett element utan barn vars text är exakt etiketten.
  function rubrikvarde(doc, etikett) {
    var element = doc.querySelectorAll("span, dt, div, p, h3, h4");
    for (var i = 0; i < element.length; i++) {
      var e = element[i];
      if (e.children.length === 0 && e.textContent.trim() === etikett) {
        var nasta = e.nextElementSibling || (e.parentElement && e.parentElement.nextElementSibling);
        if (nasta) return nasta.textContent.trim();
      }
    }
    return null;
  }

  // Första talet i en text: "4 648 kr/mån" → "4648", "63,5 m²" → "63.5".
  // Returnerar text (inte number) så att vi styr exakt vad som skrivs i kommandot.
  function forstaTal(text) {
    if (text === null || text === undefined) return null;
    var m = String(text).replace(/[\s\u00a0]/g, "").match(/\d+(?:[.,]\d+)?/);
    return m ? m[0].replace(",", ".") : null;
  }

  // Positivt heltal som text, annars null.
  function heltal(text) {
    var t = forstaTal(text);
    return t && /^\d+$/.test(t) && Number(t) > 0 ? t : null;
  }

  // Positivt tal (punkt som decimaltecken) som text, annars null.
  function decimaltal(text) {
    var t = forstaTal(text);
    return t && /^\d+(\.\d+)?$/.test(t) && Number(t) > 0 ? t : null;
  }

  // Bara bokstäver (inkl. åäö), siffror, mellanslag, bindestreck, komma och punkt.
  function tvattaAdress(text) {
    if (!text) return null;
    var ren = String(text).normalize("NFC")
      .replace(/\s+/g, " ")
      .replace(/[^\p{L}0-9 ,.\-]/gu, "")
      .replace(/ +/g, " ")
      .trim()
      .slice(0, ADRESS_MAX_TECKEN)
      .trim();
    return ren || null;
  }

  // --- A) Annonssidan --------------------------------------------------------

  function lasAnnons(doc, url) {
    var ld = jsonLd(doc);
    var plats = avTyp(ld, "Place");
    var produkt = avTyp(ld, "Product");
    var stig = avTyp(ld, "BreadcrumbList");

    // Föreningslänk: i första hand JSON-LD:s länkstig, annars en vanlig länk på sidan
    var foreningSokvag = null;
    if (stig && Array.isArray(stig.itemListElement)) {
      stig.itemListElement.forEach(function (post) {
        var item = post && (typeof post.item === "string" ? post.item : post.item && post.item["@id"]);
        if (item && item.indexOf("/bostadsrattsforening/") !== -1) {
          foreningSokvag = new URL(item, "https://www.booli.se").pathname;
        }
      });
    }
    if (!foreningSokvag) {
      var lank = doc.querySelector('a[href^="/bostadsrattsforening/"], a[href^="https://www.booli.se/bostadsrattsforening/"]');
      if (lank) foreningSokvag = new URL(lank.getAttribute("href"), "https://www.booli.se").pathname;
    }
    if (foreningSokvag) foreningSokvag = foreningSokvag.replace(/\/$/, "");
    if (foreningSokvag && !FORENING_SOKVAG.test(foreningSokvag)) foreningSokvag = null;

    return {
      annons_url: utanParametrar(url).replace(/\/$/, ""),
      adress: tvattaAdress(plats && plats.address && plats.address.streetAddress),
      pris: heltal(produkt && produkt.offers && produkt.offers.price),
      avgift: heltal(rubrikvarde(doc, "Avgift")),
      rum: decimaltal(rubrikvarde(doc, "Rum")),
      kvm: decimaltal(rubrikvarde(doc, "Boarea")),
      foreningSokvag: foreningSokvag
    };
  }

  // --- B) Föreningssidan -----------------------------------------------------

  // PDF-länken vid rubriken "Årsredovisning", utan ?parametrar. null om ingen finns.
  function lasForeningPdf(doc) {
    var selektor = 'a[href^="https://documents.bcdn.se/"]';
    var rubriker = Array.prototype.filter.call(
      doc.querySelectorAll("h1, h2, h3, h4, h5, h6, span, p, div"),
      function (e) { return e.children.length === 0 && e.textContent.trim() === "Årsredovisning"; }
    );
    // Gå uppåt från rubriken till närmaste förälder som innehåller en dokumentlänk
    for (var i = 0; i < rubriker.length; i++) {
      var el = rubriker[i];
      for (var steg = 0; steg < 5 && el; steg++) {
        el = el.parentElement;
        var a = el && el.querySelector(selektor);
        if (a) return utanParametrar(a.getAttribute("href"));
      }
    }
    // Reserv: en dokumentlänk vars filnamn innehåller "rsredovisning"
    var reserv = Array.prototype.filter.call(doc.querySelectorAll(selektor), function (a) {
      return /rsredovisning/i.test(a.getAttribute("href"));
    })[0];
    return reserv ? utanParametrar(reserv.getAttribute("href")) : null;
  }

  // Bygg terminalkommandot. Annonsdelen tas bara med om annons-URL:en är giltig;
  // ogiltiga eller saknade värden utelämnas. Allt står inom enkla citattecken.
  function byggKommando(pdf, annons) {
    if (!PDF_MONSTER.test(pdf)) return null;
    var delar = [
      "cd " + PROJEKTKATALOG,
      "&&",
      "venv/bin/python analysera.py '" + pdf + "'"
    ];
    if (annons && ANNONS_MONSTER.test(annons.annons_url)) {
      delar.push("--annons '" + annons.annons_url + "'");
      var adress = tvattaAdress(annons.adress);
      if (adress) delar.push("--adress '" + adress + "'");
      var pris = heltal(annons.pris), avgift = heltal(annons.avgift);
      var rum = decimaltal(annons.rum), kvm = decimaltal(annons.kvm);
      if (pris) delar.push("--pris '" + pris + "'");
      if (avgift) delar.push("--avgift '" + avgift + "'");
      if (rum) delar.push("--rum '" + rum + "'");
      if (kvm) delar.push("--kvm '" + kvm + "'");
    }
    return delar.join(" ");
  }

  // Annonsuppgifter sparade från annonssidan – bara om de gäller just denna
  // förening och är färska. Töms alltid efter läsning.
  function hamtaSparadAnnons(sokvag) {
    var data = null;
    try {
      data = JSON.parse(sessionStorage.getItem(LAGRINGSNYCKEL));
      sessionStorage.removeItem(LAGRINGSNYCKEL);
    } catch (e) { return null; }
    if (!data || data.foreningSokvag !== sokvag || Date.now() - data.tid > MAX_ALDER_MS) return null;
    return data.annons;
  }

  // Hämta föreningssidan i bakgrunden (samma webbplats, med inloggningen) och leta
  // upp årsredovisningen. Ger PDF-länken, eller null om den inte går att hitta.
  function hamtaForeningPdf(sokvag) {
    return fetch("https://www.booli.se" + sokvag, { credentials: "include" })
      .then(function (svar) { return svar.ok ? svar.text() : null; })
      .then(function (html) {
        return html ? lasForeningPdf(new DOMParser().parseFromString(html, "text/html")) : null;
      });
  }

  // Annonsflödet: hämta PDF:en i bakgrunden och visa kommandot direkt. Går det inte
  // (sidan laddar dokumenten med JavaScript, nätverksfel, ej inloggad) används
  // reserven: öppna föreningssidan och låt användaren klicka en gång till.
  // Beroendena skickas in så att flödet kan testas utan webbläsare.
  function annonsFlode(annons, beroenden) {
    return Promise.resolve()
      .then(function () { return beroenden.hamtaPdf(annons.foreningSokvag); })
      .catch(function () { return null; })
      .then(function (pdf) {
        var kommando = pdf ? byggKommando(pdf, annons) : null;
        if (kommando) {
          beroenden.visa(kommando);
          return "klart";
        }
        beroenden.reserv(annons);
        return "reserv";
      });
  }

  // Annonsuppgifter som saknas i kommandot – för en tydlig varning i stället för tysta luckor.
  function saknadeAnnonsfalt(annons) {
    if (!annons) return ["alla annonsuppgifter"];
    var saknas = [];
    if (!heltal(annons.pris)) saknas.push("pris");
    if (!heltal(annons.avgift)) saknas.push("avgift");
    if (!decimaltal(annons.kvm)) saknas.push("boarea");
    return saknas;
  }

  function visaKommando(kommando, annons) {
    var saknas = saknadeAnnonsfalt(annons);
    var rubrik = "Kopiera kommandot (Cmd+C) och klistra in det i Terminalen:";
    if (saknas.length) {
      rubrik = "OBS: " + saknas.join(", ") + " saknas – skuldjusterat pris och väntad avgift kan inte räknas. " +
        (annons ? "" : "Börja från annonsen för att få med dem. ") + rubrik;
    }
    prompt(rubrik, kommando);
  }

  // --- Körning ---------------------------------------------------------------

  function kor(doc, loc) {
    var typ = sidtyp(loc.href);

    if (typ === "annons") {
      var annons = lasAnnons(doc, loc.origin + loc.pathname);
      if (!annons.foreningSokvag) {
        alert("Hittar ingen länk till bostadsrättsföreningen på den här annonsen.\n\n" +
              "Det kan vara en bostad utan förening (t.ex. villa eller hyresrätt). " +
              "Öppna föreningssidan själv och klicka på bokmärket där.");
        return;
      }
      annonsFlode(annons, {
        hamtaPdf: hamtaForeningPdf,
        visa: function (kommando) { visaKommando(kommando, annons); },
        reserv: function (a) {
          try {
            sessionStorage.setItem(LAGRINGSNYCKEL, JSON.stringify({
              annons: a, foreningSokvag: a.foreningSokvag, tid: Date.now()
            }));
          } catch (e) { /* lagring avstängd – kommandot byggs då utan annonsdel */ }
          alert("Annonsen är läst. Föreningssidan öppnas nu – klicka på bokmärket igen när den har laddat klart.");
          loc.href = loc.origin + a.foreningSokvag;
        }
      });
      return;
    }

    if (typ === "forening") {
      var pdf = lasForeningPdf(doc);
      if (!pdf) {
        alert("Logga in på Booli för att se dokumenten.");
        return;
      }
      var sparad = hamtaSparadAnnons(loc.pathname.replace(/\/$/, ""));
      var kommando = byggKommando(pdf, sparad);
      if (!kommando) {
        alert("Årsredovisningens länk har ett oväntat format och används inte av säkerhetsskäl:\n\n" + pdf);
        return;
      }
      visaKommando(kommando, sparad);
      return;
    }

    alert("Öppna en annons eller föreningssida på Booli.");
  }

  // Testläge: exponera funktionerna i stället för att köra (används bara vid test).
  if (typeof window !== "undefined" && typeof window.__BOSTADSANALYS_TEST__ === "function") {
    window.__BOSTADSANALYS_TEST__({
      sidtyp: sidtyp, lasAnnons: lasAnnons, lasForeningPdf: lasForeningPdf,
      byggKommando: byggKommando, tvattaAdress: tvattaAdress,
      annonsFlode: annonsFlode, saknadeAnnonsfalt: saknadeAnnonsfalt
    });
    return;
  }

  kor(document, location);
})();
