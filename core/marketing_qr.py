"""
QR codes destines a l'affichage en salle.

Deux supports : l'adresse du site public, et le lien de preinscription. Ils
finissent sur un mur, parfois en tres grand format, ce qui impose un rendu
vectoriel : une image agrandie au-dela de sa definition donne des modules aux
bords baveux, que les telephones peinent a decoder.

Le PDF est ecrit a la main. Un QR code n'est qu'une grille de carres noirs, et
le format PDF les exprime en quelques octets - une bibliotheque de mise en page
complete serait disproportionnee pour dessiner des rectangles.
"""

import qrcode

# Zone de silence prevue par la norme : quatre modules blancs tout autour.
# En dessous, un scanner peine a delimiter le code sur un mur charge.
BORDURE_MODULES = 4

# Cote de la page, en points PostScript (72 par pouce). 210 mm, la largeur
# d'un A4 : une taille de depart familiere a un imprimeur. Le format etant
# vectoriel, elle ne limite en rien l'agrandissement.
COTE_PAGE = 595.28


def matrice(contenu):
    """
    Grille du QR code : une liste de lignes de booleens.

    Correction d'erreur elevee, comme pour les cartes membres : une affiche se
    salit, se decolle et se prend des reflets ; 25 % de redondance lui laissent
    une chance.
    """
    qr = qrcode.QRCode(
        border=BORDURE_MODULES,
        error_correction=qrcode.constants.ERROR_CORRECT_Q,
    )
    qr.add_data(contenu or "-")
    qr.make(fit=True)
    return qr.get_matrix()


def _flux_de_dessin(grille, cote_page=COTE_PAGE):
    """
    Instructions de dessin PDF : un rectangle par module sombre.

    Tous les rectangles sont empiles puis remplis d'un seul coup. Le repere PDF
    part du bas a gauche, la grille du haut a gauche : la ligne est donc
    inversee.
    """
    total = len(grille)
    module = cote_page / total

    lignes = ["0 0 0 rg"]
    for rang, ligne in enumerate(grille):
        y = cote_page - (rang + 1) * module
        for colonne, sombre in enumerate(ligne):
            if sombre:
                x = colonne * module
                lignes.append(f"{x:.4f} {y:.4f} {module:.4f} {module:.4f} re")
    lignes.append("f")
    return "\n".join(lignes).encode("ascii")


def en_pdf(contenu, cote_page=COTE_PAGE):
    """
    Le QR code en PDF vectoriel, agrandissable sans perte.

    Structure minimale : catalogue, arbre des pages, page, flux de dessin. Les
    positions de chaque objet sont relevees a l'ecriture pour construire la
    table de references croisees, qu'un lecteur PDF exige exacte.
    """
    flux = _flux_de_dessin(matrice(contenu), cote_page)
    boite = f"[0 0 {cote_page:.2f} {cote_page:.2f}]"

    objets = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            "<< /Type /Page /Parent 2 0 R /MediaBox " + boite
            + " /Contents 4 0 R /Resources << >> >>"
        ).encode("ascii"),
        b"<< /Length " + str(len(flux)).encode("ascii") + b" >>\nstream\n"
        + flux + b"\nendstream",
    ]

    sortie = bytearray(b"%PDF-1.4\n")
    positions = []
    for numero, corps in enumerate(objets, start=1):
        positions.append(len(sortie))
        sortie += f"{numero} 0 obj\n".encode("ascii") + corps + b"\nendobj\n"

    debut_xref = len(sortie)
    sortie += f"xref\n0 {len(objets) + 1}\n".encode("ascii")
    sortie += b"0000000000 65535 f \n"
    for position in positions:
        sortie += f"{position:010d} 00000 n \n".encode("ascii")

    sortie += (
        f"trailer\n<< /Size {len(objets) + 1} /Root 1 0 R >>\n"
        f"startxref\n{debut_xref}\n%%EOF\n"
    ).encode("ascii")

    return bytes(sortie)


def en_png(contenu, taille=None):
    """Le QR code en image, pour un partage rapide ou un ecran."""
    from members.card_images import render_qr_png

    return render_qr_png(contenu, taille)
