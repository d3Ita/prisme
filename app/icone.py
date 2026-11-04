"""Fait l'icone de Prisme.exe a partir du logo. Usage : python icone.py logo.png sortie.ico"""

import sys

from PIL import Image

TAILLES = (16, 20, 24, 32, 40, 48, 64, 128, 256)

if __name__ == '__main__':
    logo = Image.open(sys.argv[1]).convert('RGBA')
    logo.save(sys.argv[2], sizes=[(t, t) for t in TAILLES])
