"""Serveur local de Prisme : sert l'interface web et lance sd-cli (stable-diffusion.cpp)."""

import base64
import hashlib
import shlex
import shutil
import ctypes
import ipaddress
import json
import os
import platform
import random
import re
import secrets
import socket
import ssl
import subprocess
import sys
import tarfile
import tempfile
import zipfile
import http.client
import urllib.error
import urllib.request
import threading
import time
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath, PureWindowsPath
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, unquote, urlparse

VERSION = '1.8.4'
# PRISME_PORT change le port, par exemple pour lancer une version de travail a cote de Prisme
PORT = int(os.environ.get('PRISME_PORT') or 7861)
# Dans l'exe, les fichiers de l'interface sont extraits a part ; les donnees restent a cote de l'exe
EXE = getattr(sys, 'frozen', False)
WINDOWS = sys.platform == 'win32'
MAC = sys.platform == 'darwin'
SYSTEME = 'windows' if WINDOWS else 'mac' if MAC else 'linux'
# Les moteurs et le navigateur ne doivent pas ouvrir de console sous Windows
SANS_CONSOLE = subprocess.CREATE_NO_WINDOW if WINDOWS else 0
# Les moteurs tournent en priorite basse, et laissent un coeur du processeur libre : l'ordinateur reste
# utilisable pendant une generation, sans ralentir le calcul quand rien d'autre ne tourne
OPTIONS_MOTEUR = SANS_CONSOLE | (subprocess.BELOW_NORMAL_PRIORITY_CLASS if WINDOWS else 0)


