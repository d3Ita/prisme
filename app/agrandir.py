"""Agrandissement d'une image terminee : Real-ESRGAN x4 par le mode upscale de sd-cli.

Ce module ne connait pas le serveur : il construit la commande, suit la progression (les morceaux
de l'image, n/k) et recopie la description de l'image d'origine dans l'image agrandie, pour que la galerie et
Reutiliser la retrouvent. Mesure sur une RTX 4070 SUPER : 1280 x 704 -> 5120 x 2816 en 12 s."""
import re
import struct
import zlib
from pathlib import Path

FACTEUR = 4
CLE = 'modele_agrandissement'
PAS = re.compile(r'(\d+)/(\d+)\s*-\s*[\d.,]+\s*(?:s/it|it/s)')
SIGNATURE_PNG = b'\x89PNG\r\n\x1a\n'
# Au-dela, l'image agrandie depasserait 16 384 px de cote, la limite de la plupart des navigateurs
COTE_MAX_SOURCE = 4096


def arguments(modele, source, sortie):
    return ['-M', 'upscale', '-i', str(source), '--upscale-model', str(modele), '-o', str(sortie)]


def taille_png(chemin):
    with open(chemin, 'rb') as f:
        if f.read(8) != SIGNATURE_PNG:
            return None
        n, genre = struct.unpack('>I4s', f.read(8))
        return struct.unpack('>II', f.read(8)) if genre == b'IHDR' else None


def morceaux_png(donnees):
    """(genre, contenu) de chaque morceau d'un PNG."""
    if not donnees.startswith(SIGNATURE_PNG):
        raise ValueError('Ce fichier n\'est pas une image PNG.')
    i, morceaux = 8, []
    while i + 8 <= len(donnees):
        n, genre = struct.unpack('>I4s', donnees[i:i + 8])
        morceaux.append((genre, donnees[i + 8:i + 8 + n]))
        i += 12 + n
    return morceaux


def morceau_png(genre, contenu):
    return struct.pack('>I', len(contenu)) + genre + contenu + struct.pack('>I', zlib.crc32(genre + contenu) & 0xffffffff)


def copier_description(source, sortie):
    """Remplace la description de l'image agrandie (sd-cli y ecrit ses reglages d'agrandissement) par celle de l'image
    d'origine : description, variante et LoRA restent ceux de la creation."""
    textes = [(g, c) for g, c in morceaux_png(Path(source).read_bytes()) if g == b'tEXt' and c.startswith(b'parameters\x00')]
    morceaux = [(g, c) for g, c in morceaux_png(Path(sortie).read_bytes())
                if not (g in (b'tEXt', b'iTXt', b'zTXt') and c.split(b'\x00', 1)[0] == b'parameters')]
    resultat = SIGNATURE_PNG
    for genre, contenu in morceaux:
        resultat += morceau_png(genre, contenu)
        if genre == b'IHDR':
            resultat += b''.join(morceau_png(g, c) for g, c in textes)
    Path(sortie).write_bytes(resultat)


def executer(commande, lancer, rapporter, annule):
    """Lance sd-cli et rapporte les morceaux agrandis (etape sur total). Renvoie (code, erreurs)."""
    processus = lancer(commande)
    reste, journal = '', []
    while True:
        bloc = processus.stdout.read1(4096)
        if not bloc:
            break
        lignes = re.split(r'[\r\n]+', reste + bloc.decode('utf-8', 'replace'))
        reste = lignes.pop()
        for ligne in lignes:
            if ligne.strip():
                journal = (journal + [ligne])[-60:]
            pas = PAS.findall(ligne)
            if pas:
                fait, total = map(int, pas[-1])
                rapporter(phase='agrandissement', etape=fait, total=total)
    code = processus.wait()
    erreurs = [] if annule() else [l for l in journal if re.search(r'^\[E\]|error|out of memory', l, re.I)]
    return code, erreurs
