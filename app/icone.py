"""Fait l'icone de Prisme.exe et son ecran de demarrage a partir du logo.

Usage : python icone.py logo.png sortie.ico [demarrage.png]
"""

import sys

from PIL import Image, ImageDraw, ImageFont

TAILLES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
POLICES = r'C:\Windows\Fonts'


def police(nom, taille):
    try:
        return ImageFont.truetype(f'{POLICES}\\{nom}', taille)
    except OSError:
        return ImageFont.load_default(taille)


def ecran_demarrage(logo, chemin):
    """Carte sombre aux coins arrondis : logo, nom et mention de chargement, comme l'interface."""
    largeur, hauteur, rayon = 440, 300, 28
    image = Image.new('RGBA', (largeur, hauteur), (0, 0, 0, 0))
    dessin = ImageDraw.Draw(image)
    dessin.rounded_rectangle((0, 0, largeur - 1, hauteur - 1), radius=rayon, fill=(22, 22, 28, 255),
                             outline=(58, 58, 72, 255), width=2)
    vignette = logo.resize((120, 120), Image.LANCZOS)
    image.alpha_composite(vignette, ((largeur - 120) // 2, 44))
    for texte, fonte, y, couleur in (('Prisme', police('segoeuib.ttf', 34), 182, (236, 236, 241)),
                                     ('Chargement…', police('segoeui.ttf', 15), 232, (161, 161, 176))):
        boite = dessin.textbbox((0, 0), texte, font=fonte)
        dessin.text(((largeur - (boite[2] - boite[0])) // 2, y), texte, font=fonte, fill=couleur)
    image.save(chemin)


if __name__ == '__main__':
    logo = Image.open(sys.argv[1]).convert('RGBA')
    logo.save(sys.argv[2], sizes=[(t, t) for t in TAILLES])
    if len(sys.argv) > 3:
        ecran_demarrage(logo, sys.argv[3])