def fils_calcul():
    logiques = os.cpu_count() or 2
    # Les puces Apple n'ont pas d'hyperthreading ; ailleurs, un coeur physique compte en general deux fils
    physiques = logiques if MAC else max(1, logiques // 2)
    return max(1, physiques - 1)


def lancer_moteur(commande, **options):
    processus = subprocess.Popen(commande, creationflags=OPTIONS_MOTEUR, **options)
    if not WINDOWS:
        try:
            os.setpriority(os.PRIO_PROCESS, processus.pid, 10)
        except (OSError, AttributeError):
            pass
    return processus
SUFFIXE_EXE = '.exe' if WINDOWS else ''
# L'exe Linux ajoute ses propres bibliotheques a LD_LIBRARY_PATH : on rend l'original
# aux programmes lances (moteurs, navigateur), qui chargeraient sinon des versions incompatibles
if EXE and not WINDOWS:
    for variable in ('LD_LIBRARY_PATH', 'DYLD_LIBRARY_PATH'):
        if variable + '_ORIG' in os.environ:
            os.environ[variable] = os.environ[variable + '_ORIG']
        else:
            os.environ.pop(variable, None)
# Bibliotheques du systeme dont les moteurs Linux ont besoin, avec le paquet qui les fournit
BIBLIOTHEQUES_LINUX = {'libgomp.so.1': 'libgomp1', 'libvulkan.so.1': 'libvulkan1'}
RESSOURCES = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
# PRISME_RACINE fait travailler le serveur sur un autre dossier, par exemple un dossier temporaire pour les tests
if os.environ.get('PRISME_RACINE'):
    RACINE = Path(os.environ['PRISME_RACINE']).resolve()
elif EXE and MAC:
    # Une application Mac ne doit pas ecrire dans son propre paquet : les donnees vont dans ~/Prisme
    RACINE = Path.home() / 'Prisme'
else:
    RACINE = Path(sys.executable).resolve().parent if EXE else Path(__file__).resolve().parent.parent
RACINE.mkdir(parents=True, exist_ok=True)
DONNEES = RACINE / 'app'
MODELES = RACINE / 'models'
LORAS = MODELES / 'loras'
IMAGES = RACINE / 'images'
SD_CLI = RACINE / 'sd' / f'sd-cli{SUFFIXE_EXE}'
LLAMA_SERVEUR = RACINE / 'llama' / f'llama-server{SUFFIXE_EXE}'
TELECHARGEMENTS = RACINE / '.telechargements'

# Moteurs installes par Prisme au premier lancement : versions officielles testees, verifiees par empreinte
SD_VERSION = 'https://github.com/leejet/stable-diffusion.cpp/releases/download/master-1039-290148d/'
LLAMA_VERSION = 'https://github.com/ggml-org/llama.cpp/releases/download/b12100/'
MOTEURS_PAR_SYSTEME = {
  'windows': {
    'image': {
        'nom': 'stable-diffusion.cpp', 'version': 'master-1039-290148d', 'dossier': 'sd', 'executable': 'sd-cli.exe',
        'archives': [
            {'url': 'https://github.com/leejet/stable-diffusion.cpp/releases/download/master-1039-290148d/'
                    'sd-master-290148d-bin-win-cuda12-x64.zip',
             'taille': 361586913, 'sha256': 'e389e1009037c3c5d4d00f07fb4f96d011734e1b887b994c7a9fce309ef555d2'},
            {'url': 'https://github.com/leejet/stable-diffusion.cpp/releases/download/master-1039-290148d/'
                    'cudart-sd-bin-win-cu12-x64.zip',
             'taille': 563452046, 'sha256': 'fe20366827d357c00797eebb58244dddab7fd9a348d70090c3871004c320f38d'},
        ],
    },
    'texte': {
        'nom': 'llama.cpp', 'version': 'b12100', 'dossier': 'llama', 'executable': 'llama-server.exe',
        'archives': [
            {'url': 'https://github.com/ggml-org/llama.cpp/releases/download/b12100/llama-b12100-bin-win-cuda-12.4-x64.zip',
             'taille': 287009354, 'sha256': 'b281eb49c5771013dd79bdd187432de6bc3352fd3a47c26d88e8d6572cf3dbea'},
        ],
        # Meme generation CUDA que le moteur d'images : ses DLL sont reprises par lien, sans les retelecharger
        'requiert': 'image',
        'dll_partagees': ['cublas64_12.dll', 'cublasLt64_12.dll', 'cudart64_12.dll'],
    },
  },
  # Windows sans carte NVIDIA : versions Vulkan, pour les cartes AMD et Intel
  'windows-vulkan': {
    'image': {
        'nom': 'stable-diffusion.cpp', 'version': 'master-1039-290148d', 'dossier': 'sd', 'executable': 'sd-cli.exe',
        'archives': [{'url': SD_VERSION + 'sd-master-290148d-bin-win-vulkan-x64.zip', 'taille': 29800696,
                      'sha256': 'd333b2b3fd0a26e5a0917341e6a730c95335e551f342f5bf8b5b4f4ccf0b3cf1'}],
    },
    'texte': {
        'nom': 'llama.cpp', 'version': 'b12100', 'dossier': 'llama', 'executable': 'llama-server.exe',
        'archives': [{'url': LLAMA_VERSION + 'llama-b12100-bin-win-vulkan-x64.zip', 'taille': 37660126,
                      'sha256': '7cf10d097449202aad72a7207d48ddfcfeb8ef719fd093b1727a93cdca4913b2'}],
    },
  },
  # Linux : versions Vulkan, qui marchent avec les cartes NVIDIA, AMD et Intel
  'linux': {
    'image': {
        'nom': 'stable-diffusion.cpp', 'version': 'master-1039-290148d', 'dossier': 'sd', 'executable': 'sd-cli',
        'archives': [{'url': SD_VERSION + 'sd-master-290148d-bin-Linux-Ubuntu-24.04-x86_64-vulkan.zip', 'taille': 37677240,
                      'sha256': '95ce28a87d12b09f64aacc8ee2f0728fa40ada4afb9ebd26f544ef1063d86bdb'}],
    },
    'texte': {
        'nom': 'llama.cpp', 'version': 'b12100', 'dossier': 'llama', 'executable': 'llama-server',
        'archives': [{'url': LLAMA_VERSION + 'llama-b12100-bin-ubuntu-vulkan-x64.tar.gz', 'taille': 35860090,
                      'sha256': 'dfe0478b552af911cb3b1fc15943106f6adbc949df446903ed0098ba602e079a'}],
    },
  },
  # Mac : versions Metal pour les puces Apple
  'mac': {
    'image': {
        'nom': 'stable-diffusion.cpp', 'version': 'master-1039-290148d', 'dossier': 'sd', 'executable': 'sd-cli',
        'archives': [{'url': SD_VERSION + 'sd-master-290148d-bin-Darwin-macOS-26.6.2-arm64.zip', 'taille': 37649640,
                      'sha256': '9e85e31dfa4daae0259c66ac41fab8a5441688b77ee2a761845c3cb88c16f4a4'}],
    },
    'texte': {
        'nom': 'llama.cpp', 'version': 'b12100', 'dossier': 'llama', 'executable': 'llama-server',
        'archives': [{'url': LLAMA_VERSION + 'llama-b12100-bin-macos-arm64.tar.gz', 'taille': 16651168,
                      'sha256': '7085982920120f53bd59821dccc84a66faeb4a6c592b4cc3e020911da5818dea'}],
    },
  },
}
# Le meme fichier par l'API GitHub, quand le lien direct des releases ne repond pas (erreurs 504 de github.com)
LIENS_SECOURS = {
    'sd-master-290148d-bin-win-cuda12-x64.zip': 'https://api.github.com/repos/leejet/stable-diffusion.cpp/releases/assets/699547367',
    'cudart-sd-bin-win-cu12-x64.zip': 'https://api.github.com/repos/leejet/stable-diffusion.cpp/releases/assets/699545839',
    'sd-master-290148d-bin-win-vulkan-x64.zip': 'https://api.github.com/repos/leejet/stable-diffusion.cpp/releases/assets/699547949',
    'sd-master-290148d-bin-Linux-Ubuntu-24.04-x86_64-vulkan.zip': 'https://api.github.com/repos/leejet/stable-diffusion.cpp/releases/assets/699547131',
    'sd-master-290148d-bin-Darwin-macOS-26.6.2-arm64.zip': 'https://api.github.com/repos/leejet/stable-diffusion.cpp/releases/assets/699546521',
    'llama-b12100-bin-win-cuda-12.4-x64.zip': 'https://api.github.com/repos/ggml-org/llama.cpp/releases/assets/708736623',
    'llama-b12100-bin-win-vulkan-x64.zip': 'https://api.github.com/repos/ggml-org/llama.cpp/releases/assets/708738790',
    'llama-b12100-bin-ubuntu-vulkan-x64.tar.gz': 'https://api.github.com/repos/ggml-org/llama.cpp/releases/assets/708736190',
    'llama-b12100-bin-macos-arm64.tar.gz': 'https://api.github.com/repos/ggml-org/llama.cpp/releases/assets/708733521',
}
for _moteurs in MOTEURS_PAR_SYSTEME.values():
    for _moteur in _moteurs.values():
        for _archive in _moteur['archives']:
            _archive['secours'] = LIENS_SECOURS.get(_archive['url'].rsplit('/', 1)[1])
ACCELERATIONS = {'windows': 'CUDA', 'windows-vulkan': 'Vulkan', 'linux': 'Vulkan', 'mac': 'Metal'}


def carte_nvidia():
    """Le pilote NVIDIA installe nvcuda.dll dans System32 : sans lui, les moteurs CUDA ne peuvent pas marcher."""
    return (Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'nvcuda.dll').is_file()


def choisir_moteurs():
    """Moteurs adaptes a cette machine. Sous Windows, PRISME_ACCELERATION=cuda ou vulkan force le choix."""
    if not WINDOWS:
        return SYSTEME
    force = os.environ.get('PRISME_ACCELERATION', '').strip().lower()
    if force in ('cuda', 'vulkan'):
        return 'windows' if force == 'cuda' else 'windows-vulkan'
    return 'windows' if carte_nvidia() else 'windows-vulkan'


JEU_MOTEURS = choisir_moteurs()
MOTEURS = MOTEURS_PAR_SYSTEME[JEU_MOTEURS]
ACCELERATION = ACCELERATIONS[JEU_MOTEURS]
FICHIER_CODE = DONNEES / 'code-acces.txt'
FICHIER_REGLAGES = DONNEES / 'reglages.json'

CONSIGNE_AMELIORATION = (
    "Tu réécris des descriptions d'images pour un générateur d'images. "
    "Garde exactement le sujet et l'intention de l'utilisateur, sans rien ajouter qui change le sens. "
    "Précise le cadrage, la lumière, l'ambiance, les matières, les couleurs et le style photo ou illustration. "
    "Réponds uniquement par la description finale, en anglais, en un seul paragraphe de 60 à 90 mots. "
    "Écris tout en anglais : aucun mot ni caractère chinois ou d'une autre langue."
)
# En modification, il ne faut pas decrire une nouvelle scene : seulement ce qui change dans l'image fournie
CONSIGNE_MODIFICATION = (
    "Tu reformules une demande de modification d'image pour un modèle d'édition d'images. "
    "L'image jointe, si elle est fournie, est l'image à modifier. "
    "Écris une instruction de modification courte et précise : décris uniquement ce qui doit changer, "
    "en nommant les éléments concernés tels qu'ils apparaissent dans l'image, avec les détails utiles "
    "(couleur, matière, position, lumière du changement). Ne décris pas toute la scène et n'invente aucun autre changement. "
    "Termine par une phrase qui demande de garder tout le reste identique : sujet, composition, cadrage, arrière-plan, éclairage et style. "
    "Réponds uniquement par l'instruction, en anglais, en deux à quatre phrases. "
    "Écris tout en anglais : aucun mot ni caractère chinois ou d'une autre langue."
)
# Certains modeles glissent parfois quelques mots en chinois : on redemande alors une fois
CARACTERES_CJK = re.compile(r'[\u3000-\u30ff\u3400-\u9fff\uac00-\ud7af\uff00-\uffef]')

# Aucun modele impose : ils se choisissent dans les Reglages au premier lancement
REGLAGES_DEFAUT = {
    'modele_diffusion': '',
    'modele_texte': '',
    'modele_vision': '',
    'vae': '',
    'etapes': 20,
    'cfg': 4.0,
    'methode': 'euler',
    'sigmas': '',
    'dechargement_cpu': True,
    'vae_tuiles': True,
    'flash_attention': True,
    # L'acces depuis le reseau local s'active dans les Reglages
    'acces_reseau': False,
    'arret_auto_minutes': 30,
    # Arrete le serveur quelques secondes apres la fermeture de la fenetre du PC
    'arret_fermeture': True,
    # [{'nom': 'fichier.safetensors', 'force': 1.0, 'actif': True}], fichiers du dossier models/loras
    'loras': [],
    # Amelioration de la description par un modele de langage servi par Ollama (vide = desactivee)
    'amelioration_modele': '',
    'amelioration_auto': False,
    'amelioration_consigne': CONSIGNE_AMELIORATION,
    'amelioration_consigne_modif': CONSIGNE_MODIFICATION,
    'ollama_adresse': 'http://127.0.0.1:11434',
    # 'integre' : modele de langage du dossier models lance par llama.cpp ; 'ollama' : modele servi par Ollama
    'amelioration_moteur': 'integre',
    'amelioration_modele_local': '',
    'amelioration_vision_locale': '',
    # Une fois au lancement, Prisme demande a GitHub le numero de la derniere version
    'verifier_mises_a_jour': True,
}
METHODES = ['euler', 'euler_a', 'heun', 'dpm2', 'dpm++2s_a', 'dpm++2m', 'dpm++2mv2', 'ipndm', 'ipndm_v', 'lcm',
            'ddim_trailing', 'tcd', 'res_multistep', 'res_2s', 'er_sde', 'euler_cfg_pp', 'euler_a_cfg_pp', 'euler_ge',
            'dpm++2m_sde', 'dpm++2m_sde_bt', 'lms']
EXTENSIONS_MODELES = ('.gguf', '.safetensors', '.ckpt', '.pt', '.bin')
EXTENSIONS_LORA = ('.safetensors', '.gguf')
# sd-cli lit les LoRA dans la description sous la forme <lora:nom:force>
BALISE_LORA = re.compile(r'<lora:([^:>]+):([^>]+)>')

NOM_IMAGE = re.compile(r'^[\w.-]+\.png$')
# Taille maximale d'une requete : une image de depart en base64 tient largement dedans
TAILLE_MAX_REQUETE = 64 * 1024 * 1024
# Au-dela de ce nombre de codes faux, l'appareil est bloque un moment
ESSAIS_MAX, FENETRE_ESSAIS = 10, 15 * 60
# Connexion d'un appareil en tapant seulement l'adresse : il demande l'acces, le PC l'autorise
DUREE_DEMANDE, DEMANDES_MAX_PAR_APPAREIL = 120, 3
PAS = re.compile(r'(\d+)/(\d+)\s*-\s*[\d.,]+\s*(?:s/it|it/s)')

verrou = threading.Lock()
dernier_contact = time.time()
# Fermeture de la fenetre du PC : le serveur s'arrete si elle n'est pas rouverte juste apres (rechargement)
dernier_contact_local = time.time()
fermeture_demandee = None
DELAI_FERMETURE = 6
# Moteur de texte en cours d'utilisation, a arreter avec le serveur
processus_texte = None
etat = {'occupe': False}
processus = None
annule = False
amelioration_en_cours = threading.Lock()
cache_infos = {}
echecs = {}
demandes = {}
verrou_demandes = threading.Lock()
verrou_echecs = threading.Lock()
# Acces reseau du serveur en cours : un changement de reglage s'applique au prochain lancement
SERVEUR_RESEAU = True


def chemin_relatif_sur(nom):
    """Vrai si le chemin reste dans son dossier, en appliquant les regles de Windows et des autres systemes."""
    nom = str(nom).replace('\\', '/')
    return bool(nom) and not (PureWindowsPath(nom).anchor or PurePosixPath(nom).anchor or '..' in PurePosixPath(nom).parts)


def lire_reglages():
    reglages = dict(REGLAGES_DEFAUT)
    try:
        enregistres = json.loads(FICHIER_REGLAGES.read_text(encoding='utf-8-sig'))
        reglages.update({k: v for k, v in enregistres.items() if k in REGLAGES_DEFAUT})
    except (OSError, ValueError):
        pass
    return reglages


def valider_reglages(donnees):
    """Renvoie (reglages, erreur) : les modeles sont des chemins relatifs au dossier models."""
    r = lire_reglages()
    try:
        for cle in ('modele_diffusion', 'modele_texte', 'modele_vision', 'vae', 'amelioration_modele_local',
                    'amelioration_vision_locale'):
            nom = str(donnees.get(cle, r[cle])).strip().replace('\\', '/')
            if nom and not chemin_relatif_sur(nom):
                return None, 'Les modèles doivent être dans le dossier models.'
            r[cle] = nom
        r['etapes'] = int(donnees.get('etapes', r['etapes']))
        r['cfg'] = float(donnees.get('cfg', r['cfg']))
        r['methode'] = str(donnees.get('methode', r['methode']))
        r['sigmas'] = ','.join(x.strip() for x in str(donnees.get('sigmas', r['sigmas'])).split(',') if x.strip())
        for cle in ('dechargement_cpu', 'vae_tuiles', 'flash_attention', 'acces_reseau', 'arret_fermeture',
                    'verifier_mises_a_jour'):
            r[cle] = bool(donnees.get(cle, r[cle]))
        r['arret_auto_minutes'] = int(donnees.get('arret_auto_minutes', r['arret_auto_minutes']))
        loras = []
        for l in donnees.get('loras', r['loras']) or []:
            nom = str(l.get('nom', '')).strip().replace('\\', '/')
            if not chemin_relatif_sur(nom) or re.search(r'[:<>]', nom) \
                    or Path(nom).suffix.lower() not in EXTENSIONS_LORA:
                return None, f'Nom de LoRA invalide : {nom}'
            loras.append({'nom': nom, 'force': round(float(l.get('force', 1.0)), 2), 'actif': bool(l.get('actif', True))})
        r['loras'] = loras
        r['amelioration_modele'] = str(donnees.get('amelioration_modele', r['amelioration_modele'])).strip()
        r['amelioration_auto'] = bool(donnees.get('amelioration_auto', r['amelioration_auto']))
        r['amelioration_consigne'] = str(donnees.get('amelioration_consigne', r['amelioration_consigne'])).strip() \
            or CONSIGNE_AMELIORATION
        r['amelioration_consigne_modif'] = str(donnees.get('amelioration_consigne_modif', r['amelioration_consigne_modif'])).strip() \
            or CONSIGNE_MODIFICATION
        r['ollama_adresse'] = str(donnees.get('ollama_adresse', r['ollama_adresse'])).strip().rstrip('/')
        r['amelioration_moteur'] = str(donnees.get('amelioration_moteur', r['amelioration_moteur']))
        [float(x) for x in r['sigmas'].split(',') if r['sigmas']]
    except (TypeError, ValueError):
        return None, 'Une valeur est invalide.'
    if not r['modele_diffusion'] or not r['modele_texte'] or not r['vae']:
        return None, 'Choisis au moins le modèle de dessin, l\'encodeur de texte et le VAE.'
    if not 1 <= r['etapes'] <= 150:
        return None, 'Le nombre d\'étapes doit être entre 1 et 150.'
    if not 0 <= r['cfg'] <= 30:
        return None, 'Le CFG doit être entre 0 et 30.'
    if r['methode'] not in METHODES:
        return None, 'Méthode d\'échantillonnage inconnue.'
    if r['sigmas'] and len(r['sigmas'].split(',')) != r['etapes'] + 1:
        return None, f'Il faut {r["etapes"] + 1} sigmas pour {r["etapes"]} étapes, ou laisser le champ vide.'
    if r['amelioration_moteur'] not in ('integre', 'ollama'):
        return None, 'Moteur d\'amélioration inconnu.'
    if not re.match(r'^https?://[^/\s]+$', r['ollama_adresse']):
        return None, 'Adresse d\'Ollama invalide (exemple : http://127.0.0.1:11434).'
    if any(not -2 <= l['force'] <= 2 for l in r['loras']):
        return None, 'La force d\'un LoRA doit être entre -2 et 2.'
    if not 1 <= r['arret_auto_minutes'] <= 24 * 60:
        return None, 'L\'arrêt automatique doit être entre 1 et 1440 minutes.'
    return r, None


def lister_modeles():
    if not MODELES.exists():
        return []
    return sorted(({'nom': f.relative_to(MODELES).as_posix(), 'taille': f.stat().st_size}
                   for f in MODELES.rglob('*') if f.is_file() and f.suffix.lower() in EXTENSIONS_MODELES
                   and LORAS not in f.parents),
                  key=lambda m: m['nom'].lower())


def paquets_manquants():
    """Paquets Linux a installer pour que les moteurs demarrent."""
    if SYSTEME != 'linux':
        return []
    manquants = []
    for bibliotheque, paquet in BIBLIOTHEQUES_LINUX.items():
        try:
            ctypes.CDLL(bibliotheque)
        except OSError:
            manquants.append(paquet)
    return manquants


def problemes_configuration(r):
    """Ce qui empeche de generer, pour guider au premier lancement."""
    problemes = []
    if MAC and platform.machine() != 'arm64':
        problemes.append('Prisme pour Mac nécessite une puce Apple (M1 ou plus récente)')
    manquants = paquets_manquants()
    if manquants:
        problemes.append('Bibliothèques système manquantes : sudo apt install ' + ' '.join(manquants))
    if not SD_CLI.is_file():
        problemes.append('Moteur d\'images non installé')
    roles = {'modele_diffusion': 'Modèle de dessin', 'modele_texte': 'Encodeur de texte', 'vae': 'VAE'}
    for cle, nom in roles.items():
        if not r[cle]:
            problemes.append(f'{nom} : aucun fichier choisi dans les Réglages')
        elif not (MODELES / r[cle]).is_file():
            problemes.append(f'{nom} : fichier introuvable ({r[cle]})')
    return problemes


class _OperationFichier(ctypes.Structure):
    _fields_ = [('hwnd', ctypes.c_void_p), ('wFunc', ctypes.c_uint), ('pFrom', ctypes.c_wchar_p),
                ('pTo', ctypes.c_wchar_p), ('fFlags', ctypes.c_ushort), ('fAnyOperationsAborted', ctypes.c_int),
                ('hNameMappings', ctypes.c_void_p), ('lpszProgressTitle', ctypes.c_wchar_p)]


def mettre_a_la_corbeille(chemin):
    """Met un fichier a la corbeille du systeme, pour qu'il reste recuperable."""
    chemin = Path(chemin)
    if WINDOWS:
        # FO_DELETE avec FOF_ALLOWUNDO
        operation = _OperationFichier(wFunc=3, pFrom=str(chemin) + '\0', fFlags=0x40 | 0x10 | 0x4 | 0x400)
        resultat = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
        return resultat == 0 and not operation.fAnyOperationsAborted and not chemin.exists()
    if MAC:
        cible = str(chemin).replace('\\', '\\\\').replace('"', '\\"')
        subprocess.run(['osascript', '-e', f'tell application "Finder" to delete POSIX file "{cible}"'], capture_output=True)
        return not chemin.exists()
    if shutil.which('gio'):
        subprocess.run(['gio', 'trash', str(chemin)], capture_output=True)
        if not chemin.exists():
            return True
    # Corbeille freedesktop, utilisee par les bureaux Linux
    corbeille = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share')) / 'Trash'
    (corbeille / 'files').mkdir(parents=True, exist_ok=True)
    (corbeille / 'info').mkdir(parents=True, exist_ok=True)
    nom, n = chemin.name, 1
    while (corbeille / 'files' / nom).exists():
        nom = f'{chemin.stem}.{n}{chemin.suffix}'
        n += 1
    (corbeille / 'info' / f'{nom}.trashinfo').write_text(
        f'[Trash Info]\nPath={urllib.request.pathname2url(str(chemin.resolve()))}\n'
        f'DeletionDate={datetime.now().strftime("%Y-%m-%dT%H:%M:%S")}\n', encoding='utf-8')
    shutil.move(str(chemin), corbeille / 'files' / nom)
    return not chemin.exists()


def ouvrir_dossier(dossier, selection=None):
    """Ouvre un dossier dans l'explorateur du systeme, en montrant un fichier si demande."""
    if WINDOWS:
        if selection:
            subprocess.Popen(['explorer.exe', '/select,', str(selection)])
        else:
            os.startfile(dossier)
    elif MAC:
        subprocess.Popen(['open', '-R', str(selection)] if selection else ['open', str(dossier)])
    else:
        subprocess.Popen(['xdg-open', str(dossier)])


def appel_ollama(r, chemin, corps=None, delai=10):
    requete = urllib.request.Request(r['ollama_adresse'] + chemin, json.dumps(corps).encode() if corps else None,
                                     {'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(requete, context=contexte_ssl(), timeout=delai) as reponse:
            return json.load(reponse)
    except urllib.error.HTTPError as e:
        detail = e.read().decode('utf-8', 'replace')[:200]
        raise RuntimeError(f'Ollama a refusé la demande : {detail}') from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise RuntimeError('Ollama ne répond pas : lance Ollama ou vérifie son adresse dans les Réglages.') from None


capacites_ollama = {}


def modele_voit_les_images(r):
    nom = r['amelioration_modele']
    if nom not in capacites_ollama:
        try:
            capacites_ollama[nom] = 'vision' in appel_ollama(r, '/api/show', {'model': nom}).get('capabilities', [])
        except RuntimeError:
            return False
    return capacites_ollama[nom]


class MoteurTexte:
    """Lance llama-server le temps d'une amelioration, puis l'arrete pour liberer la carte graphique."""

    def __init__(self, r):
        self.modele = MODELES / r['amelioration_modele_local']
        self.vision = MODELES / r['amelioration_vision_locale'] if r['amelioration_vision_locale'] else None
        self.processus = None

    def __enter__(self):
        if not LLAMA_SERVEUR.is_file():
            raise RuntimeError('Le moteur de texte n\'est pas installé : installe-le dans les Réglages.')
        if not self.modele.is_file():
            raise RuntimeError(f'Modèle de langage introuvable : {self.modele.name}')
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            self.port = s.getsockname()[1]
        commande = [str(LLAMA_SERVEUR), '-m', str(self.modele), '-ngl', '99', '-c', '8192',
                    '--host', '127.0.0.1', '--port', str(self.port), '--no-webui']
        if self.vision and self.vision.is_file():
            commande += ['--mmproj', str(self.vision)]
        self.journal = tempfile.TemporaryFile()
        global processus_texte
        commande += ['--threads', str(fils_calcul())]
        self.processus = processus_texte = lancer_moteur(commande, stdout=self.journal, stderr=subprocess.STDOUT)
        limite = time.time() + 300
        while time.time() < limite:
            if self.processus.poll() is not None:
                self.journal.seek(0)
                fin = self.journal.read().decode('utf-8', 'replace').strip().splitlines()[-3:]
                raise RuntimeError('Le moteur de texte s\'est arrêté : ' + ' '.join(fin))
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{self.port}/health', timeout=2) as reponse:
                    if reponse.status == 200:
                        return self
            except OSError:
                time.sleep(0.5)
        raise RuntimeError('Le moteur de texte a mis trop longtemps à démarrer.')

    def discuter(self, messages, temperature):
        corps = json.dumps({'messages': messages, 'temperature': temperature, 'max_tokens': 400}).encode()
        requete = urllib.request.Request(f'http://127.0.0.1:{self.port}/v1/chat/completions', corps,
                                         {'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(requete, timeout=300) as reponse:
                return json.load(reponse)['choices'][0]['message']['content']
        except (OSError, KeyError, ValueError) as e:
            raise RuntimeError(f'Le moteur de texte n\'a pas répondu : {e}') from None

    def __exit__(self, *erreur):
        global processus_texte
        processus_texte = None
        if self.processus and self.processus.poll() is None:
            self.processus.kill()
            self.processus.wait()
        if self.processus:
            self.journal.close()


def nettoyer_reponse(texte):
    # Certains modeles ecrivent leur raisonnement entre balises avant la reponse
    return re.sub(r'<think>.*?</think>', '', texte or '', flags=re.S).strip().strip('"«» ').strip()


def amelioration_active(r):
    if r['amelioration_moteur'] == 'ollama':
        return r['amelioration_modele']
    return Path(r['amelioration_modele_local']).stem if r['amelioration_modele_local'] else ''


def ameliorer_description(r, texte, image=None):
    if r['amelioration_moteur'] == 'ollama':
        return ameliorer_avec_ollama(r, texte, image)
    consigne = r['amelioration_consigne_modif'] if image is not None else r['amelioration_consigne']
    contenu = texte
    if image is not None:
        if r['amelioration_vision_locale']:
            contenu = [{'type': 'text', 'text': texte},
                       {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(image).decode()}}]
        else:
            contenu = f"Demande de modification (l'image n'est pas visible) : {texte}"
    messages = [{'role': 'system', 'content': consigne}, {'role': 'user', 'content': contenu}]
    resultat = ''
    with MoteurTexte(r) as moteur:
        for temperature in (0.6, 0.3):
            resultat = nettoyer_reponse(moteur.discuter(messages, temperature))
            if resultat and not CARACTERES_CJK.search(resultat):
                break
    if not resultat:
        raise RuntimeError('Le modèle n\'a rien renvoyé.')
    return CARACTERES_CJK.sub('', resultat).strip()


def ameliorer_avec_ollama(r, texte, image=None):
    """Avec une image de depart, produit une consigne de modification au lieu d'une nouvelle description."""
    message = {'role': 'user', 'content': texte}
    if image is not None:
        consigne = r['amelioration_consigne_modif']
        if modele_voit_les_images(r):
            message['images'] = [base64.b64encode(image).decode()]
        else:
            message['content'] = f"Demande de modification (l'image n'est pas visible) : {texte}"
    else:
        consigne = r['amelioration_consigne']
    resultat = ''
    for temperature, dernier in ((0.6, False), (0.3, True)):
        reponse = appel_ollama(r, '/api/chat', {
            'model': r['amelioration_modele'],
            'messages': [{'role': 'system', 'content': consigne}, message],
            'stream': False,
            # Libere la carte graphique pour la generation qui suit, sauf avant une seconde tentative
            'keep_alive': 0 if dernier else '30s',
            'options': {'temperature': temperature},
        }, delai=300)
        resultat = nettoyer_reponse(reponse.get('message', {}).get('content', ''))
        if resultat and not CARACTERES_CJK.search(resultat):
            if not dernier:
                appel_ollama(r, '/api/generate', {'model': r['amelioration_modele'], 'keep_alive': 0})
            break
    if not resultat:
        raise RuntimeError('Le modèle n\'a rien renvoyé.')
    return CARACTERES_CJK.sub('', resultat).strip()


installations = {}
verrou_installations = threading.Lock()


def moteur_installe(nom):
    return (RACINE / MOTEURS[nom]['dossier'] / MOTEURS[nom]['executable']).is_file()


def extraire_archive(archive, dossier):
    """Extrait un zip ou un tar.gz sans laisser un fichier sortir du dossier ; retire un dossier racine commun."""
    temporaire = dossier / '.extraction'
    shutil.rmtree(temporaire, ignore_errors=True)
    temporaire.mkdir(parents=True)
    if archive.name.endswith(('.tar.gz', '.tgz')):
        with tarfile.open(archive) as t:
            for m in t.getmembers():
                if not chemin_relatif_sur(m.name):
                    raise RuntimeError(f'Archive refusée : chemin interdit ({m.name})')
            # Le filtre 'data' refuse aussi les liens qui pointeraient hors du dossier
            t.extractall(temporaire, filter='data')
    else:
        with zipfile.ZipFile(archive) as z:
            for m in z.infolist():
                if not chemin_relatif_sur(m.filename):
                    raise RuntimeError(f'Archive refusée : chemin interdit ({m.filename})')
            for m in z.infolist():
                if m.is_dir():
                    continue
                cible = temporaire / PurePosixPath(m.filename.replace('\\', '/'))
                cible.parent.mkdir(parents=True, exist_ok=True)
                with z.open(m) as source, open(cible, 'wb') as destination:
                    shutil.copyfileobj(source, destination)
                # Les zip de Linux et Mac gardent le droit d'execution, que zipfile n'applique pas
                if not WINDOWS and (m.external_attr >> 16) & 0o111:
                    cible.chmod(0o755)
    contenu = list(temporaire.iterdir())
    source = contenu[0] if len(contenu) == 1 and contenu[0].is_dir() else temporaire
    for element in source.iterdir():
        element.rename(dossier / element.name)
    shutil.rmtree(temporaire)


# Certificats racines pour les telechargements en https. Le Python embarque dans l'exe Mac (et parfois Linux)
# cherche ses certificats dans le dossier de la machine qui l'a construit : s'il n'en trouve aucun,
# on charge ceux du systeme. SSL_CERT_FILE, s'il est defini, reste prioritaire.
FICHIERS_CERTIFICATS = ['/etc/ssl/cert.pem', '/etc/ssl/certs/ca-certificates.crt', '/etc/pki/tls/certs/ca-bundle.crt',
                        '/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem', '/etc/ssl/ca-bundle.pem']
_contexte_ssl = None


def contexte_ssl():
    global _contexte_ssl
    if _contexte_ssl is None:
        contexte = ssl.create_default_context()
        if not contexte.cert_store_stats()['x509_ca']:
            charge = False
            for fichier in FICHIERS_CERTIFICATS:
                if os.path.isfile(fichier):
                    try:
                        contexte.load_verify_locations(cafile=fichier)
                        charge = True
                        break
                    except (OSError, ssl.SSLError):
                        pass
            if not charge and MAC:
                # Dernier recours sur Mac : les certificats racines du trousseau systeme
                pem = subprocess.run(['security', 'find-certificate', '-a', '-p',
                                      '/System/Library/Keychains/SystemRootCertificates.keychain'],
                                     capture_output=True, text=True).stdout
                if pem.strip():
                    contexte.load_verify_locations(cadata=pem)
        _contexte_ssl = contexte
    return _contexte_ssl


# Erreurs des serveurs de telechargement qui passent en general d'elles-memes : on reessaie
CODES_PASSAGERS = {408, 425, 429, 500, 502, 503, 504}
ESSAIS = 6
PAUSE_ESSAI = 2


def erreur_passagere(e):
    if isinstance(e, urllib.error.HTTPError):
        return e.code in CODES_PASSAGERS
    return isinstance(e, (OSError, http.client.HTTPException))


def erreur_lisible(e, url):
    """Message clair quand un telechargement echoue malgre les nouveaux essais."""
    hote = urlparse(url).hostname or url
    if isinstance(e, urllib.error.HTTPError):
        if e.code in CODES_PASSAGERS:
            return RuntimeError(f'Le serveur de téléchargement ({hote}) ne répond pas (erreur {e.code}). Réessaie dans quelques minutes.')
        return RuntimeError(f'Téléchargement refusé par {hote} (erreur {e.code}).')
    return RuntimeError(f'Téléchargement impossible depuis {hote} : vérifie la connexion Internet, puis réessaie.')


def requete_github(url, **en_tetes):
    """Requete avec le jeton GITHUB_TOKEN s'il existe (machines de construction de GitHub, qui partagent leurs adresses
    et atteignent vite la limite de l'API) ; le jeton ne part que vers api.github.com, jamais vers une redirection."""
    requete = urllib.request.Request(url, headers={'User-Agent': f'Prisme/{VERSION}', **en_tetes})
    jeton = os.environ.get('GITHUB_TOKEN')
    if jeton and urlparse(url).hostname == 'api.github.com':
        requete.add_unredirected_header('Authorization', f'Bearer {jeton}')
    return requete


def lien_api_github(url):
    """Le meme fichier par l'API GitHub, quand le lien direct d'une release ne repond pas (erreurs 504 de github.com)."""
    m = re.fullmatch(r'https://github\.com/([\w.-]+)/([\w.-]+)/releases/download/([^/]+)/([^/?#]+)', url)
    if not m:
        return None
    proprietaire, depot, tag, nom = m.groups()
    requete = requete_github(f'https://api.github.com/repos/{proprietaire}/{depot}/releases/tags/{tag}',
                             Accept='application/vnd.github+json')
    with urllib.request.urlopen(requete, context=contexte_ssl(), timeout=30) as reponse:
        fichiers = json.load(reponse).get('assets') or []
    lien = next((a.get('url') for a in fichiers if a.get('name') == unquote(nom)), None)
    return lien if lien and lien.startswith(f'https://api.github.com/repos/{proprietaire}/{depot}/releases/assets/') else None


def verifier_reception(reponse, recu):
    """Une connexion coupee peut rendre un fichier tronque sans erreur : on compare avec la taille annoncee."""
    annonce = reponse.headers.get('Content-Length')
    if annonce and annonce.isdigit() and recu != int(annonce):
        raise http.client.IncompleteRead(b'', int(annonce) - recu)


def telecharger(archive, destination, progression):
    """Telecharge une archive en verifiant sa taille et son empreinte SHA-256. Les erreurs passageres sont reessayees ;
    apres deux echecs du lien direct d'une release GitHub, le fichier passe par l'API GitHub. L'empreinte garantit
    que c'est bien le meme fichier, quel que soit le chemin."""
    url, en_tetes, secours = archive['url'], {}, archive.get('secours')
    for essai in range(ESSAIS):
        # Apres deux echecs du lien direct : lien de secours connu, sinon cherche (et recherche encore s'il echoue)
        if essai >= 2 and url == archive['url']:
            if not secours:
                try:
                    secours = lien_api_github(archive['url'])
                except Exception:
                    secours = None
            if secours:
                url, en_tetes = secours, {'Accept': 'application/octet-stream'}
        recu = 0
        empreinte = hashlib.sha256()
        try:
            requete = requete_github(url, **en_tetes)
            with urllib.request.urlopen(requete, context=contexte_ssl(), timeout=60) as reponse, open(destination, 'wb') as fichier:
                while bloc := reponse.read(1024 * 1024):
                    fichier.write(bloc)
                    empreinte.update(bloc)
                    recu += len(bloc)
                    progression(len(bloc))
                verifier_reception(reponse, recu)
            break
        except Exception as e:
            # La progression revient en arriere de ce qui a ete recu pendant cet essai
            progression(-recu)
            if not erreur_passagere(e):
                raise erreur_lisible(e, url) if isinstance(e, urllib.error.HTTPError) else e
            if essai == ESSAIS - 1:
                raise erreur_lisible(e, url)
            time.sleep(min(PAUSE_ESSAI * 2 ** essai, 20))
    if destination.stat().st_size != archive['taille'] or empreinte.hexdigest() != archive['sha256']:
        raise RuntimeError('Le fichier téléchargé ne correspond pas à la version attendue (empreinte différente).')


def installer_moteur(nom):
    moteur = MOTEURS[nom]
    dossier = RACINE / moteur['dossier']
    provisoire = RACINE / f'.{moteur["dossier"]}.installation'
    suivi = installations[nom]

    def avancer(octets):
        with verrou_installations:
            suivi['fait'] += octets

    try:
        if moteur.get('requiert') and not moteur_installe(moteur['requiert']):
            raise RuntimeError('Installe d\'abord le moteur d\'images.')
        shutil.rmtree(provisoire, ignore_errors=True)
        provisoire.mkdir(parents=True)
        TELECHARGEMENTS.mkdir(exist_ok=True)
        for archive in moteur['archives']:
            fichier = TELECHARGEMENTS / archive['url'].rsplit('/', 1)[1]
            telecharger(archive, fichier, avancer)
            with verrou_installations:
                suivi['phase'] = 'extraction'
            extraire_archive(fichier, provisoire)
            fichier.unlink()
            with verrou_installations:
                suivi['phase'] = 'telechargement'
        source = RACINE / MOTEURS.get(moteur.get('requiert'), {}).get('dossier', '')
        for dll in moteur.get('dll_partagees', []):
            try:
                os.link(source / dll, provisoire / dll)
            except OSError:
                shutil.copy2(source / dll, provisoire / dll)
        if not (provisoire / moteur['executable']).is_file():
            raise RuntimeError(f'{moteur["executable"]} est absent de l\'archive.')
        shutil.rmtree(dossier, ignore_errors=True)
        provisoire.rename(dossier)
        try:
            TELECHARGEMENTS.rmdir()
        except OSError:
            pass
        with verrou_installations:
            suivi['phase'] = 'termine'
    except Exception as e:
        shutil.rmtree(provisoire, ignore_errors=True)
        with verrou_installations:
            suivi.update(phase='erreur', erreur=str(e) if isinstance(e, RuntimeError) else f'Installation impossible : {e}')


def etat_moteurs():
    with verrou_installations:
        return {nom: {'installe': moteur_installe(nom), 'nom': m['nom'], 'version': m['version'], 'requiert': m.get('requiert'),
                      'acceleration': ACCELERATION,
                      'taille': sum(a['taille'] for a in m['archives']),
                      'installation': dict(installations[nom]) if nom in installations else None}
                for nom, m in MOTEURS.items()}


# Modeles conseilles, telechargeables depuis Prisme : modeles officiels et generalistes, verifies par empreinte
HF = 'https://huggingface.co/'
DESSIN = HF + 'AtomicChat/Qwen-Image-2.1-Turbo-GGUF/resolve/main/'
VL8B = HF + 'Qwen/Qwen3-VL-8B-Instruct-GGUF/resolve/main/'
MODELES_CONSEILLES = [
    {'id': 'dessin-q4', 'role': 'Modèle de dessin', 'titre': 'Qwen-Image 2.1 Turbo · Q4_K',
     'detail': 'Léger : cartes graphiques de 8 Go', 'pour': ('complet', 'leger'), 'profil_rapide': True,
     'fichier': 'Qwen-Image-2.1-Turbo-AD-Q4_K.gguf', 'url': DESSIN + 'Qwen-Image-2.1-Turbo-AD-Q4_K.gguf',
     'taille': 4201694944, 'sha256': '4bb73c53cbe284bbd6d69b9fdc59539c531f0389dd2aa567663d777f8130bc59',
     'remplit': ['modele_diffusion']},
    {'id': 'dessin-q8', 'role': 'Modèle de dessin', 'titre': 'Qwen-Image 2.1 Turbo · Q8_0',
     'detail': 'Meilleure qualité : cartes de 12 Go ou plus', 'pour': (), 'profil_rapide': True,
     'fichier': 'Qwen-Image-2.1-Turbo-Q8_0.gguf', 'url': DESSIN + 'Qwen-Image-2.1-Turbo-Q8_0.gguf',
     'taille': 7591577312, 'sha256': '8d74ae0be534df394ea2d29f04b77f879318c9e0df20a3e208e6bedbf89b4159',
     'remplit': ['modele_diffusion']},
    {'id': 'texte-q8', 'role': 'Encodeur de texte', 'titre': 'Qwen3-VL 8B · Q8_0',
     'detail': 'Meilleure qualité, sert aussi à améliorer les descriptions', 'pour': ('complet',),
     'fichier': 'Qwen3VL-8B-Instruct-Q8_0.gguf', 'url': VL8B + 'Qwen3VL-8B-Instruct-Q8_0.gguf',
     'taille': 8709519456, 'sha256': '0d264b3941185d00a74f75c4245521dae088ff1efc90ab8d1754e83f5844adb0',
     'remplit': ['modele_texte', 'amelioration_modele_local']},
    {'id': 'texte-q4', 'role': 'Encodeur de texte', 'titre': 'Qwen3-VL 8B · Q4_K_M',
     'detail': 'Plus léger, sert aussi à améliorer les descriptions', 'pour': ('leger',),
     'fichier': 'Qwen3VL-8B-Instruct-Q4_K_M.gguf', 'url': VL8B + 'Qwen3VL-8B-Instruct-Q4_K_M.gguf',
     'taille': 5027784800, 'sha256': '67d1659bfe71b89d50b45a4ad1a9e5b997e5bb16ce5da66a6a6167abd569e9e2',
     'remplit': ['modele_texte', 'amelioration_modele_local']},
    {'id': 'vision-f16', 'role': 'Vision', 'titre': 'Vision Qwen3-VL 8B · F16',
     'detail': 'Pour modifier une image de départ', 'pour': ('complet',),
     'fichier': 'mmproj-Qwen3VL-8B-Instruct-F16.gguf', 'url': VL8B + 'mmproj-Qwen3VL-8B-Instruct-F16.gguf',
     'taille': 1159029824, 'sha256': 'ca524100ebf825c9a870db1c580d03879e0da0ab2541697e2458e64891cf9d38',
     'remplit': ['modele_vision', 'amelioration_vision_locale']},
    {'id': 'vision-q8', 'role': 'Vision', 'titre': 'Vision Qwen3-VL 8B · Q8_0',
     'detail': 'Plus légère, pour modifier une image de départ', 'pour': ('leger',),
     'fichier': 'mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf', 'url': VL8B + 'mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf',
     'taille': 752289728, 'sha256': 'c6ba85508d82f42590e6eb77d5340369ab6fecf107a7561d809523d8aa5f3bfd',
     'remplit': ['modele_vision', 'amelioration_vision_locale']},
    {'id': 'vae', 'role': 'VAE', 'titre': 'VAE Qwen-Image 2.1 Turbo',
     'detail': 'Produit l\'image finale', 'pour': ('complet', 'leger'),
     'fichier': 'qwen-image-vae.safetensors', 'url': HF + 'Qwen/Qwen-Image-2.1-Turbo/resolve/main/vae/diffusion_pytorch_model.safetensors',
     'taille': 675508656, 'sha256': '71879ffd5321e6d10c3c87513e2b474b1252efa7f3dec2969214a9bf06a6dd5c',
     'remplit': ['vae']},
]
MODELES_PAR_ID = {m['id']: m for m in MODELES_CONSEILLES}
GO = 1024 ** 3


def memoire_systeme():
    """Memoire vive totale, en octets (0 si elle n'a pas pu etre lue)."""
    try:
        if WINDOWS:
            class Etat(ctypes.Structure):
                _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong)] + \
                           [(n, ctypes.c_ulonglong) for n in ('total', 'libre', 'fichier', 'fichier_libre', 'virtuelle',
                                                             'virtuelle_libre', 'etendue')]
            e = Etat()
            e.dwLength = ctypes.sizeof(Etat)
            return e.total if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(e)) else 0
        if MAC:
            return int(subprocess.run(['sysctl', '-n', 'hw.memsize'], capture_output=True, text=True, timeout=5).stdout)
        return os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES')
    except (OSError, ValueError, AttributeError, subprocess.SubprocessError):
        return 0


def memoire_video():
    """Memoire de la carte graphique, lue pour les cartes NVIDIA ; sur Mac, la memoire est partagee."""
    if MAC:
        return memoire_systeme()
    try:
        sortie = subprocess.run(['nvidia-smi', '--query-gpu=memory.total', '--format=csv,noheader,nounits'],
                                capture_output=True, text=True, timeout=10, creationflags=SANS_CONSOLE).stdout
        return int(sortie.split()[0]) * 1024 * 1024
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return 0


_machine = None


def profil_machine():
    """Ensemble de modeles adapte : leger si la memoire est juste (Mac de moins de 24 Go, carte de moins de 12 Go,
    ou moins de 24 Go de memoire vive), complet sinon."""
    global _machine
    if _machine is None:
        vive, video = memoire_systeme(), memoire_video()
        if MAC:
            leger = not vive or vive < 24 * GO
        else:
            leger = bool(video and video < 11.5 * GO) or bool(vive and vive < 24 * GO)
        _machine = {'profil': 'leger' if leger else 'complet', 'memoire': vive, 'video': video, 'mac': MAC}
    return _machine
SIGMAS_RAPIDE = '1.0,0.978453,0.95418,0.926626,0.89508,0.845148,0.704534,0.414568,0.0'
# Etat de chaque telechargement : attente, telechargement, verification, termine, annule, erreur
telechargements_modeles = {}
file_modeles = deque()
verrou_modeles = threading.Lock()
travailleur_modeles = None


def empreinte_fichier(chemin):
    empreinte = hashlib.sha256()
    with open(chemin, 'rb') as f:
        while bloc := f.read(8 * 1024 * 1024):
            empreinte.update(bloc)
    return empreinte.hexdigest()


def utiliser_modele(modele):
    """Choisit le modele telecharge dans les reglages : on le telecharge pour s'en servir."""
    r = lire_reglages()
    change = False
    for cle in modele['remplit']:
        if r[cle] != modele['fichier']:
            r[cle] = modele['fichier']
            change = True
            # Ce modele Turbo demande peu d'etapes : profil rapide, sauf si l'utilisateur a deja regle les etapes
            if cle == 'modele_diffusion' and modele.get('profil_rapide') and r['etapes'] == REGLAGES_DEFAUT['etapes']:
                r.update(etapes=8, cfg=1.0, methode='euler', sigmas=SIGMAS_RAPIDE)
    if change:
        DONNEES.mkdir(exist_ok=True)
        FICHIER_REGLAGES.write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding='utf-8')


