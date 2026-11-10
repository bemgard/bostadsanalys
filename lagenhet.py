"""
Nyckeltal för själva lägenheten (annonsen), inte bara föreningen.

Skuldjusterat pris = pris + lägenhetens andel av föreningens skuld, uppskattad som
boarea × föreningens belåning per kvm. Det gör annonser i föreningar med olika
belåning jämförbara: en billig lägenhet i en högt belånad förening kan i praktiken
vara dyrare än en dyrare lägenhet i en skuldfri.

Uppskattningen förutsätter att skulden fördelas per kvm. I verkligheten fördelas
den efter andelstal, och belåningen per kvm räknas på total yta (inkl. lokaler),
så siffran är ett jämförelsetal, inte en exakt skuldandel.
"""


def skuldjusterat_pris(pris, kvm, belaning_per_kvm):
    """Pris + kvm × belåning per kvm, avrundat till hela kronor. None om något saknas."""
    if pris is None or not kvm or belaning_per_kvm is None:
        return None
    return round(pris + kvm * belaning_per_kvm)


def per_kvm(belopp, kvm):
    """Belopp per kvm, avrundat till hela kronor. None om något saknas."""
    if belopp is None or not kvm:
        return None
    return round(belopp / kvm)
