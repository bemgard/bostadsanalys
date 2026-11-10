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