def telecharger_modele(modele):
    """Telecharge un modele dans models/ en reprenant un telechargement interrompu, puis verifie son empreinte."""
    suivi = telechargements_modeles[modele['id']]
    final = MODELES / modele['fichier']
    partiel = MODELES / (modele['fichier'] + '.partiel')
    try:
        MODELES.mkdir(parents=True, exist_ok=True)
        deja = partiel.stat().st_size if partiel.exists() else 0
        if deja > modele['taille']:
            partiel.unlink()
            deja = 0
        with verrou_modeles:
            suivi['fait'] = deja
        libre = shutil.disk_usage(MODELES).free
        if libre < modele['taille'] - deja + 200 * 1024 * 1024:
            raise RuntimeError(f'Pas assez de place sur le disque : il faut {(modele["taille"] - deja) / 1e9:.1f} Go libres.')
        for essai in range(ESSAIS):
            deja = partiel.stat().st_size if partiel.exists() else 0
            en_tetes = {'User-Agent': f'Prisme/{VERSION}'}
            if deja:
                en_tetes['Range'] = f'bytes={deja}-'
            try:
                with urllib.request.urlopen(urllib.request.Request(modele['url'], headers=en_tetes), context=contexte_ssl(),
                                            timeout=60) as reponse:
                    # Un serveur qui ne reprend pas renvoie tout le fichier : on recommence du debut
                    if deja and reponse.status != 206:
                        deja = 0
                    with verrou_modeles:
                        suivi['fait'] = deja
                    recu = 0
                    with open(partiel, 'ab' if deja else 'wb') as fichier:
                        while bloc := reponse.read(1024 * 1024):
                            if suivi.get('annule'):
                                raise InterruptedError
                            fichier.write(bloc)
                            recu += len(bloc)
                            with verrou_modeles:
                                suivi['fait'] += len(bloc)
                    verifier_reception(reponse, recu)
                break
            except InterruptedError:
                raise
            except Exception as e:
                if not erreur_passagere(e):
                    raise erreur_lisible(e, modele['url']) if isinstance(e, urllib.error.HTTPError) else e
                if essai == ESSAIS - 1:
                    raise erreur_lisible(e, modele['url'])
                time.sleep(min(PAUSE_ESSAI * 2 ** essai, 20))
        with verrou_modeles:
            suivi['phase'] = 'verification'
        if partiel.stat().st_size != modele['taille'] or empreinte_fichier(partiel) != modele['sha256']:
            partiel.unlink(missing_ok=True)
            raise RuntimeError('Le fichier reçu ne correspond pas au modèle attendu (empreinte différente). Réessaie.')
        partiel.replace(final)
        utiliser_modele(modele)
        with verrou_modeles:
            suivi['phase'] = 'termine'
    except InterruptedError:
        # Le morceau deja recu est garde : le prochain telechargement reprend a cet endroit
        with verrou_modeles:
            suivi.update(phase='annule')
    except Exception as e:
        with verrou_modeles:
            suivi.update(phase='erreur', erreur=str(e) if isinstance(e, RuntimeError) else f'Téléchargement impossible : {e}')


