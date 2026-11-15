"""
Gränsvärden för bedömning av en bostadsrättsförening.

Filen innehåller BARA konstanter. Vill du ändra en gräns gör du det här –
ingen annan kod behöver röras. Färgerna är "grön", "gul" och "röd".
Belopp är i kronor, ytor i kvm.
"""

# --- Belåning per kvm ----------------------------------------------------------
# Skulder till kreditinstitut (lång- + kortfristiga) / bostadsrättsyta (kr/kvm).
# Bostadsrättsyta, inte totalyta: det är bostadsrättsinnehavarna som bär skulden.
# grön ≤ 5 000, gul ≤ 9 000, röd > 9 000
BELANING_PER_KVM_GRON_MAX = 5000
BELANING_PER_KVM_GUL_MAX = 9000

# --- Räntekänslighet -------------------------------------------------------------
# Skulder × 1 % / årsavgifter bostäder, i procent. Visar hur många procent
# avgiften behöver höjas om räntan stiger 1 procentenhet.
# grön ≤ 5, gul ≤ 10, röd > 10
RANTEKANSLIGHET_PROCENT_GRON_MAX = 5
RANTEKANSLIGHET_PROCENT_GUL_MAX = 10

# --- Sparande per kvm ------------------------------------------------------------
# Föreningens egen redovisade siffra för sparande per kvm totalyta (kr/kvm).
# grön ≥ 250, gul ≥ 150, röd < 150
SPARANDE_PER_KVM_GRON_MIN = 250
SPARANDE_PER_KVM_GUL_MIN = 150

# --- Avgift per kvm --------------------------------------------------------------
# Årsavgifter bostäder / bostadsyta (kr/kvm per år).
# grön mellan 450 och 850 (inklusive gränserna), annars gul. Aldrig röd.
AVGIFT_PER_KVM_GRON_MIN = 450
AVGIFT_PER_KVM_GRON_MAX = 850

# --- Avgiftshöjningar -----------------------------------------------------------
# Genomförda och beslutade höjningar av årsavgiften, sorterade efter datum (inte efter
# vilken lista årsredovisningen/extraktionen lagt dem i).
#   kommande = träder i kraft efter dagens datum (--idag) – ingår troligen inte i
#              annonsens avgift och slår direkt mot din månadskostnad
#   senaste  = trätt i kraft under de senaste AVGIFTSHOJNING_HISTORIK_MANADER månaderna
# röd om de kommande höjningarna tillsammans är minst AVGIFTSHOJNING_ROD_KOMMANDE_PROCENT
# gul om någon kommande höjning finns (även med okänt datum eller okänd storlek),
#     eller om de senaste höjningarna tillsammans är minst AVGIFTSHOJNING_GUL_SENASTE_PROCENT
#     (tecken på ekonomisk press – fråga varför och om fler väntar)
# grön annars. Flera höjningar räknas ihop med ränta-på-ränta (10 % + 10 % = 21 %).
AVGIFTSHOJNING_ROD_KOMMANDE_PROCENT = 10
AVGIFTSHOJNING_GUL_SENASTE_PROCENT = 20
AVGIFTSHOJNING_HISTORIK_MANADER = 36

# --- Energikostnad per kvm -------------------------------------------------------
# Föreningens redovisade energikostnad (el + värme + vatten) per kvm totalyta.
# gul om över detta, annars grön. Aldrig röd.
ENERGIKOSTNAD_PER_KVM_GUL_OVER = 250

# --- Föreningens storlek ---------------------------------------------------------
# gul om föreningen har färre bostadsrätter än detta (få som delar på kostnader
# och styrelsearbete), annars grön. Aldrig röd.
LITEN_FORENING_GUL_UNDER = 20

