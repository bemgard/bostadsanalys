"""
Nyckeltal för själva lägenheten (annonsen), inte bara föreningen.

Skuldjusterat pris = pris + lägenhetens andel av föreningens skuld, uppskattad som
boarea × föreningens skuld per kvm BOSTADSRÄTTSYTA (bedomning.skuld_per_kvm_bostadsratt).
Det är bostadsrättsinnehavarna som bär skulden – lokaler och hyresrätter gör det inte –
så ytan är bostadsrätternas, inte totalytan.

Kvarvarande förenkling: skulden fördelas i verkligheten efter andelstal, inte exakt
per kvm. Andelstalet står inte i årsredovisningen.
"""


def skuldjusterat_pris(pris, kvm, skuld_per_kvm):
    """Pris + kvm × skuld per kvm bostadsrättsyta, avrundat till hela kronor. None om något saknas."""
    if pris is None or not kvm or skuld_per_kvm is None:
        return None
    return round(pris + kvm * skuld_per_kvm)


def per_kvm(belopp, kvm):
    """Belopp per kvm, avrundat till hela kronor. None om något saknas."""
    if belopp is None or not kvm:
        return None
    return round(belopp / kvm)


def avgift_efter_hojningar(avgift, kommande_procent):
    """Annonsens månadsavgift efter föreningens beslutade, kommande höjningar (sammanlagt %).
    Antar att annonsens avgift är dagens och inte redan innehåller de kommande höjningarna.
    None om avgift eller höjningsuppgift saknas."""
    if avgift is None or kommande_procent is None:
        return None
    return round(avgift * (1 + kommande_procent / 100))


def vantad_avgift(avgift, kommande_procent, vantad_ranta_procent):
    """Annonsens månadsavgift efter den STÖRSTA av (a) föreningens beslutade kommande höjningar
    och (b) den väntade höjningen när lånen villkorsändras till marknadsräntan.
    Den största i stället för summan: beslutade höjningar görs ofta just för att täcka högre
    räntor, så summan skulle ofta räkna samma höjning två gånger. Är höjningarna till för olika
    saker (t.ex. en renovering) blir siffran för låg – därav mäklarfrågan om vad de ska täcka.
    None om avgiften saknas eller ingen av höjningarna går att räkna."""
    hojningar = [x for x in (kommande_procent, vantad_ranta_procent) if x is not None]
    if avgift is None or not hojningar:
        return None
    return round(avgift * (1 + max(hojningar) / 100))