def traiter_file_modeles():
    """Telecharge les modeles demandes l'un apres l'autre."""
    global travailleur_modeles
    while True:
        with verrou_modeles:
            if not file_modeles:
                travailleur_modeles = None
                return
            ident = file_modeles.popleft()
            suivi = telechargements_modeles[ident]
            if suivi.get('annule'):
                suivi['phase'] = 'annule'
                continue
            suivi['phase'] = 'telechargement'
        telecharger_modele(MODELES_PAR_ID[ident])


def demander_modele(ident):
    global travailleur_modeles
    modele = MODELES_PAR_ID[ident]
    with verrou_modeles:
        if telechargements_modeles.get(ident, {}).get('phase') in ('attente', 'telechargement', 'verification'):
            return
        telechargements_modeles[ident] = {'phase': 'attente', 'fait': 0, 'total': modele['taille'], 'erreur': None}
        file_modeles.append(ident)
        if travailleur_modeles is None:
            travailleur_modeles = threading.Thread(target=traiter_file_modeles, daemon=True)
            travailleur_modeles.start()


def etat_modeles_conseilles():
    with verrou_modeles:
        machine = profil_machine()
        modeles = [{k: m[k] for k in ('id', 'role', 'titre', 'detail', 'fichier', 'taille')}
                   | {'conseille': machine['profil'] in m['pour'], 'present': (MODELES / m['fichier']).is_file(),
                      'reprise': (MODELES / (m['fichier'] + '.partiel')).is_file(),
                      'telechargement': dict(telechargements_modeles[m['id']]) if m['id'] in telechargements_modeles else None}
                   for m in MODELES_CONSEILLES]
    MODELES.mkdir(parents=True, exist_ok=True)
    return {'modeles': modeles, 'libre': shutil.disk_usage(MODELES).free, 'machine': machine}


