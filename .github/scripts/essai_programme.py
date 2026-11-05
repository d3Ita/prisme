"""Lance le programme construit, verifie qu'il repond et qu'il sait installer son moteur (telechargement https), puis l'arrete."""
import json
import os
import subprocess
import sys
import time
import urllib.request

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
