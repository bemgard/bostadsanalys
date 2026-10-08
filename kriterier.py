"""
Gränsvärden för bedömning av en bostadsrättsförening.

Filen innehåller BARA konstanter. Vill du ändra en gräns gör du det här –
ingen annan kod behöver röras. Färgerna är "grön", "gul" och "röd".
Belopp är i kronor, ytor i kvm.
"""

# --- Belåning per kvm ----------------------------------------------------------
# Skulder till kreditinstitut (lång- + kortfristiga) / total yta (kr/kvm).
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
# Hur stor del av skulden som får ny ränta (villkorsändras) inom horisonten,
# räknat från räkenskapsårets slut.
RANTEBINDNING_HORISONT_MANADER = 24
# gul om andelen av skulden som omförhandlas inom horisonten är större än detta
RANTEBINDNING_GUL_ANDEL_PROCENT = 30
# röd om andelen är större än detta OCH den viktade snitträntan på just de
# lånen är lägre än RANTEBINDNING_ROD_RANTA_MAX_PROCENT (dvs. stor risk för
# kraftigt höjd räntekostnad)
RANTEBINDNING_ROD_ANDEL_PROCENT = 40
RANTEBINDNING_ROD_RANTA_MAX_PROCENT = 2.5

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
# (t.ex. "Översyn tak" eller "Besiktning balkonger").
RENOVERINGAR_UNDANTAG = ["besiktning", "översyn", "uppföljning", "spolning", "inventering"]
# gul om någon stor åtgärd finns inom horisonten.
# röd om stor åtgärd finns OCH
#   sparande per kvm < RENOVERINGAR_ROD_SPARANDE_MIN
#   ELLER likvida medel per kvm totalyta < RENOVERINGAR_ROD_LIKVIDA_PER_KVM_MIN
RENOVERINGAR_ROD_SPARANDE_MIN = 150
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
TOMTRATT_FARG = "röd"

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

# --- Saknade värden --------------------------------------------------------------
# Om ett nyckeltal inte kan räknas fram (indata saknas i årsredovisningen)
# räknas det som denna färg i utslaget.
SAKNAS_RAKNAS_SOM = "gul"

# --- Utslag ----------------------------------------------------------------------
# SORTERA BORT: minst UTSLAG_SORTERA_BORT_MIN_RODA röda
# AVVAKTA:      minst UTSLAG_AVVAKTA_MIN_RODA röd ELLER minst UTSLAG_AVVAKTA_MIN_GULA gula
# GÅ VIDARE:    annars
UTSLAG_SORTERA_BORT_MIN_RODA = 2
UTSLAG_AVVAKTA_MIN_RODA = 1
UTSLAG_AVVAKTA_MIN_GULA = 3