# Avis de nouvelle version : le numero de la derniere version publiee sur GitHub, lu une fois au lancement
PAGE_VERSIONS = 'https://github.com/d3Ita/prisme/releases/latest'
mise_a_jour = {}


def numero_version(texte):
    return tuple(int(x) for x in re.findall(r'\d+', texte)[:3])


# Fichier de la release a telecharger pour ce systeme, et seule origine acceptee pour la mise a jour
FICHIER_MAJ = {'windows': 'Prisme.exe', 'mac': 'Prisme-macOS-arm64.zip', 'linux': 'Prisme-Linux-x64.tar.gz'}[SYSTEME]
ORIGINE_MAJ = 'https://github.com/d3Ita/prisme/releases/download/'
verrou_maj = threading.Lock()


def lire_release(donnees):
    """Version et fichier a telecharger d'apres la reponse de GitHub ; le fichier n'est retenu que s'il vient
    des releases de Prisme et qu'il a une empreinte SHA-256."""
    version = str(donnees.get('tag_name', '')).lstrip('v')
    fichier = None
    for a in donnees.get('assets') or []:
        url, empreinte = str(a.get('browser_download_url', '')), str(a.get('digest') or '')
        if a.get('name') == FICHIER_MAJ and url.startswith(ORIGINE_MAJ) and re.fullmatch(r'sha256:[0-9a-f]{64}', empreinte):
            fichier = {'url': url, 'taille': int(a['size']), 'sha256': empreinte[7:]}
    return version, fichier


def verifier_mise_a_jour():
    try:
        requete = requete_github('https://api.github.com/repos/d3Ita/prisme/releases/latest', Accept='application/vnd.github+json')
        with urllib.request.urlopen(requete, context=contexte_ssl(), timeout=8) as reponse:
            version, fichier = lire_release(json.load(reponse))
        if numero_version(version) > numero_version(VERSION):
            # La mise a jour en un clic ne vaut que pour le programme construit, pas pour le script Python
            mise_a_jour.update(version=version, url=PAGE_VERSIONS, fichier=fichier, auto=bool(EXE and fichier))
    except Exception:
        pass


def etat_mise_a_jour():
    with verrou_maj:
        if not mise_a_jour:
            return None
        return {k: mise_a_jour.get(k) for k in ('version', 'url', 'auto')} | \
            {'installation': dict(mise_a_jour['installation']) if mise_a_jour.get('installation') else None}


def programme_actuel():
    """Ce qu'il faut remplacer : l'exe (Windows, Linux) ou le paquet Prisme.app (Mac)."""
    exe = Path(sys.executable).resolve()
    return exe.parents[2] if MAC else exe


def script_remplacement(nouveau, cible, pids):
    """Script qui attend la fin de Prisme, met le nouveau programme a sa place et le relance sans ouvrir de fenetre
    (la fenetre deja ouverte se recharge toute seule)."""
    if WINDOWS:
        lignes = ['@echo off']
        for i, pid in enumerate(pids):
            lignes += [f':attente{i}', f'tasklist /FI "PID eq {pid}" /NH | find " {pid} " >nul && (ping -n 2 127.0.0.1 >nul & goto attente{i})']
        lignes += ['set n=0', ':deplacer', f'move /y "{nouveau}" "{cible}" >nul 2>&1', 'if not errorlevel 1 goto lancer',
                   'set /a n+=1', 'if %n% geq 30 goto lancer', 'ping -n 2 127.0.0.1 >nul', 'goto deplacer',
                   ':lancer', f'start "" "{cible}" --sans-fenetre', '(goto) 2>nul & del "%~f0"']
        return '\r\n'.join(lignes) + '\r\n'
    n, c = shlex.quote(str(nouveau)), shlex.quote(str(cible))
    attente = ' || '.join(f'kill -0 {pid} 2>/dev/null' for pid in pids)
    lignes = ['#!/bin/sh', f'while {attente}; do sleep 1; done']
    if MAC:
        ancien = shlex.quote(str(cible) + '.ancien')
        lignes += [f'rm -rf {ancien}', f'if mv {c} {ancien} && mv {n} {c}; then rm -rf {ancien}; else mv {ancien} {c} 2>/dev/null; fi',
                   f'rm -rf {shlex.quote(str(Path(nouveau).parent))}', f'open {c} --args --sans-fenetre']
    else:
        lignes += [f'mv -f {n} {c}', f'chmod 755 {c}', f'nohup {c} --sans-fenetre >/dev/null 2>&1 &']
    lignes.append('rm -f "$0"')
    return '\n'.join(lignes) + '\n'


