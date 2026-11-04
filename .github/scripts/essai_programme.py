"""Lance le programme construit, verifie qu'il repond, puis l'arrete par le bouton Quitter."""
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
demande = urllib.request.Request('http://127.0.0.1:7861/api/quitter', data=b'{}', method='POST',
                                 headers={'Content-Type': 'application/json'})
urllib.request.urlopen(demande, timeout=5).close()
processus.wait(timeout=30)
print('arret propre, code', processus.returncode)
