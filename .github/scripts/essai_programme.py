"""Lance le programme construit, verifie qu'il repond et qu'il sait installer son moteur (telechargement https), puis l'arrete.
Sous Windows et Mac, le relance avec sa fenetre Qt (sans ecran) et verifie qu'elle se charge, et le temps qu'il met."""
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# Taille du programme : l'exe (Windows, Linux) ou tout le paquet Prisme.app (Mac)
programme = Path(sys.argv[1]).resolve()
paquet = next((p for p in programme.parents if p.suffix == '.app'), None)
octets = sum(f.stat().st_size for f in paquet.rglob('*') if f.is_file()) if paquet else programme.stat().st_size
print(f'taille {octets / 1e6:.0f} Mo')

processus = subprocess.Popen([os.path.abspath(sys.argv[1]), '--sans-fenetre'])
etat = None
for _ in range(60):
    try:
        with urllib.request.urlopen('http://127.0.0.1:7861/api/etat', timeout=2) as reponse:
            etat = json.load(reponse)
        break
    except OSError:
        time.sleep(1)
assert etat, 'Le programme ne repond pas'
print('version', etat['version'], '| problemes', etat['problemes'])

# Installation du moteur d'images depuis GitHub, comme au premier lancement : verifie les certificats https de l'exe
demande = urllib.request.Request('http://127.0.0.1:7861/api/installer-moteur', data=b'{"moteur": "image"}', method='POST',
                                 headers={'Content-Type': 'application/json'})
urllib.request.urlopen(demande, timeout=10).close()
installation = None
for _ in range(600):
    with urllib.request.urlopen('http://127.0.0.1:7861/api/etat', timeout=5) as reponse:
        moteur = json.load(reponse)['moteurs']['image']
    installation = moteur['installation'] or {}
    if installation.get('phase') in ('termine', 'erreur'):
        break
    time.sleep(1)
print('moteur', moteur['nom'], moteur['acceleration'], '|', installation.get('phase'), installation.get('erreur') or '')
assert installation.get('phase') == 'termine', f"Installation du moteur impossible : {installation.get('erreur')}"
demande = urllib.request.Request('http://127.0.0.1:7861/api/quitter', data=b'{}', method='POST',
                                 headers={'Content-Type': 'application/json'})
urllib.request.urlopen(demande, timeout=5).close()
processus.wait(timeout=30)
print('arret propre, code', processus.returncode)

if not sys.platform.startswith('linux'):
    # Prisme 2 : la fenetre Qt Quick du programme construit (PySide6 et QML embarques) se charge. Deux lancements :
    # le premier compte aussi les verifications du systeme (macOS examine chaque bibliotheque nouvelle)
    for lancement in ('premier', 'deuxieme'):
        debut = time.monotonic()
        processus = subprocess.Popen([os.path.abspath(sys.argv[1])], env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'})
        fenetre = None
        for _ in range(240):
            try:
                with urllib.request.urlopen('http://127.0.0.1:7861/api/etat', timeout=2) as reponse:
                    fenetre = json.load(reponse).get('fenetre')
                if fenetre == 'qt':
                    break
            except OSError:
                pass
            time.sleep(0.25)
        print('fenetre', fenetre, f'| {lancement} lancement : prete en {time.monotonic() - debut:.1f} s')
        assert fenetre == 'qt', 'La fenetre Qt ne se charge pas dans le programme construit'
        demande = urllib.request.Request('http://127.0.0.1:7861/api/quitter', data=b'{}', method='POST',
                                         headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(demande, timeout=5).close()
        processus.wait(timeout=30)
        print('arret propre, code', processus.returncode)