def installer_mise_a_jour():
    suivi = mise_a_jour['installation']

    def avancer(octets):
        with verrou_maj:
            suivi['fait'] += octets

    try:
        fichier, cible = mise_a_jour['fichier'], programme_actuel()
        dossier = cible.parent
        if not os.access(dossier, os.W_OK):
            raise RuntimeError('Prisme ne peut pas se remplacer à cet endroit : télécharge la nouvelle version à la main.')
        telechargement = dossier / f'.prisme-maj-{FICHIER_MAJ}'
        telecharger(fichier, telechargement, avancer)
        with verrou_maj:
            suivi['phase'] = 'installation'
        if WINDOWS:
            nouveau = telechargement
        elif MAC:
            extrait = dossier / '.prisme-maj-app'
            shutil.rmtree(extrait, ignore_errors=True)
            # ditto garde les liens et les droits du paquet .app
            subprocess.run(['ditto', '-x', '-k', str(telechargement), str(extrait)], check=True, capture_output=True)
            telechargement.unlink()
            nouveau = extrait / 'Prisme.app'
            if not (nouveau / 'Contents' / 'MacOS' / 'Prisme').is_file():
                raise RuntimeError('La nouvelle version est incomplète.')
        else:
            nouveau = dossier / '.prisme-maj-programme'
            with tarfile.open(telechargement) as archive:
                nouveau.write_bytes(archive.extractfile(archive.getmember('prisme')).read())
            nouveau.chmod(0o755)
            telechargement.unlink()
        # Sous Windows et Linux, l'exe tourne dans deux processus (lanceur et Python) : on attend les deux
        pids = [os.getpid()] + ([] if MAC else [os.getppid()])
        script = Path(tempfile.gettempdir()) / f'prisme-maj-{os.getpid()}.{"cmd" if WINDOWS else "sh"}'
        script.write_text(script_remplacement(nouveau, cible, pids), encoding='utf-8', newline='')
        # Sans cela, le nouveau Prisme heriterait des variables internes de l'exe actuel et se croirait son sous-processus
        environnement = {k: v for k, v in os.environ.items() if not k.startswith(('_PYI_', '_MEIPASS'))}
        environnement['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
        if WINDOWS:
            options = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            try:
                # Hors du groupe de processus de Prisme, pour que le script survive a sa fermeture
                subprocess.Popen(['cmd', '/c', str(script)], env=environnement,
                                 creationflags=options | subprocess.CREATE_BREAKAWAY_FROM_JOB)
            except OSError:
                subprocess.Popen(['cmd', '/c', str(script)], env=environnement, creationflags=options)
        else:
            subprocess.Popen(['/bin/sh', str(script)], start_new_session=True, env=environnement,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with verrou_maj:
            suivi['phase'] = 'redemarrage'
        # Laisse a la fenetre le temps de voir la phase, puis s'arrete : le script prend le relais
        threading.Timer(1.5, arreter).start()
    except Exception as e:
        with verrou_maj:
            suivi.update(phase='erreur', erreur=str(e) if isinstance(e, RuntimeError) else f'Mise à jour impossible : {e}')


def lister_loras():
    if not LORAS.exists():
        return []
    return sorted(({'nom': f.relative_to(LORAS).as_posix(), 'taille': f.stat().st_size}
                   for f in LORAS.rglob('*') if f.is_file() and f.suffix.lower() in EXTENSIONS_LORA),
                  key=lambda m: m['nom'].lower())


def loras_actifs(r):
    return [l for l in r['loras'] if l['actif'] and (LORAS / l['nom']).is_file()]


def code_acces():
    """Code demande aux appareils du reseau ; garde le meme pour que le lien du telephone reste valable."""
    DONNEES.mkdir(exist_ok=True)
    if FICHIER_CODE.exists():
        code = FICHIER_CODE.read_text(encoding='utf-8-sig').strip()
        # Les codes courts des premieres versions se devinaient trop vite : on les remplace
        if len(code) >= 20:
            return code
    code = secrets.token_urlsafe(16)
    FICHIER_CODE.write_text(code, encoding='utf-8')
    return code


CODE = code_acces()


def resumer_appareil(agent):
    """Nom lisible de l'appareil, d'apres son navigateur, pour reconnaitre la demande sur le PC."""
    for motif, nom in (('iPhone', 'iPhone'), ('iPad', 'iPad'), ('Android', 'Android'), ('Windows', 'PC Windows'),
                       ('Macintosh', 'Mac'), ('Linux', 'Linux')):
        if motif in agent:
            return nom
    return 'Appareil inconnu'


def adresse_reseau():
    # Aucun paquet n'est envoye : la connexion UDP sert seulement a choisir l'interface reseau
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(('192.168.0.1', 80))
            return s.getsockname()[0]
        except OSError:
            return '127.0.0.1'


def arguments(r, prompt, largeur, hauteur, seed, source, sortie):
    edition = []
    if source:
        edition = ['--llm_vision', str(MODELES / r['modele_vision']), '-r', str(source)]
    options = (['--sigmas', r['sigmas']] if r['sigmas'] else []) \
        + (['--diffusion-fa'] if r['flash_attention'] else []) \
        + (['--offload-to-cpu'] if r['dechargement_cpu'] else []) \
        + (['--vae-tiling'] if r['vae_tuiles'] else [])
    return edition + [
        '--diffusion-model', str(MODELES / r['modele_diffusion']),
        '--llm', str(MODELES / r['modele_texte']),
        '--vae', str(MODELES / r['vae']),
        '-p', prompt + ''.join(f'<lora:{Path(l["nom"]).with_suffix("").as_posix()}:{l["force"]}>' for l in loras_actifs(r)),
        '--steps', str(r['etapes']), '--cfg-scale', str(r['cfg']), '--sampling-method', r['methode'],
        '-W', str(largeur), '-H', str(hauteur), '--seed', str(seed), '--threads', str(fils_calcul()),
    ] + options + (['--lora-model-dir', str(LORAS)] if loras_actifs(r) else []) + ['-o', str(sortie)]


def modeles_manquants(r, avec_vision):
    cles = ['modele_diffusion', 'modele_texte', 'vae'] + (['modele_vision'] if avec_vision else [])
    return [r[c] or c for c in cles if not r[c] or not (MODELES / r[c]).is_file()]


def nouveau_chemin():
    IMAGES.mkdir(exist_ok=True)
    base = 'image_' + datetime.now().strftime('%Y%m%d_%H%M%S')
    chemin = IMAGES / (base + '.png')
    n = 2
    while chemin.exists():
        chemin = IMAGES / f'{base}_{n}.png'
        n += 1
    return chemin


def lire_infos(chemin):
    """Lit taille, prompt et seed dans les metadonnees PNG ecrites par sd-cli."""
    mtime = chemin.stat().st_mtime
    connu = cache_infos.get(chemin.name)
    if connu and connu[0] == mtime:
        return connu[1]

    infos = {'nom': chemin.name, 'prompt': '', 'seed': None, 'loras': [], 'largeur': 0, 'hauteur': 0,
             'date': datetime.fromtimestamp(mtime).isoformat(timespec='seconds'), 'version': int(mtime)}
    try:
        with open(chemin, 'rb') as f:
            if f.read(8) == b'\x89PNG\r\n\x1a\n':
                while True:
                    entete = f.read(8)
                    if len(entete) < 8:
                        break
                    taille, genre = int.from_bytes(entete[:4], 'big'), entete[4:]
                    if genre == b'IDAT':
                        break
                    donnees = f.read(taille)
                    f.read(4)
                    if genre == b'IHDR':
                        infos['largeur'] = int.from_bytes(donnees[:4], 'big')
                        infos['hauteur'] = int.from_bytes(donnees[4:8], 'big')
                    elif genre == b'tEXt' and donnees.startswith(b'parameters\x00'):
                        brut = donnees[len(b'parameters\x00'):]
                        try:
                            texte = brut.decode('utf-8')
                        except UnicodeDecodeError:
                            texte = brut.decode('latin-1')
                        prompt = texte.split('\nSteps:')[0]
                        infos['loras'] = [f'{nom} ({force})' for nom, force in BALISE_LORA.findall(prompt)]
                        infos['prompt'] = BALISE_LORA.sub('', prompt).strip()
                        seed = re.search(r'Seed: (-?\d+)', texte)
                        if seed:
                            infos['seed'] = int(seed.group(1))
    except OSError:
        pass
    cache_infos[chemin.name] = (mtime, infos)
    return infos


def lister_images():
    if not IMAGES.exists():
        return []
    fichiers = sorted(IMAGES.glob('*.png'), key=lambda p: p.stat().st_mtime, reverse=True)
    return [lire_infos(p) for p in fichiers]


def generer(params):
    global processus
    source_temp = None
    r = params['reglages']
    try:
        source = None
        if params.get('source_nom'):
            nom = params['source_nom']
            if NOM_IMAGE.match(nom) and (IMAGES / nom).exists():
                source = IMAGES / nom
        elif params.get('source_data'):
            entete, _, donnees = params['source_data'].partition(',')
            fd, chemin = tempfile.mkstemp(prefix='prisme_source_', suffix='.png')
            with os.fdopen(fd, 'wb') as f:
                f.write(base64.b64decode(donnees))
            source = source_temp = Path(chemin)

        manquants = modeles_manquants(r, bool(source))
        if manquants:
            raise RuntimeError('Modèle introuvable dans le dossier models : ' + ', '.join(manquants) + '. Vérifie les réglages.')

        for i in range(params['nombre']):
            if annule:
                break
            seed = params['seed'] + i
            sortie = nouveau_chemin()
            with verrou:
                etat.update(phase='chargement', etape=0, index=i + 1, seed=seed, debut_image=time.time())
            journal = deque(maxlen=80)
            processus = lancer_moteur(
                [str(SD_CLI)] + arguments(r, params['prompt'], params['largeur'], params['hauteur'], seed, source, sortie),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=str(RACINE))

            reste = ''
            while True:
                bloc = processus.stdout.read1(4096)
                if not bloc:
                    break
                lignes = re.split(r'[\r\n]+', reste + bloc.decode('utf-8', 'replace'))
                reste = lignes.pop()
                for ligne in lignes:
                    if ligne.strip():
                        journal.append(ligne)
                    pas = PAS.findall(ligne)
                    if pas:
                        fait, total = map(int, pas[-1])
                        with verrou:
                            if total == r['etapes'] and etat['phase'] != 'finalisation':
                                etat.update(phase='finalisation' if fait >= total else 'dessin', etape=fait)
                            elif etat['phase'] == 'dessin':
                                etat['phase'] = 'finalisation'
            code = processus.wait()

            if annule:
                sortie.unlink(missing_ok=True)
                break
            if code != 0 or not sortie.exists():
                erreurs = [l for l in journal if re.search(r'^\[E\]|error|out of memory', l, re.I)]
                with verrou:
                    etat['erreur'] = '\n'.join(erreurs[-3:]) or f'sd-cli s\'est arrete (code {code}).'
                break
            with verrou:
                etat['resultats'].append(sortie.name)
    except Exception as e:
        with verrou:
            etat['erreur'] = str(e)
    finally:
        processus = None
        if source_temp:
            source_temp.unlink(missing_ok=True)
        with verrou:
            etat['occupe'] = False
            etat['phase'] = 'annule' if annule else ('erreur' if etat.get('erreur') else 'termine')
            etat['fin'] = time.time()


# Permet d'installer Prisme comme une application (ecran d'accueil du telephone, fenetre du PC) avec son logo
MANIFESTE = json.dumps({
    'name': 'Prisme', 'short_name': 'Prisme', 'start_url': '/', 'display': 'standalone',
    'background_color': '#f6f4ef', 'theme_color': '#f6f4ef', 'lang': 'fr',
    'icons': [{'src': '/logo.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any'}],
}, ensure_ascii=False).encode('utf-8')

PAGE_CONNEXION = '''<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Prisme</title><link rel="icon" href="/logo.png"><meta name="theme-color" content="#f6f4ef">
<style>
:root { --fond: #f6f4ef; --carte: #fff; --bordure: #e7e3da; --texte: #1f2430; --texte-2: #575d6b; --accent: #2f5bea; --sur-accent: #fff; color-scheme: light; }
@media (prefers-color-scheme: dark) { :root { --fond: #1b1a18; --carte: #242320; --bordure: #383632; --texte: #f1eee8; --texte-2: #bdb8ae; --accent: #f07a5a; --sur-accent: #2a140d; color-scheme: dark; } }
body { margin: 0; min-height: 100vh; min-height: 100dvh; display: flex; align-items: center; justify-content: center; box-sizing: border-box; padding: 20px;
  background: var(--fond); color: var(--texte); font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; text-align: center; }
.carte { width: 100%; max-width: 360px; padding: 28px 22px; border-radius: 22px; background: var(--carte); border: 1px solid var(--bordure); overflow-wrap: anywhere; }
img { border-radius: 18px; }
h1 { font-size: 22px; margin: 16px 0 6px; }
#etat { color: var(--texte-2); margin: 0 0 18px; }
#code { font: 600 40px ui-monospace, Consolas, monospace; letter-spacing: 10px; color: var(--accent); min-height: 48px; }
button { margin-top: 18px; height: 46px; padding: 0 22px; border: 0; border-radius: 12px; background: var(--accent); color: var(--sur-accent); font: 600 16px system-ui, sans-serif; }
</style>
<body>
<div class="carte">
  <img src="/logo.png" alt="" width="80" height="80">
  <h1>Connexion à Prisme</h1>
  <p id="etat">Envoi de la demande…</p>
  <div id="code"></div>
  <button id="relancer" hidden>Redemander l'accès</button>
</div>
<script>
const etat = document.getElementById('etat'), code = document.getElementById('code'), relancer = document.getElementById('relancer');
function echec(texte) { etat.textContent = texte; code.textContent = ''; relancer.hidden = false; }
async function demander() {
  relancer.hidden = true; etat.textContent = 'Envoi de la demande…';
  try {
    const r = await fetch('/acces/demander', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    const d = await r.json();
    if (!r.ok) return echec(d.erreur || 'Demande impossible.');
    code.textContent = d.code;
    etat.textContent = 'Sur le PC, clique sur « Autoriser » dans Prisme, en vérifiant que ce code est le même.';
    suivre(d.id);
  } catch { echec('Prisme ne répond pas.'); }
}
function suivre(id) {
  setTimeout(async () => {
    try {
      const d = await (await fetch('/acces/etat?id=' + encodeURIComponent(id))).json();
      if (d.etat === 'acceptee') { etat.textContent = 'Accès autorisé.'; location.replace('/'); return; }
      if (d.etat === 'refusee') return echec('Accès refusé sur le PC.');
      if (d.etat === 'expiree') return echec('La demande a expiré : personne ne l\\'a acceptée sur le PC.');
    } catch {}
    suivre(id);
  }, 1500);
}
relancer.onclick = demander;
demander();
</script>'''

# La meme page en anglais, pour les telephones dans une autre langue
PAGE_CONNEXION_EN = PAGE_CONNEXION
for _fr, _en in (('lang="fr"', 'lang="en"'), ('Connexion à Prisme', 'Connect to Prisme'), ('Envoi de la demande…', 'Sending the request…'),
                 ("Redemander l'accès", 'Ask again'), ('Demande impossible.', 'Request failed.'),
                 ('Sur le PC, clique sur « Autoriser » dans Prisme, en vérifiant que ce code est le même.',
                  'On the PC, click “Approve” in Prisme after checking that this code matches.'),
                 ('Prisme ne répond pas.', 'Prisme is not responding.'), ('Accès autorisé.', 'Access approved.'),
                 ('Accès refusé sur le PC.', 'Access refused on the PC.'),
                 ("La demande a expiré : personne ne l\\'a acceptée sur le PC.", 'The request expired: nobody approved it on the PC.')):
    assert _fr in PAGE_CONNEXION_EN, _fr
    PAGE_CONNEXION_EN = PAGE_CONNEXION_EN.replace(_fr, _en)


class Gestionnaire(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def est_local(self):
        return self.client_address[0] in ('127.0.0.1', '::1')

    def hote_autorise(self):
        """Contre le DNS rebinding : seules une adresse IP ou localhost, sur le bon port, sont acceptees."""
        m = re.match(r'^(\[[0-9a-fA-F:.]+\]|[^:\[\]]+):(\d+)$', self.headers.get('Host', ''))
        if not m or int(m.group(2)) != PORT:
            return False
        nom = m.group(1).strip('[]')
        if nom.lower() == 'localhost':
            return True
        try:
            ipaddress.ip_address(nom)
            return True
        except ValueError:
            return False

    def origine_autorisee(self):
        """Contre les requetes envoyees par d'autres sites : l'origine, si presente, doit etre Prisme lui-meme."""
        origine = self.headers.get('Origin')
        return origine is None or urlparse(origine).netloc == self.headers.get('Host')

    def bloque(self):
        if self.est_local():
            return False
        maintenant = time.time()
        with verrou_echecs:
            recents = [t for t in echecs.get(self.client_address[0], []) if maintenant - t < FENETRE_ESSAIS]
            echecs[self.client_address[0]] = recents
            return len(recents) >= ESSAIS_MAX

    def noter_echec(self):
        with verrou_echecs:
            echecs.setdefault(self.client_address[0], []).append(time.time())

    def controler(self):
        """Renvoie False (apres avoir repondu) si la requete doit etre rejetee."""
        if not self.hote_autorise():
            self.envoyer(403, {'erreur': 'Adresse non autorisée.'})
            return False
        if self.bloque():
            self.envoyer(429, {'erreur': 'Trop de codes faux : réessaie dans quelques minutes.'})
            return False
        return True

    def autorise(self):
        if self.est_local():
            return True
        cookie = SimpleCookie(self.headers.get('Cookie', ''))
        valeur = cookie['prisme_acces'].value if 'prisme_acces' in cookie else ''
        if secrets.compare_digest(valeur, CODE):
            return True
        if valeur:
            self.noter_echec()
        return False

    def refuser(self):
        if urlparse(self.path).path.startswith('/api/'):
            self.envoyer(401, {'erreur': 'Accès refusé : reconnecte-toi depuis l\'adresse de Prisme.'})
        else:
            page = PAGE_CONNEXION if self.langue_francaise() else PAGE_CONNEXION_EN
            self.envoyer(401, page.encode('utf-8'), 'text/html; charset=utf-8')

    def langue_francaise(self):
        """Langue preferee du navigateur : la page de connexion est en anglais sauf pour les navigateurs en francais."""
        preferee = self.headers.get('Accept-Language', 'fr').split(',')[0].strip().lower()
        return not preferee or preferee.startswith('fr')

    def noter_contact_local(self):
        global dernier_contact_local, fermeture_demandee
        if self.est_local():
            dernier_contact_local = time.time()
            fermeture_demandee = None

    def deposer_cookie(self):
        self.send_header('Set-Cookie', f'prisme_acces={CODE}; Max-Age=31536000; Path=/; HttpOnly; SameSite=Lax')

    def demander_acces(self):
        """Un appareil sans code demande l'acces : le PC devra l'autoriser."""
        ip = self.client_address[0]
        maintenant = time.time()
        with verrou_demandes:
            for cle in [c for c, d in demandes.items() if maintenant - d['cree'] > DUREE_DEMANDE]:
                del demandes[cle]
            if sum(d['ip'] == ip for d in demandes.values()) >= DEMANDES_MAX_PAR_APPAREIL:
                return self.envoyer(429, {'erreur': 'Trop de demandes en attente : accepte-les ou attends deux minutes.'})
            ident = secrets.token_urlsafe(16)
            demandes[ident] = {'ip': ip, 'appareil': resumer_appareil(self.headers.get('User-Agent', '')),
                               'code': f'{secrets.randbelow(10000):04d}', 'etat': 'attente', 'cree': maintenant}
            self.envoyer(200, {'id': ident, 'code': demandes[ident]['code']})

    def etat_demande(self, ident):
        """L'appareil suit sa demande ; une fois acceptee, il recoit le cookie d'acces."""
        with verrou_demandes:
            demande = demandes.get(ident)
            # Une demande ne peut etre suivie que depuis l'appareil qui l'a faite
            if not demande or demande['ip'] != self.client_address[0] or time.time() - demande['cree'] > DUREE_DEMANDE:
                return self.envoyer(200, {'etat': 'expiree'})
            if demande['etat'] == 'attente':
                return self.envoyer(200, {'etat': 'attente'})
            del demandes[ident]
        corps = json.dumps({'etat': demande['etat']}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(corps)))
        self.send_header('Cache-Control', 'no-store')
        if demande['etat'] == 'acceptee':
            self.deposer_cookie()
        self.end_headers()
        self.wfile.write(corps)

    def envoyer(self, code, corps, type_contenu='application/json; charset=utf-8', cache=False):
        if not isinstance(corps, bytes):
            corps = json.dumps(corps, ensure_ascii=False).encode('utf-8')
        # Une requete refusee avant d'avoir lu son corps : on le lit quand meme, sinon Windows coupe la connexion
        # brutalement et l'appareil ne recoit pas la reponse
        if self.command == 'POST' and not getattr(self, 'corps_lu', True):
            taille = int(self.headers.get('Content-Length') or 0)
            if 0 < taille <= TAILLE_MAX_REQUETE:
                self.rfile.read(taille)
            self.corps_lu = True
        self.send_response(code)
        self.send_header('Content-Type', type_contenu)
        self.send_header('Content-Length', str(len(corps)))
        self.send_header('Cache-Control', 'max-age=31536000, immutable' if cache else 'no-store')
        self.end_headers()
        self.wfile.write(corps)

    def lire_json(self):
        taille = int(self.headers.get('Content-Length') or 0)
        if taille > TAILLE_MAX_REQUETE:
            raise ValueError('requete trop grande')
        self.corps_lu = True
        return json.loads(self.rfile.read(taille) or b'{}')

    def do_GET(self):
        global dernier_contact
        if not self.controler():
            return
        url = urlparse(self.path)
        chemin = url.path

        # Le lien du QR code depose le code dans un cookie, puis recharge l'adresse sans le code
        code = parse_qs(url.query).get('code', [''])[0]
        if code:
            if not secrets.compare_digest(code, CODE):
                self.noter_echec()
                return self.refuser()
            self.send_response(302)
            self.deposer_cookie()
            self.send_header('Location', '/')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        # Logo et manifeste sont publics : le navigateur les demande parfois sans cookie, et ils ne revelent rien
        if chemin == '/logo.png':
            return self.envoyer(200, (RESSOURCES / 'logo.png').read_bytes(), 'image/png', cache=True)
        if chemin == '/manifest.webmanifest':
            return self.envoyer(200, MANIFESTE, 'application/manifest+json; charset=utf-8')
        if chemin == '/acces/etat':
            return self.etat_demande(parse_qs(url.query).get('id', [''])[0])
        if not self.autorise():
            return self.refuser()
        dernier_contact = time.time()
        self.noter_contact_local()

        if chemin in ('/', '/index.html'):
            self.envoyer(200, (RESSOURCES / 'index.html').read_bytes(), 'text/html; charset=utf-8')
        elif chemin == '/api/reglages':
            if not self.est_local():
                return self.envoyer(403, {'erreur': 'Disponible seulement sur le PC.'})
            self.envoyer(200, {'reglages': lire_reglages(), 'defauts': REGLAGES_DEFAUT, 'modeles': lister_modeles(),
                               'methodes': METHODES, 'dossier': str(MODELES),
                               'loras': lister_loras(), 'dossier_loras': str(LORAS)})
        elif chemin == '/api/images':
            self.envoyer(200, lister_images())
        elif chemin == '/api/modeles-conseilles':
            if not self.est_local():
                return self.envoyer(403, {'erreur': 'Disponible seulement sur le PC.'})
            self.envoyer(200, etat_modeles_conseilles())
        elif chemin == '/api/etat':
            with verrou:
                copie = dict(etat)
            debut = copie.get('debut')
            if debut:
                copie['ecoule'] = round((copie.get('fin') if not copie['occupe'] else time.time()) - debut, 1)
            copie['local'] = self.est_local()
            r = lire_reglages()
            copie['modele'] = r['modele_diffusion']
            copie['version'] = VERSION
            copie['problemes'] = problemes_configuration(r)
            copie['amelioration'] = {'modele': amelioration_active(r), 'auto': r['amelioration_auto']}
            copie['moteurs'] = etat_moteurs()
            if self.est_local():
                with verrou_demandes:
                    copie['demandes'] = [{'id': i, 'ip': d['ip'], 'appareil': d['appareil'], 'code': d['code']}
                                         for i, d in demandes.items()
                                         if d['etat'] == 'attente' and time.time() - d['cree'] <= DUREE_DEMANDE]
                copie['mise_a_jour'] = etat_mise_a_jour()
            copie['loras_actifs'] = [{'nom': Path(l['nom']).stem, 'force': l['force']} for l in loras_actifs(r)]
            self.envoyer(200, copie)
        elif chemin == '/api/ollama-modeles':
            if not self.est_local():
                return self.envoyer(403, {'erreur': 'Disponible seulement sur le PC.'})
            try:
                modeles = appel_ollama(lire_reglages(), '/api/tags').get('models', [])
                self.envoyer(200, {'modeles': [{'nom': m['name'], 'taille': m.get('size', 0)} for m in modeles]})
            except RuntimeError as e:
                self.envoyer(200, {'modeles': [], 'erreur': str(e)})
        elif chemin == '/api/acces':
            if not self.est_local():
                return self.envoyer(403, {'erreur': 'Disponible seulement sur le PC.'})
            adresse = f'http://{adresse_reseau()}:{PORT}'
            self.envoyer(200, {'adresse': adresse, 'lien': f'{adresse}/?code={CODE}', 'code': CODE, 'reseau': SERVEUR_RESEAU})
        elif chemin.startswith('/images/'):
            nom = unquote(chemin[len('/images/'):])
            fichier = IMAGES / nom
            if NOM_IMAGE.match(nom) and fichier.exists():
                self.envoyer(200, fichier.read_bytes(), 'image/png', cache=True)
            else:
                self.envoyer(404, {'erreur': 'Image introuvable'})
        else:
            self.envoyer(404, {'erreur': 'Introuvable'})

    def do_POST(self):
        self.corps_lu = False
        if not self.controler():
            return
        if not self.origine_autorisee():
            return self.envoyer(403, {'erreur': 'Requête venant d\'un autre site refusée.'})
        if self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
            return self.envoyer(415, {'erreur': 'Les requêtes doivent être en JSON.'})
        if urlparse(self.path).path == '/acces/demander':
            return self.demander_acces()
        if not self.autorise():
            return self.refuser()
        try:
            self.traiter_post(urlparse(self.path).path)
        except ValueError:
            self.envoyer(400, {'erreur': 'Données invalides.'})

    def traiter_post(self, chemin):
        global dernier_contact, annule, fermeture_demandee
        dernier_contact = time.time()
        if chemin in ('/api/quitter', '/api/fermeture'):
            if not self.est_local():
                return self.envoyer(403, {'erreur': 'Disponible seulement sur le PC.'})
            if chemin == '/api/fermeture':
                fermeture_demandee = time.time()
                return self.envoyer(200, {})
            self.envoyer(200, {})
            # La reponse part avant l'arret
            threading.Timer(0.3, arreter).start()
            return
        self.noter_contact_local()

        if chemin == '/api/generer':
            try:
                p = self.lire_json()
                prompt = str(p.get('prompt', '')).strip()
                largeur, hauteur = int(p.get('largeur') or 1024), int(p.get('hauteur') or 1024)
                nombre = max(1, min(4, int(p.get('nombre') or 1)))
                seed = p.get('seed')
                seed = random.randint(0, 2**31 - 1) if seed in (None, '') else int(seed)
            except (ValueError, TypeError, json.JSONDecodeError):
                return self.envoyer(400, {'erreur': 'Paramètres invalides.'})
            if not prompt:
                return self.envoyer(400, {'erreur': 'Écris d\'abord ce que tu veux obtenir.'})
            if not (256 <= largeur <= 2048 and 256 <= hauteur <= 2048) or largeur % 16 or hauteur % 16:
                return self.envoyer(400, {'erreur': 'Taille invalide : multiples de 16, entre 256 et 2048.'})

            r = lire_reglages()
            with verrou:
                if etat['occupe']:
                    return self.envoyer(409, {'erreur': 'Une génération est déjà en cours.'})
                if amelioration_en_cours.locked():
                    return self.envoyer(409, {'erreur': 'Attends la fin de l\'amélioration de la description.'})
                annule = False
                etat.clear()
                etat.update(occupe=True, phase='chargement', etape=0, total=r['etapes'], index=1, nombre=nombre,
                            seed=seed, seed_base=seed, debut=time.time(), resultats=[], erreur=None,
                            largeur=largeur, hauteur=hauteur, prompt=prompt)
            params = dict(prompt=prompt, largeur=largeur, hauteur=hauteur, nombre=nombre, seed=seed, reglages=r,
                          source_nom=p.get('source_nom'), source_data=p.get('source_data'))
            threading.Thread(target=generer, args=(params,), daemon=True).start()
            self.envoyer(200, {'seed': seed})

        elif chemin == '/api/ameliorer':
            r = lire_reglages()
            donnees = self.lire_json()
            texte = str(donnees.get('prompt', '')).strip()
            image = None
            nom = str(donnees.get('source_nom') or '')
            if nom:
                if not NOM_IMAGE.match(nom) or not (IMAGES / nom).exists():
                    return self.envoyer(404, {'erreur': 'Image de départ introuvable.'})
                image = (IMAGES / nom).read_bytes()
            elif donnees.get('source_data'):
                image = base64.b64decode(str(donnees['source_data']).partition(',')[2])
            if not texte:
                return self.envoyer(400, {'erreur': 'Écris d\'abord une description à améliorer.'})
            if not amelioration_active(r):
                return self.envoyer(400, {'erreur': 'Choisis un modèle d\'amélioration dans les Réglages.'})
            # Le modele de langage et la generation ne tiennent pas ensemble en memoire video
            if etat.get('occupe') or not amelioration_en_cours.acquire(blocking=False):
                return self.envoyer(409, {'erreur': 'Attends la fin du calcul en cours.'})
            try:
                self.envoyer(200, {'prompt': ameliorer_description(r, texte, image), 'modification': image is not None})
            except RuntimeError as e:
                self.envoyer(502, {'erreur': str(e)})
            finally:
                amelioration_en_cours.release()

        elif chemin == '/api/repondre-demande':
            if not self.est_local():
                return self.envoyer(403, {'erreur': 'Disponible seulement sur le PC.'})
            donnees = self.lire_json()
            with verrou_demandes:
                demande = demandes.get(str(donnees.get('id') or ''))
                if not demande or demande['etat'] != 'attente':
                    return self.envoyer(404, {'erreur': 'Cette demande a expiré.'})
                demande['etat'] = 'acceptee' if donnees.get('accepter') else 'refusee'
            if demande['etat'] == 'refusee':
                # Un refus compte comme un code faux : un appareil insistant finit bloque
                with verrou_echecs:
                    echecs.setdefault(demande['ip'], []).append(time.time())
            self.envoyer(200, {'etat': demande['etat']})

        elif chemin == '/api/mettre-a-jour':
            if not self.est_local():
                return self.envoyer(403, {'erreur': 'Disponible seulement sur le PC.'})
            with verrou:
                occupe = etat.get('occupe') or amelioration_en_cours.locked()
            if occupe:
                return self.envoyer(409, {'erreur': 'Attends la fin de la création en cours.'})
            with verrou_maj:
                if not mise_a_jour.get('auto'):
                    return self.envoyer(400, {'erreur': 'Aucune mise à jour automatique disponible.'})
                if (mise_a_jour.get('installation') or {}).get('phase') in ('telechargement', 'installation', 'redemarrage'):
                    return self.envoyer(409, {'erreur': 'Mise à jour déjà en cours.'})
                mise_a_jour['installation'] = {'phase': 'telechargement', 'fait': 0, 'total': mise_a_jour['fichier']['taille'],
                                               'erreur': None}
            threading.Thread(target=installer_mise_a_jour, daemon=True).start()
            self.envoyer(200, {})

        elif chemin in ('/api/telecharger-modele', '/api/annuler-modele'):
            if not self.est_local():
                return self.envoyer(403, {'erreur': 'Disponible seulement sur le PC.'})
            ident = str(self.lire_json().get('id') or '')
            if ident not in MODELES_PAR_ID:
                return self.envoyer(400, {'erreur': 'Modèle inconnu.'})
            if chemin == '/api/telecharger-modele':
                demander_modele(ident)
            else:
                with verrou_modeles:
                    if ident in telechargements_modeles:
                        telechargements_modeles[ident]['annule'] = True
            self.envoyer(200, {})

        elif chemin == '/api/installer-moteur':
            if not self.est_local():
                return self.envoyer(403, {'erreur': 'Disponible seulement sur le PC.'})
            nom = str(self.lire_json().get('moteur') or '')
            if nom not in MOTEURS:
                return self.envoyer(400, {'erreur': 'Moteur inconnu.'})
            with verrou_installations:
                if installations.get(nom, {}).get('phase') in ('telechargement', 'extraction'):
                    return self.envoyer(409, {'erreur': 'Installation déjà en cours.'})
                installations[nom] = {'phase': 'telechargement', 'fait': 0,
                                      'total': sum(a['taille'] for a in MOTEURS[nom]['archives']), 'erreur': None}
            threading.Thread(target=installer_moteur, args=(nom,), daemon=True).start()
            self.envoyer(200, {})

        elif chemin == '/api/supprimer':
            nom = str(self.lire_json().get('nom') or '')
            if not NOM_IMAGE.match(nom) or not (IMAGES / nom).exists():
                return self.envoyer(404, {'erreur': 'Image introuvable.'})
            if not mettre_a_la_corbeille(IMAGES / nom):
                return self.envoyer(500, {'erreur': 'Impossible de mettre l\'image à la corbeille.'})
            cache_infos.pop(nom, None)
            self.envoyer(200, {})

        elif chemin == '/api/annuler':
            annule = True
            if processus:
                try:
                    processus.kill()
                except OSError:
                    pass
            self.envoyer(200, {})

        elif chemin == '/api/reglages':
            if not self.est_local():
                return self.envoyer(403, {'erreur': 'Disponible seulement sur le PC.'})
            try:
                donnees = self.lire_json()
            except ValueError:
                return self.envoyer(400, {'erreur': 'Données invalides.'})
            r, erreur = valider_reglages(donnees)
            if erreur:
                return self.envoyer(400, {'erreur': erreur})
            DONNEES.mkdir(exist_ok=True)
            FICHIER_REGLAGES.write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding='utf-8')
            self.envoyer(200, {'reglages': r})

        elif chemin in ('/api/dossier-modeles', '/api/dossier-loras'):
            if not self.est_local():
                return self.envoyer(403, {'erreur': 'Disponible seulement sur le PC.'})
            dossier = LORAS if chemin.endswith('loras') else MODELES
            dossier.mkdir(parents=True, exist_ok=True)
            ouvrir_dossier(dossier)
            self.envoyer(200, {})

        elif chemin == '/api/dossier':
            if not self.est_local():
                return self.envoyer(403, {'erreur': 'Disponible seulement sur le PC.'})
            nom = str(self.lire_json().get('nom') or '')
            IMAGES.mkdir(exist_ok=True)
            ouvrir_dossier(IMAGES, IMAGES / nom if NOM_IMAGE.match(nom) and (IMAGES / nom).exists() else None)
            self.envoyer(200, {})
        else:
            self.envoyer(404, {'erreur': 'Introuvable'})


class Serveur(ThreadingHTTPServer):
    # Sous Windows, la reutilisation d'adresse laisserait deux serveurs ecouter le meme port. Ailleurs, elle
    # empeche seulement un port tout juste libere (TIME_WAIT, par exemple apres une mise a jour) de paraitre occupe
    allow_reuse_address = not WINDOWS

    def server_bind(self):
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def navigateur_application():
    """Navigateur capable d'ouvrir Prisme dans sa propre fenetre (Edge, Chrome, Chromium ou Brave)."""
    if WINDOWS:
        candidats = [Path(os.environ.get(v, '')) / s for v in ('ProgramFiles(x86)', 'ProgramFiles', 'LOCALAPPDATA')
                     for s in (r'Microsoft\Edge\Application\msedge.exe', r'Google\Chrome\Application\chrome.exe')]
    elif MAC:
        candidats = [Path('/Applications') / f'{nom}.app' / 'Contents' / 'MacOS' / nom
                     for nom in ('Google Chrome', 'Microsoft Edge', 'Chromium', 'Brave Browser')]
    else:
        candidats = [Path(c) for c in map(shutil.which, ('google-chrome', 'google-chrome-stable', 'chromium',
                                                         'chromium-browser', 'microsoft-edge', 'brave-browser')) if c]
    return next((c for c in candidats if c.is_file()), None)


def ouvrir_fenetre():
    adresse = f'http://127.0.0.1:{PORT}/'
    navigateur = navigateur_application()
    if navigateur:
        subprocess.Popen([str(navigateur), f'--app={adresse}', '--window-size=1440,920'])
    else:
        import webbrowser
        webbrowser.open(adresse)


def arreter():
    """Arrete Prisme et les moteurs qu'il a lances."""
    for moteur in (processus, processus_texte):
        if moteur and moteur.poll() is None:
            try:
                moteur.kill()
            except OSError:
                pass
    os._exit(0)


def doit_s_arreter(maintenant, reglages):
    """Vrai si le serveur doit s'arreter : inactivite trop longue, ou fenetre du PC fermee et pas rouverte."""
    if etat.get('occupe') or amelioration_en_cours.locked():
        return False
    if maintenant - dernier_contact > reglages['arret_auto_minutes'] * 60:
        return True
    return bool(reglages['arret_fermeture'] and fermeture_demandee
                and dernier_contact_local <= fermeture_demandee
                and maintenant - fermeture_demandee > DELAI_FERMETURE)


def surveiller():
    while True:
        time.sleep(2)
        if doit_s_arreter(time.time(), lire_reglages()):
            arreter()


def fermer_demarrage(delai=0.0):
    """Ferme l'ecran de demarrage de l'exe, apres un court delai pour laisser la fenetre apparaitre."""
    try:
        import pyi_splash
    except ImportError:
        return
    threading.Timer(delai, pyi_splash.close).start()


def main():
    # Relance avec python.exe : le pare-feu l'autorise deja, pythonw.exe non
    executable = Path(sys.executable)
    if not EXE and executable.name.lower() == 'pythonw.exe' and (executable.parent / 'python.exe').exists():
        subprocess.Popen([str(executable.parent / 'python.exe'), __file__] + sys.argv[1:],
                         creationflags=SANS_CONSOLE, cwd=str(Path(__file__).resolve().parent))
        return

    try:
        global SERVEUR_RESEAU
        SERVEUR_RESEAU = lire_reglages()['acces_reseau']
        hote = '0.0.0.0' if SERVEUR_RESEAU else '127.0.0.1'
        serveur = Serveur((hote, PORT), Gestionnaire)
    except OSError:
        # Deja lance : on rouvre seulement la fenetre
        ouvrir_fenetre()
        fermer_demarrage(1.5)
        return
    if '--sans-fenetre' not in sys.argv:
        ouvrir_fenetre()
    fermer_demarrage(1.5 if '--sans-fenetre' not in sys.argv else 0)
    threading.Thread(target=surveiller, daemon=True).start()
    if lire_reglages()['verifier_mises_a_jour'] and not os.environ.get('PRISME_RACINE'):
        threading.Thread(target=verifier_mise_a_jour, daemon=True).start()
    serveur.serve_forever()


if __name__ == '__main__':
    main()
