"""Prisme 2 : captures de la fenetre Qt Quick, pour la regarder sans rien installer.

Lance par la CI (Linux, ecran virtuel Xvfb). Un vrai serveur de Prisme tourne dans un dossier temporaire, avec de
fausses images (degrades) et un faux moteur, puis la fenetre est photographiee en clair, en sombre, et pendant une
creation. Usage : python .github/scripts/apercu_qt.py <dossier des captures>"""
import json
import math
import os
import struct
import sys
import tempfile
import threading
import time
import zlib
from pathlib import Path

RACINE = Path(tempfile.mkdtemp(prefix='prisme_apercu_'))
os.environ['PRISME_RACINE'] = str(RACINE)
os.environ['PRISME_PORT'] = '7899'
# Interface en francais, comme sur le Mac de l'auteur (la CI est en anglais)
os.environ['LANG'] = os.environ['LC_ALL'] = 'fr_FR.UTF-8'
APP = Path(__file__).resolve().parents[2] / 'app'
sys.path.insert(0, str(APP))

IMAGES = [
    ((640, 640), ((247, 160, 92), (92, 54, 150)), 'Un renard roux assis dans la neige au coucher du soleil, lumière dorée'),
    ((768, 432), ((34, 120, 168), (238, 214, 160)), 'Une plage déserte au petit matin, brume légère, style photo argentique'),
    ((432, 768), ((26, 32, 64), (214, 92, 128)), 'Affiche rétro d’une ville futuriste la nuit, néons roses et bleus'),
]


def png(largeur, hauteur, couleurs, prompt, seed):
    """Degrade diagonal avec un halo, en PNG avec sa description, comme les images de sd-cli."""
    (r1, g1, b1), (r2, g2, b2) = couleurs
    lignes = bytearray()
    for y in range(hauteur):
        lignes.append(0)
        for x in range(largeur):
            t = (x / largeur + y / hauteur) / 2
            halo = max(0.0, 1 - math.hypot(x - largeur * 0.68, y - hauteur * 0.32) / (min(largeur, hauteur) * 0.32))
            lignes += bytes(min(255, round(a + (b - a) * t + 70 * halo)) for a, b in ((r1, r2), (g1, g2), (b1, b2)))

    def bloc(genre, contenu):
        return struct.pack('>I', len(contenu)) + genre + contenu + struct.pack('>I', zlib.crc32(genre + contenu) & 0xffffffff)

    texte = f'{prompt}\nSteps: 20, CFG scale: 4.0, Seed: {seed}'.encode('utf-8')
    return (b'\x89PNG\r\n\x1a\n' + bloc(b'IHDR', struct.pack('>IIBBBBB', largeur, hauteur, 8, 2, 0, 0, 0))
            + bloc(b'tEXt', b'parameters\x00' + texte) + bloc(b'IDAT', zlib.compress(bytes(lignes), 6)) + bloc(b'IEND', b''))


def preparer():
    """Un Prisme pret : faux moteur, faux modeles choisis, trois images."""
    (RACINE / 'sd').mkdir()
    (RACINE / 'sd' / 'sd-cli').write_bytes(b'')
    (RACINE / 'models').mkdir()
    reglages = {'modele_diffusion': 'flux-2-klein-4b-Q8_0.gguf', 'modele_texte': 'Qwen3-4B-Q8_0.gguf',
                'vae': 'flux2-vae.safetensors', 'amelioration_modele_local': 'Qwen3-4B-Q8_0.gguf'}
    for fichier in set(reglages.values()):
        (RACINE / 'models' / fichier).write_bytes(b'')
    (RACINE / 'app').mkdir()
    (RACINE / 'app' / 'reglages.json').write_text(json.dumps(reglages), encoding='utf-8')
    (RACINE / 'images').mkdir()
    for i, ((largeur, hauteur), couleurs, prompt) in enumerate(IMAGES):
        chemin = RACINE / 'images' / f'image_20261112_10{i:02d}00.png'
        chemin.write_bytes(png(largeur, hauteur, couleurs, prompt, 1000 + i))
        os.utime(chemin, (1_800_000_000 + i * 60,) * 2)