# --- Byggdelar -------------------------------------------------------------------
# Ålder på viktiga byggdelar, räknad från senaste utförda åtgärd i föreningens
# underhållshistorik till dagens datum (--idag).
#
# Per byggdel:
#   namn       – visas i tabellen
#   gul_over   – gul om åldern i år är större än detta
#   rod_over   – röd om åldern är större än detta OCH ingen sådan åtgärd är planerad
#                inom RENOVERINGAR_HORISONT_AR (None = aldrig röd)
#   nyckelord  – matchas i början eller slutet av ett ord, skiftlägesokänsligt
#                ("rörstambyte" träffas av "stambyte", "yttertak" av "tak")
#   hela_ord   – matchas bara som helt ord (för korta ord som "el", så att
#                "panel" eller "kabel" inte räknas)
#   ignorera   – ord som tas bort ur texten innan matchningen för just den byggdelen
#                (så att "Elstambyte" aldrig räknas som stambyte, bara som el)
#   undantag   – innehåller texten något av dessa räknas den inte som byggdelen
#                (t.ex. "takterrass" är inte taket)
# Byggdel som inte finns i historiken alls räknas som "okänd" (gul).
BYGGDELAR = {
    "stambyte": {
        "namn": "Stambyte (vatten/avlopp)",
        "gul_over": 40,
        "rod_over": 50,
        "nyckelord": ["stambyte", "stamrenovering", "relining", "stammar"],
        "hela_ord": [],
        "ignorera": ["elstambyte", "elstamsbyte"],
        "undantag": [],
    },
    "tak": {
        "namn": "Tak",
        "gul_over": 40,
        "rod_over": None,
        "nyckelord": ["tak", "takbyte", "takomläggning"],
        "hela_ord": [],
        "ignorera": [],
        "undantag": ["takterrass", "takterass"],
    },
    "fasad": {
        "namn": "Fasad",
        "gul_over": 40,
        "rod_over": None,
        "nyckelord": ["fasad", "omputsning"],
        "hela_ord": [],
        "ignorera": [],
        "undantag": [],
    },
    "el": {
        "namn": "El",
        "gul_over": 50,
        "rod_over": None,
        "nyckelord": ["elstambyte", "elstamsbyte", "elstam", "elcentral", "el-central",
                      "elinstallation", "elsystem"],
        "hela_ord": ["el"],  # t.ex. "Stambyte av VVS och EL"
        "ignorera": [],
        "undantag": [],
    },
}
# Åtgärder vars text innehåller något av dessa ord räknas inte som byte av
# någon byggdel (t.ex. "Stamspolning", "Översyn av stammar", "Målning tak",
# "Korrigeringar i stambytet").
BYGGDELAR_EJ_BYTE = ["spolning", "översyn", "besiktning", "målning", "korrigering"]

# --- Räntebindning ---------------------------------------------------------------
# Hur stor del av skulden som får ny ränta (villkorsändras) från räkenskapsårets
# slut fram till horisonten, räknad från dagens datum (--idag).
RANTEBINDNING_HORISONT_MANADER = 24

# Marknadsränta: den ränta föreningens lån antas få när de villkorsändras.
# UPPDATERA när räntorna ändras. Satt 2026-11-15: snitträntan för föreningslån var
# 2,82 % i mars 2026 (SCB via Dagens PS), Riksbanken höjde styrräntan till 2,00 %
# den 4 nov 2026 och väntas höja mer 2027 – 3,5 % är en försiktig bedömning för
# lån som binds om inom horisonten.
MARKNADSRANTA_FORENINGSLAN_PROCENT = 3.5

# Väntad avgiftshöjning = Σ belopp × (marknadsränta − lånets ränta) / årsavgifterna,
# för lån som villkorsändras från idag till horisonten (lån med högre ränta än
# marknadsräntan räknas som 0, inte som sänkning).
# röd om väntad avgiftshöjning ≥ RANTEBINDNING_ROD_AVGIFTSHOJNING_PROCENT
# gul om den är ≥ RANTEBINDNING_GUL_AVGIFTSHOJNING_PROCENT, eller om lån som redan
#     villkorsändrats efter räkenskapsåret gav samma effekt (fråga om avgiften redan höjts),
#     eller om räntan/årsavgifterna saknas så att det inte går att räkna
RANTEBINDNING_ROD_AVGIFTSHOJNING_PROCENT = 10
RANTEBINDNING_GUL_AVGIFTSHOJNING_PROCENT = 3

