"""Dessine l'icone de Prisme.exe (meme logo que l'interface). Usage : python icone.py sortie.ico"""

import sys

from PIL import Image, ImageDraw

TAILLE = 1024
ETINCELLES = [
    [(12, 3), (13.9, 8.1), (19, 10), (13.9, 11.9), (12, 17), (10.1, 11.9), (5, 10), (10.1, 8.1)],
    [(19, 15), (19.8, 17.2), (22, 18), (19.8, 18.8), (19, 21), (18.2, 18.8), (16, 18), (18.2, 17.2)],
]


def dessiner():
    # Degrade diagonal violet, comme le logo de l'en-tete
    degrade = Image.new('RGB', (TAILLE, TAILLE))
    pixels = degrade.load()
    debut, fin = (109, 93, 252), (168, 85, 247)
    for y in range(TAILLE):
        for x in range(TAILLE):
            t = (x + y) / (2 * TAILLE - 2)
            pixels[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(debut, fin))

    masque = Image.new('L', (TAILLE, TAILLE), 0)
    ImageDraw.Draw(masque).rounded_rectangle((0, 0, TAILLE - 1, TAILLE - 1), radius=TAILLE * 0.23, fill=255)
    icone = Image.new('RGBA', (TAILLE, TAILLE), (0, 0, 0, 0))
    icone.paste(degrade, (0, 0), masque)

    # Le logo de 24 unites occupe 60 % de l'icone
    echelle, decalage = TAILLE * 0.6 / 24, TAILLE * 0.2
    dessin = ImageDraw.Draw(icone)
    for forme in ETINCELLES:
        dessin.polygon([(decalage + x * echelle, decalage + y * echelle) for x, y in forme], fill='white')
    return icone


if __name__ == '__main__':
    tailles = [(t, t) for t in (16, 20, 24, 32, 40, 48, 64, 128, 256)]
    dessiner().save(sys.argv[1], sizes=tailles)