def main(dossier):
    preparer()
    import serveur
    from PySide6.QtCore import QEventLoop, QMetaObject, QObject
    from PySide6.QtGui import QFont

    http = serveur.Serveur(('127.0.0.1', serveur.PORT), serveur.Gestionnaire)
    threading.Thread(target=http.serve_forever, daemon=True).start()
    import fenetre_qt
    application = fenetre_qt.application()
    # Police proche de celles du Mac et de Windows (le Linux de la CI n'a que DejaVu par defaut)
    application.setFont(QFont('Inter', 10))
    sortie = Path(dossier)
    sortie.mkdir(parents=True, exist_ok=True)

    def attendre(secondes):
        fin = time.monotonic() + secondes
        while time.monotonic() < fin:
            application.processEvents(QEventLoop.AllEvents, 50)
            time.sleep(0.02)

    erreurs = []

    def capturer(nom, apparence, pendant_creation=False, ouvrir=None, modification=False, preparer=None):
        if preparer:
            preparer()
        moteur = fenetre_qt.charger(f'http://127.0.0.1:{serveur.PORT}', APP, erreurs, width=1280, height=860, apparence=apparence)
        if not moteur.rootObjects():
            sys.exit('La fenêtre ne se charge pas :\n' + '\n'.join(erreurs))
        fenetre = moteur.rootObjects()[0]
        attendre(4)
        if pendant_creation:
            with serveur.verrou:
                serveur.etat.update(occupe=True, phase='dessin', etape=13, total=20, index=1, nombre=1, debut=time.time() - 9,
                                    prompt='Un phare sur une falaise pendant une tempête, vagues immenses',
                                    largeur=1024, hauteur=1024, resultats=[], claude=False)
            attendre(3)
        if ouvrir:
            QMetaObject.invokeMethod(fenetre.findChild(QObject, ouvrir), 'open')
            attendre(3)
        if modification:
            # Une image du fil choisie avec Modifier : elle devient l'image de depart, format Original
            nom_image = 'image_20261112_100000.png'
            fenetre.setProperty('source', {'galerie': nom_image, 'nom': nom_image, 'largeur': 640, 'hauteur': 640,
                                           'url': f'http://127.0.0.1:{serveur.PORT}/images/{nom_image}'})
            fenetre.setProperty('format', 'source')
            attendre(2)
        # Capture par l'ecran (virtuel) : PySide6 ne voit la fenetre que comme une QWindow
        application.primaryScreen().grabWindow(fenetre.winId()).save(str(sortie / f'{nom}.png'))
        print('capture', nom)
        with serveur.verrou:
            serveur.etat.clear()
            serveur.etat['occupe'] = False
        serveur.demandes.clear()
        serveur.consentements.clear()
        serveur.mise_a_jour.clear()
        fenetre.close()
        moteur.deleteLater()
        attendre(0.5)

    capturer('1-clair', 'clair')
    capturer('2-sombre', 'sombre')
    capturer('3-creation-en-cours', 'clair', pendant_creation=True)
    capturer('4-modeles', 'clair', ouvrir='modeles')
    capturer('5-reglages', 'clair', ouvrir='reglages')
    capturer('6-modeles-sombre', 'sombre', ouvrir='modeles')
    capturer('7-modification', 'clair', modification=True)
    capturer('8-telephone', 'clair', ouvrir='telephone')

    def demande_acces():
        serveur.demandes['essai'] = {'ip': '192.168.1.24', 'appareil': 'iPhone', 'code': '4817', 'etat': 'attente', 'cree': time.time()}

    def accord_claude():
        serveur.consentements['essai'] = {
            'genre': 'externe', 'etat': 'attente', 'cree': time.time(), 'telechargements': [],
            'details': {'url': 'https://huggingface.co/exemple/modele/resolve/main/style-aquarelle.safetensors',
                        'hote': 'huggingface.co', 'fichier': 'loras/style-aquarelle.safetensors', 'taille': 228_000_000,
                        'sha256': None, 'role': 'lora'}}

    def nouvelle_version():
        serveur.mise_a_jour.update(version='2.0.0', url=serveur.PAGE_VERSIONS, fichier=None, auto=True)

    capturer('9-demande-telephone', 'clair', preparer=demande_acces)
    capturer('10-accord-claude', 'sombre', preparer=accord_claude)
    capturer('11-nouvelle-version', 'clair', preparer=nouvelle_version)
    http.shutdown()
    # Une erreur QML (liaison cassee avec de vraies donnees) fait echouer la CI
    for e in erreurs:
        print('QML :', e)
    sys.exit(1 if erreurs else 0)


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'captures')