# --- Renoveringar ----------------------------------------------------------------
# Planerat underhåll inom horisonten (år från räkenskapsårets slut).
RENOVERINGAR_HORISONT_AR = 5
# Ord som gör en planerad åtgärd till en "stor åtgärd" (matchas mot åtgärdstexten).
RENOVERINGAR_STORA_ATGARDER = [
    "stambyte",
    "tak",
    "fasad",
    "fönster",
    "dränering",
    "hiss",
    "balkong",
]
# Nyckelordet matchas bara i början eller slutet av ett ord (skiftlägesokänsligt),
# så "takkupor" och "yttertak" räknas men inte "kontakt".
# En åtgärd vars text innehåller något av dessa ord räknas INTE som stor åtgärd
# (t.ex. "Översyn tak", "Besiktning balkonger" eller "Målning av slitna fönster").
RENOVERINGAR_UNDANTAG = ["besiktning", "översyn", "uppföljning", "spolning", "inventering", "målning"]
# gul om någon stor åtgärd finns inom horisonten och kassan räcker.
# röd om stor åtgärd finns OCH likvida medel per kvm totalyta < RENOVERINGAR_ROD_LIKVIDA_PER_KVM_MIN.
# (Sparandet påverkar inte denna rad – det har en egen rad.)
# Saknas en redovisad underhållsplan blir raden minst gul.
RENOVERINGAR_ROD_LIKVIDA_PER_KVM_MIN = 300

# --- Rapportens ålder ------------------------------------------------------------
# gul om räkenskapsårets slut ligger mer än så här många månader bakåt i tiden
RAPPORTENS_ALDER_GUL_MANADER = 15

# --- Byggår ---------------------------------------------------------------------
# röd om huset är byggt senare än detta år (utanför sökfiltret), annars grön.
# Vid flera hus används det senaste byggåret.
BYGGAR_MAX = 1920

# --- Äkta förening ---------------------------------------------------------------
# Färg om föreningen är oäkta (skattekonsekvenser för medlemmarna); äkta = grön
OAKTA_FORENING_FARG = "röd"

# --- Grundläggning ---------------------------------------------------------------
# Färg per status när årsredovisningen nämner problem med byggnadens grund.
# Inga grundproblem nämnda = grön.
GRUNDLAGGNING_FARG = {
    "planerad": "röd",
    "pågående": "röd",
    "okänd": "gul",
    "åtgärdad": "grön",
}

# --- Tomträtt --------------------------------------------------------------------
# Färg om marken innehas med tomträtt (annars ingen flagga)
TOMTRATT_FARG = "gul"

# --- Revisorn --------------------------------------------------------------------
# Färg om revisorn gör en anmärkning / avvikande uttalande
REVISORN_ANMARKNING_FARG = "röd"
# Färg om revisionsberättelsen innehåller en upplysning av särskild betydelse
REVISORN_UPPLYSNING_FARG = "gul"

# --- Kontrollräkning -------------------------------------------------------------
# När vår egen uträkning av ett nyckeltal avviker mer än så här många procent
# från föreningens redovisade siffra flaggas det som en avvikelse.
# Påverkar INTE färgen – är bara en varning om att något bör kontrolleras.
KONTROLLRAKNING_TOLERANS_PROCENT = 10

