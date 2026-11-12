"""Construit Prisme pour le systeme en cours, apres avoir lance les tests.

Windows : Prisme.exe a la racine du projet
Mac     : dist/Prisme-macOS-arm64.dmg (a ouvrir, puis glisser Prisme.app dans Applications)
          et dist/Prisme-macOS-arm64.zip (pour la mise a jour en un clic)
Linux   : dist/Prisme-Linux-x64.tar.gz (programme prisme)

Prerequis : pip install pyinstaller pillow PySide6-Essentials==6.8.1 segno==1.6.1
"""

import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

RACINE = Path(__file__).resolve().parent
TRAVAIL = RACINE / '.construction'
DIST = RACINE / 'dist'
WINDOWS = sys.platform == 'win32'
MAC = sys.platform == 'darwin'


def lancer(*commande):
    subprocess.run([str(c) for c in commande], check=True, cwd=RACINE)


def main():
    # Pas de programme si un test echoue
    lancer(sys.executable, '-m', 'unittest', 'discover', '-s', RACINE / 'tests')

    TRAVAIL.mkdir(exist_ok=True)
    icone = TRAVAIL / ('icone.icns' if MAC else 'icone.ico')
    demarrage = TRAVAIL / 'demarrage.png'
    lancer(sys.executable, RACINE / 'app' / 'icone.py', RACINE / 'docs' / 'logo.png', icone, demarrage)

    # Pillow sert a la construction (icone) mais pas au programme : l'apercu MCP s'en passe
    options = ['--noconfirm', '--clean', '--name', 'Prisme', '--windowed', '--exclude-module', 'PIL', '--icon', icone,
               '--add-data', f'{RACINE / "app" / "index.html"}{os.pathsep}.',
               '--add-data', f'{RACINE / "app" / "logo.png"}{os.pathsep}.',
               '--add-data', f'{RACINE / "app" / "modeles.json"}{os.pathsep}.',
               # Prisme 2 : la fenetre Qt Quick (PySide6 et segno doivent etre installes pour la construction)
               '--add-data', f'{RACINE / "app" / "qml"}{os.pathsep}qml',
               '--workpath', TRAVAIL / 'build', '--specpath', TRAVAIL]
    if WINDOWS:
        # L'ecran de demarrage n'existe pas sous Mac ; sous Linux, il demanderait Tk sur la machine
        options += ['--onefile', '--splash', demarrage, '--distpath', RACINE]
    elif MAC:
        options += ['--onedir', '--distpath', TRAVAIL / 'dist']
    else:
        options += ['--onefile', '--distpath', TRAVAIL / 'dist']
    lancer(sys.executable, '-m', 'PyInstaller', *options, RACINE / 'app' / 'serveur.py')

    if WINDOWS:
        print(f'Programme cree : {RACINE / "Prisme.exe"}')
        return
    DIST.mkdir(exist_ok=True)
    if MAC:
        # ditto garde les liens et les droits du paquet .app, que le module zipfile perdrait
        archive = DIST / 'Prisme-macOS-arm64.zip'
        archive.unlink(missing_ok=True)
        lancer('ditto', '-c', '-k', '--keepParent', TRAVAIL / 'dist' / 'Prisme.app', archive)
        # Image disque comme les autres apps Mac : Prisme.app a cote d'un raccourci vers Applications. Glissee depuis
        # le Finder, l'app n'est plus lancee depuis une copie temporaire de macOS (App Translocation)
        contenu = TRAVAIL / 'dmg'
        shutil.rmtree(contenu, ignore_errors=True)
        contenu.mkdir()
        lancer('ditto', TRAVAIL / 'dist' / 'Prisme.app', contenu / 'Prisme.app')
        (contenu / 'Applications').symlink_to('/Applications')
        image = DIST / 'Prisme-macOS-arm64.dmg'
        image.unlink(missing_ok=True)
        lancer('hdiutil', 'create', '-volname', 'Prisme', '-srcfolder', contenu, '-fs', 'HFS+', '-format', 'UDZO', image)
        print(f'Image disque creee : {image}')
    else:
        programme = TRAVAIL / 'dist' / 'prisme'
        shutil.move(TRAVAIL / 'dist' / 'Prisme', programme)
        programme.chmod(0o755)
        archive = DIST / 'Prisme-Linux-x64.tar.gz'
        with tarfile.open(archive, 'w:gz') as t:
            t.add(programme, arcname='prisme')
    print(f'Programme cree : {archive}')


if __name__ == '__main__':
    main()