# --- Rimlighetskontroller -------------------------------------------------------
# Fångar troliga felavläsningar i extraktionen (rimlighet.py). Påverkar INTE färgen –
# ger en varning om att siffran bör kontrolleras i PDF:en.
# Hur mycket två siffror som borde stämma (t.ex. ytor, lånenot mot balansräkning)
# får skilja sig, i procent.
RIMLIGHET_TOLERANS_PROCENT = 5
# Högsta rimliga räntesats på ett föreningslån (%)
RIMLIGHET_MAX_RANTA_PROCENT = 15
# Rimlig längd på ett räkenskapsår i månader (min, max) – första året kan vara förlängt
RIMLIGHET_RAKENSKAPSAR_MANADER = (6, 18)

# --- Saknade värden --------------------------------------------------------------
# Om ett nyckeltal inte kan räknas fram (indata saknas i årsredovisningen)
# räknas det som denna färg i utslaget.
SAKNAS_RAKNAS_SOM = "gul"

# --- Utslag ----------------------------------------------------------------------
# Rader som visas och färgas men INTE räknas i utslaget (t.ex. sökfilter som byggår).
UTSLAG_RAKNAS_EJ = ["Byggår"]

# Utslaget räknas i utslag.py:
# 1. Stoppfaktorer – en räcker för SORTERA BORT, oavsett poäng.
STOPP_OAKTA_FORENING = True          # oäkta förening
STOPP_REVISORNS_ANMARKNING = True    # anmärkning (inte upplysning) i revisionsberättelsen
STOPP_GRUNDPROBLEM = True            # planerade eller pågående problem med grunden
STOPP_VANTAD_AVGIFTSHOJNING_PROCENT = 20  # väntad avgiftshöjning när lånen villkorsändras (None = av)

# 2. Poäng 0–100: viktat snitt där grön = 1, gul = ½, röd = 0 (saknas = SAKNAS_RAKNAS_SOM).
# Tunga kriterier (vikt 3) avgör mest; rader som inte står här får standardvikten.
UTSLAG_VIKTER = {
    "Belåning per kvm": 3,
    "Sparande per kvm": 3,
    "Räntebindning": 3,
    "Avgiftshöjningar": 3,
    "Renoveringar": 3,
    "Byggdelar": 3,          # stambyte, tak, fasad, el
    "Grundläggning": 3,
    "Räntekänslighet": 1,
    "Avgift per kvm": 1,
    "Energikostnad per kvm": 1,
    "Föreningens storlek": 1,
    "Tomträtt": 1,
    "Rapportens ålder": 1,
    "Äkta förening": 1,      # oäkta är redan en stoppfaktor
    "Revisorn": 1,           # anmärkning är redan en stoppfaktor
}
UTSLAG_VIKT_STANDARD = 1
UTSLAG_TUNG_VIKT = 3  # vikt från vilken ett kriterium räknas som tungt (i motivering och datakvalitet)

# 3. Utslag (om ingen stoppfaktor slagit till), i den här ordningen:
#    - minst UTSLAG_SORTERA_BORT_TUNGA_RODA röda tunga kriterier → SORTERA BORT
#    - poäng under UTSLAG_AVVAKTA_MIN_POANG → SORTERA BORT
#    - något rött tungt kriterium → högst AVVAKTA, oavsett poäng
#    - poäng minst UTSLAG_GA_VIDARE_MIN_POANG → GÅ VIDARE, annars AVVAKTA
# Kalibrerat 2026-11-15 mot 16 föreningar: poängen ensam spred för lite – det som skiljer
# föreningar åt är röda tunga kriterier (t.ex. belåning och sparande samtidigt).
UTSLAG_SORTERA_BORT_TUNGA_RODA = 2
UTSLAG_GA_VIDARE_MIN_POANG = 75
UTSLAG_AVVAKTA_MIN_POANG = 50

# 4. Datakvalitet: "Osäker" om minst så här många nyckeltal saknas, något tungt
#    nyckeltal saknas, eller minst så här många rimlighetsvarningar finns.
DATAKVALITET_OSAKER_SAKNADE = 3
DATAKVALITET_OSAKER_VARNINGAR = 2
