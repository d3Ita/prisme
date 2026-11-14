"""Serveur local de Prisme : sert l'interface web et lance sd-cli (stable-diffusion.cpp)."""

import base64
import hashlib
import shlex
import shutil
import signal
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

import agrandir
from urllib.parse import parse_qs, unquote, urlencode, urlparse

VERSION = '2.1.3'
# PRISME_PORT change le port, par exemple pour lancer une version de travail a cote de Prisme
PORT = int(os.environ.get('PRISME_PORT') or 7861)
# Dans l'exe, les fichiers de l'interface sont extraits a part ; les donnees restent a cote de l'exe
EXE = getattr(sys, 'frozen', False)
# macOS lance une app telechargee et pas deplacee depuis une copie temporaire en lecture seule (App Translocation) :
# ce chemin change apres un redemarrage (Claude ne retrouverait plus Prisme) et Prisme ne peut pas s'y mettre a jour
TRANSLOQUE = EXE and '/AppTranslocation/' in sys.executable
DEPLACER_MAC = ('macOS fait tourner Prisme depuis une copie temporaire : quitte Prisme, glisse Prisme.app dans le '
                'dossier Applications, puis relance-le.')
WINDOWS = sys.platform == 'win32'
MAC = sys.platform == 'darwin'
SYSTEME = 'windows' if WINDOWS else 'mac' if MAC else 'linux'
# Les moteurs et le navigateur ne doivent pas ouvrir de console sous Windows
SANS_CONSOLE = subprocess.CREATE_NO_WINDOW if WINDOWS else 0
# Les moteurs tournent en priorite basse, et laissent un coeur du processeur libre : l'ordinateur reste
# utilisable pendant une generation, sans ralentir le calcul quand rien d'autre ne tourne
OPTIONS_MOTEUR = SANS_CONSOLE | (subprocess.BELOW_NORMAL_PRIORITY_CLASS if WINDOWS else 0)


# Memoire de carte graphique gardee libre pour l'affichage pendant une creation ou une amelioration (reglage memoire_ecran).
# Sans elle, sd-cli et llama-server remplissent la carte a 0,5 Go pres et l'ecran du PC gele. Sur Mac, la memoire est
# partagee et geree par le systeme : rien a reserver.
RESERVE_ECRAN_GO = 1.5


def reserve_ecran(r):
    return bool(r.get('memoire_ecran', True)) and not MAC


def options_reserve_sd(r):
    """Arguments de sd-cli : une valeur negative de --max-vram garde cette memoire libre."""
    return ['--max-vram', f'-{RESERVE_ECRAN_GO}'] if reserve_ecran(r) else []


def fils_calcul():
    logiques = os.cpu_count() or 2
    # Les puces Apple n'ont pas d'hyperthreading ; ailleurs, un coeur physique compte en general deux fils
    physiques = logiques if MAC else max(1, logiques // 2)
    return max(1, physiques - 1)


if WINDOWS:
    class _LimitesJob(ctypes.Structure):
        """JOBOBJECT_EXTENDED_LIMIT_INFORMATION"""
        _fields_ = [('PerProcessUserTimeLimit', ctypes.c_int64), ('PerJobUserTimeLimit', ctypes.c_int64),
                    ('LimitFlags', ctypes.c_uint32), ('MinimumWorkingSetSize', ctypes.c_size_t),
                    ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', ctypes.c_uint32),
                    ('Affinity', ctypes.c_size_t), ('PriorityClass', ctypes.c_uint32), ('SchedulingClass', ctypes.c_uint32),
                    ('IoInfo', ctypes.c_uint64 * 6), ('ProcessMemoryLimit', ctypes.c_size_t),
                    ('JobMemoryLimit', ctypes.c_size_t), ('PeakProcessMemoryUsed', ctypes.c_size_t),
                    ('PeakJobMemoryUsed', ctypes.c_size_t)]
    _noyau = ctypes.WinDLL('kernel32', use_last_error=True)
    _noyau.CreateJobObjectW.restype = _noyau.OpenProcess.restype = ctypes.c_void_p
elif sys.platform.startswith('linux'):
    _prctl = ctypes.CDLL(None, use_errno=True).prctl
_job = None


def job_moteurs():
    """Windows : objet Job qui arrete les moteurs des que Prisme se termine, meme s'il plante ou est tue
    (JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE) ; None si le systeme le refuse."""
    global _job
    if _job is None:
        job = _noyau.CreateJobObjectW(None, None)
        limites = _LimitesJob(LimitFlags=0x2000)
        _job = job if job and _noyau.SetInformationJobObject(ctypes.c_void_p(job), 9, ctypes.byref(limites),
                                                             ctypes.sizeof(limites)) else 0
    return _job or None


def mourir_avec_prisme():
    """Linux, dans le moteur juste avant son lancement : il recoit SIGKILL quand Prisme disparait (PR_SET_PDEATHSIG)."""
    _prctl(1, signal.SIGKILL)


def lancer_moteur(commande, **options):
    """Moteur en priorite basse qui ne survit pas a Prisme : objet Job sous Windows, PR_SET_PDEATHSIG sous Linux, et sous
    Linux et Mac un groupe de processus a lui, arrete d'un coup avec ce qu'il a lance."""
    if not WINDOWS:
        options['start_new_session'] = True
        if sys.platform.startswith('linux'):
            options['preexec_fn'] = mourir_avec_prisme
    processus = subprocess.Popen(commande, creationflags=OPTIONS_MOTEUR, **options)
    if WINDOWS and job_moteurs():
        _noyau.AssignProcessToJobObject(ctypes.c_void_p(job_moteurs()), ctypes.c_void_p(int(processus._handle)))
    elif not WINDOWS:
        try:
            os.setpriority(os.PRIO_PROCESS, processus.pid, 10)
        except (OSError, AttributeError):
            pass
    noter_moteur(processus.pid, commande[0])
    return processus


class _MemoireProcessus(ctypes.Structure):
    # PROCESS_MEMORY_COUNTERS de Windows
    _fields_ = [('cb', ctypes.c_ulong), ('PageFaultCount', ctypes.c_ulong)] + [(n, ctypes.c_size_t) for n in (
        'PeakWorkingSetSize', 'WorkingSetSize', 'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
        'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]


def attendre_moteur(moteur):
    """Attend la fin du moteur : (code de sortie, memoire vive la plus haute qu'il a prise en octets, ou None).
    La memoire de la carte graphique n'y est pas."""
    if WINDOWS:
        code = moteur.wait()
        compteurs = _MemoireProcessus(cb=ctypes.sizeof(_MemoireProcessus))
        lu = _noyau.K32GetProcessMemoryInfo(ctypes.c_void_p(int(moteur._handle)), ctypes.byref(compteurs), compteurs.cb)
        return code, compteurs.PeakWorkingSetSize if lu else None
    try:
        _, statut, usage = os.wait4(moteur.pid, 0)
    except ChildProcessError:
        return moteur.wait(), None
    moteur.returncode = os.waitstatus_to_exitcode(statut)
    # ru_maxrss : en octets sur Mac, en kilo-octets sous Linux
    return moteur.returncode, usage.ru_maxrss * (1 if sys.platform == 'darwin' else 1024)


def tuer_arbre(moteur):
    """Arrete un moteur et ce qu'il a lance : son groupe sous Linux et Mac ; sous Windows, l'objet Job s'en charge."""
    try:
        if WINDOWS:
            moteur.kill()
        else:
            os.killpg(moteur.pid, signal.SIGKILL)
    except OSError:
        try:
            moteur.kill()
        except OSError:
            pass


def chemin_processus(pid):
    """Executable d'un processus en cours, ou None s'il n'existe plus ou n'est pas accessible."""
    try:
        if WINDOWS:
            poignee = _noyau.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not poignee:
                return None
            try:
                code, tampon, taille = ctypes.c_ulong(), ctypes.create_unicode_buffer(32768), ctypes.c_ulong(32768)
                _noyau.GetExitCodeProcess(ctypes.c_void_p(poignee), ctypes.byref(code))
                if code.value != 259:  # STILL_ACTIVE
                    return None
                ok = _noyau.QueryFullProcessImageNameW(ctypes.c_void_p(poignee), 0, tampon, ctypes.byref(taille))
                return tampon.value if ok else None
            finally:
                _noyau.CloseHandle(ctypes.c_void_p(poignee))
        if sys.platform.startswith('linux'):
            return os.readlink(f'/proc/{pid}/exe')
        sortie = subprocess.run(['ps', '-p', str(pid), '-o', 'comm='], capture_output=True, text=True, timeout=5).stdout
        return sortie.strip() or None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def tuer_pid(pid):
    if WINDOWS:
        poignee = _noyau.OpenProcess(0x0001, False, pid)  # PROCESS_TERMINATE
        if poignee:
            _noyau.TerminateProcess(ctypes.c_void_p(poignee), 1)
            _noyau.CloseHandle(ctypes.c_void_p(poignee))
        return
    for tuer in (lambda: os.killpg(pid, signal.SIGKILL), lambda: os.kill(pid, signal.SIGKILL)):
        try:
            return tuer()
        except OSError:
            pass


verrou_fichier_moteurs = threading.Lock()


def noter_moteur(pid, executable):
    """Garde la trace des moteurs lances (fichier moteurs.json), pour arreter ceux qu'un plantage aurait laisses."""
    with verrou_fichier_moteurs:
        notes = lire_notes_moteurs()
        notes = {p: c for p, c in notes.items() if chemin_processus(int(p))}
        notes[str(pid)] = str(Path(executable).resolve())
        DONNEES.mkdir(exist_ok=True)
        FICHIER_MOTEURS.write_text(json.dumps(notes), encoding='utf-8')


def lire_notes_moteurs():
    try:
        notes = json.loads(FICHIER_MOTEURS.read_text(encoding='utf-8'))
        return {str(int(p)): str(c) for p, c in notes.items()} if isinstance(notes, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def arreter_moteurs_orphelins():
    """Au lancement : arrete les moteurs d'une session precedente (Prisme plante ou tue) notes dans moteurs.json,
    seulement s'ils tournent encore depuis les dossiers des moteurs de ce Prisme : jamais un autre programme."""
    dossiers = [(RACINE / 'sd').resolve(), (RACINE / 'llama').resolve()]
    arretes = []
    with verrou_fichier_moteurs:
        for pid, chemin in lire_notes_moteurs().items():
            reel = chemin_processus(int(pid))
            if reel and Path(reel).resolve() == Path(chemin).resolve() and \
                    any(Path(reel).resolve().is_relative_to(d) for d in dossiers):
                tuer_pid(int(pid))
                arretes.append(int(pid))
        FICHIER_MOTEURS.unlink(missing_ok=True)
    return arretes
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
# Moteurs lances par Prisme (PID et executable), pour arreter ceux qu'un plantage laisserait tourner
FICHIER_MOTEURS = DONNEES / 'moteurs.json'
MODELES = RACINE / 'models'
LORAS = MODELES / 'loras'
IMAGES = RACINE / 'images'
# Images demandees par Claude : a part des images creees dans Prisme, que Claude ne lit pas
IMAGES_CLAUDE = RACINE / 'images-claude'
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
    # Modele d'agrandissement (Real-ESRGAN) ; vide = celui du catalogue, s'il est dans le dossier models
    'modele_agrandissement': '',
    'etapes': 20,
    'cfg': 4.0,
    'methode': 'euler',
    'sigmas': '',
    'dechargement_cpu': True,
    'vae_tuiles': True,
    'flash_attention': True,
    # Laisse de la memoire de carte graphique a Windows (ou au bureau sous Linux) : sinon l'ecran gele pendant les calculs
    'memoire_ecran': True,
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
EXTENSIONS_MODELES = ('.gguf', '.safetensors')
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
# Demandes de Claude (serveur MCP) qui attendent l'accord de l'utilisateur dans la fenetre de Prisme :
# licence non commerciale a accepter, ou modele hors du catalogue de Prisme
consentements = {}
verrou_consentements = threading.Lock()
DUREE_CONSENTEMENT, CONSENTEMENTS_MAX = 600, 5
# Derniere requete de la fenetre de Prisme, et du serveur MCP (en-tete X-Prisme-Client: mcp)
dernier_contact_fenetre = 0.0
dernier_contact_mcp = 0.0
DELAI_MCP = 600
# La fenetre appelle /api/etat toutes les 2,5 s (au moins une fois par minute si elle est reduite) : sans nouvelles
# pendant 5 min, elle est fermee meme si elle n'a pas pu le dire (navigateur ferme d'un coup, plantage)
SILENCE_FENETRE = 300
verrou_echecs = threading.Lock()
# Acces reseau du serveur en cours : un changement de reglage s'applique au prochain lancement
SERVEUR_RESEAU = True


def chemin_relatif_sur(nom):
    """Vrai si le chemin reste dans son dossier, en appliquant les regles de Windows et des autres systemes."""
    nom = str(nom).replace('\\', '/')
    return bool(nom) and not (PureWindowsPath(nom).anchor or PurePosixPath(nom).anchor or '..' in PurePosixPath(nom).parts)


verrou_reglages = threading.RLock()


def ecrire_reglages(r):
    """Ecrit les reglages d'un coup (fichier provisoire, puis renomme) : une coupure ne laisse jamais un fichier a moitie
    ecrit, que Prisme relirait comme des reglages par defaut."""
    DONNEES.mkdir(exist_ok=True)
    provisoire = FICHIER_REGLAGES.with_name(FICHIER_REGLAGES.name + '.provisoire')
    provisoire.write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding='utf-8')
    provisoire.replace(FICHIER_REGLAGES)


def version_reglages():
    """Change a chaque ecriture : la fenetre Reglages la renvoie pour ne pas ecraser un choix fait entre-temps.
    En texte : ce nombre de 19 chiffres serait arrondi par JavaScript, et l'enregistrement toujours refuse."""
    try:
        return str(FICHIER_REGLAGES.stat().st_mtime_ns)
    except OSError:
        return '0'


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
                    'amelioration_vision_locale', agrandir.CLE):
            nom = str(donnees.get(cle, r[cle])).strip().replace('\\', '/')
            if nom and not chemin_relatif_sur(nom):
                return None, 'Les modèles doivent être dans le dossier models.'
            r[cle] = nom
        r['etapes'] = int(donnees.get('etapes', r['etapes']))
        r['cfg'] = float(donnees.get('cfg', r['cfg']))
        r['methode'] = str(donnees.get('methode', r['methode']))
        r['sigmas'] = ','.join(x.strip() for x in str(donnees.get('sigmas', r['sigmas'])).split(',') if x.strip())
        for cle in ('dechargement_cpu', 'vae_tuiles', 'flash_attention', 'memoire_ecran', 'acces_reseau', 'arret_fermeture',
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
        return None, 'Choisis au moins le modèle de dessin, le modèle de texte et le VAE.'
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
    roles = {'modele_diffusion': 'Modèle de dessin', 'modele_texte': 'Modèle de texte', 'vae': 'VAE'}
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


def supprimer_modele(nom):
    """Supprime definitivement un fichier du dossier models (et son telechargement partiel) pour liberer la place, puis
    retire ce fichier des reglages qui le choisissaient. Renvoie la place liberee, en octets."""
    nom = str(nom).replace('\\', '/')
    fichier = MODELES / nom
    if not chemin_relatif_sur(nom) or not fichier.is_file() or fichier.suffix.lower() not in EXTENSIONS_MODELES \
            or LORAS in fichier.parents:
        raise ValueError('Modèle introuvable dans le dossier models.')
    with verrou_modeles:
        if any(t['phase'] in ('attente', 'telechargement', 'verification') and MODELES_PAR_ID[i]['fichier'] == nom
               for i, t in telechargements_modeles.items() if i in MODELES_PAR_ID):
            raise RuntimeError('Ce modèle est en cours de téléchargement : arrête d\'abord le téléchargement.')
    libere = fichier.stat().st_size
    fichier.unlink()
    partiel = MODELES / (nom + '.partiel')
    if partiel.is_file():
        libere += partiel.stat().st_size
        partiel.unlink()
    with verrou_reglages:
        r = lire_reglages()
        vides = {cle: '' for cle, valeur in r.items() if isinstance(valeur, str) and valeur == nom and cle in REGLAGES_DEFAUT
                 and REGLAGES_DEFAUT[cle] == ''}
        if vides:
            r.update(vides)
            ecrire_reglages(r)
    return libere


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
        self.reserve = reserve_ecran(r)
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
        # Avec la reserve pour l'ecran, llama.cpp choisit lui-meme combien de couches tiennent sur la carte (--fit) en
        # gardant cette marge ; -ngl 99 forcerait tout le modele sur la carte et annulerait ce calcul
        couches = ['--fit', 'on', '--fit-target', str(int(RESERVE_ECRAN_GO * 1024))] if self.reserve else ['-ngl', '99']
        commande = [str(LLAMA_SERVEUR), '-m', str(self.modele), *couches, '-c', '8192',
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
        corps = json.dumps({'messages': messages, 'temperature': temperature, 'max_tokens': 400,
                            'chat_template_kwargs': {'enable_thinking': False}}).encode()
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
            tuer_arbre(self.processus)
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


# Modeles conseilles, telechargeables depuis Prisme : modeles officiels et generalistes, verifies par empreinte.
# Le catalogue (fichiers et profils par machine) est dans app/modeles.json
CATALOGUE = json.loads((RESSOURCES / 'modeles.json').read_text(encoding='utf-8'))
ROLES_MODELES = {'image': 'Modèle de dessin', 'texte': 'Modèle de texte', 'edition': 'Vision', 'vae': 'VAE',
                 'agrandissement': 'Agrandissement'}
MODELES_CONSEILLES = [
    m | {'role': ROLES_MODELES[m['role']], 'role_id': m['role'],
         'titre': f"{m['nom']} · {m['quantification']}" if m['quantification'] else m['nom'],
         'detail': m['detail']['fr'], 'detail_en': m['detail']['en']}
    for m in CATALOGUE['modeles']
]
PROFILS = CATALOGUE['profils']
# Les options (licence non commerciale, autre style) ne sont jamais suggerees automatiquement
PRINCIPAUX = [p for p in PROFILS if p['categorie'] == 'principal']
MODELES_PAR_ID = {m['id']: m for m in MODELES_CONSEILLES}
GO = 1024 ** 3


def memoire_systeme():
    """Memoire vive totale, en octets (0 si elle n'a pas pu etre lue)."""
    try:
        if SYSTEME == 'linux':
            with open('/proc/meminfo', encoding='ascii') as f:
                for ligne in f:
                    if ligne.startswith('MemTotal:'):
                        return int(ligne.split()[1]) * 1024
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


def sortie_outil(commande):
    """Sortie d'un outil de diagnostic deja present sur la machine (nvidia-smi...), ou '' s'il manque."""
    try:
        return subprocess.run(commande, capture_output=True, text=True, timeout=10, creationflags=SANS_CONSOLE).stdout
    except (OSError, subprocess.SubprocessError, ValueError):
        return ''


def cartes_registre():
    """Cartes graphiques declarees dans le registre de Windows, avec leur memoire (toutes marques)."""
    import winreg
    cartes = []
    classe = r'SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}'
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, classe) as cle:
            for i in range(winreg.QueryInfoKey(cle)[0]):
                sous = winreg.EnumKey(cle, i)
                if not sous.isdigit():
                    continue
                try:
                    with winreg.OpenKey(cle, sous) as carte:
                        nom = str(winreg.QueryValueEx(carte, 'DriverDesc')[0])
                        memoire = 0
                        for valeur in ('HardwareInformation.qwMemorySize', 'HardwareInformation.MemorySize'):
                            try:
                                brut = winreg.QueryValueEx(carte, valeur)[0]
                            except OSError:
                                continue
                            memoire = int.from_bytes(brut[:8], 'little') if isinstance(brut, bytes) else int(brut)
                            break
                except OSError:
                    continue
                if 'Basic' not in nom and 'Virtual' not in nom:
                    cartes.append({'nom': nom, 'video': memoire, 'source': 'registre'})
    except OSError:
        pass
    return cartes


def carte_graphique():
    """Carte graphique principale et sa memoire video, lues avec les outils presents (nvidia-smi, rocm-smi,
    /sys sous Linux, registre de Windows, vulkaninfo). None si aucune carte dediee n'est trouvee."""
    if MAC:
        return None
    cartes = []
    for ligne in sortie_outil(['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv,noheader,nounits']).splitlines():
        nom, _, memoire = ligne.rpartition(',')
        if nom.strip() and memoire.strip().isdigit():
            cartes.append({'nom': nom.strip(), 'video': int(memoire) * 1024 * 1024, 'source': 'nvidia-smi'})
    if not cartes and SYSTEME == 'linux':
        try:
            for nom, infos in (json.loads(sortie_outil(['rocm-smi', '--showmeminfo', 'vram', '--json']) or '{}')).items():
                total = next((v for k, v in infos.items() if 'Total' in k and 'Used' not in k), None)
                if total:
                    cartes.append({'nom': nom, 'video': int(total), 'source': 'rocm-smi'})
        except (ValueError, AttributeError, TypeError):
            pass
        for fichier in Path('/sys/class/drm').glob('card*/device/mem_info_vram_total'):
            try:
                cartes.append({'nom': 'AMD', 'video': int(fichier.read_text()), 'source': 'sysfs'})
            except (OSError, ValueError):
                pass
    if not cartes and WINDOWS:
        cartes = cartes_registre()
    if not cartes:
        # vulkaninfo donne le type de carte, pas sa memoire
        types = re.findall(r'deviceType\s*=\s*PHYSICAL_DEVICE_TYPE_(\w+)', sortie_outil(['vulkaninfo', '--summary']))
        noms = re.findall(r'deviceName\s*=\s*(.+)', sortie_outil(['vulkaninfo', '--summary']))
        for genre, nom in zip(types, noms):
            if genre in ('DISCRETE_GPU', 'INTEGRATED_GPU'):
                cartes.append({'nom': nom.strip(), 'video': 0, 'integree': genre == 'INTEGRATED_GPU', 'source': 'vulkaninfo'})
    return max(cartes, key=lambda c: (c['video'], not c.get('integree')), default=None)


def memoire_video(carte=None):
    """Memoire de la carte graphique ; sur Mac, la memoire est partagee."""
    if MAC:
        return memoire_systeme()
    return (carte or {}).get('video', 0)


def suggerer_profil(machine):
    """Profil de modeles le plus complet que la machine peut porter, ou None si sa configuration n'a pas pu etre lue
    (l'utilisateur choisit alors lui-meme). Les seuils sont dans app/modeles.json (en Gio)."""
    go = lambda octets: (octets or 0) / GO
    if machine.get('mac'):
        if not machine.get('memoire'):
            return None
        candidats = [p for p in PRINCIPAUX if p['cible']['type'] == 'mac' and go(machine['memoire']) >= p['cible']['memoire_min']]
    else:
        carte, video = machine.get('carte'), machine.get('video') or 0
        # Carte dediee vue, mais sa memoire est illisible : mieux vaut laisser choisir
        if carte and not video and not carte.get('integree'):
            return None
        candidats = [p for p in PRINCIPAUX if p['cible']['type'] == 'pc' and go(video) >= p['cible']['video_min']
                     and (not machine.get('memoire') or go(machine['memoire']) >= p['cible']['memoire_min'])]
    meilleur = max(candidats, key=lambda p: (p['cible']['video_min'], p['cible']['memoire_min']), default=None)
    return meilleur['id'] if meilleur else None


_machine = None


def profil_machine():
    """Ensemble de modeles adapte : leger si la memoire est juste (Mac de moins de 24 Go, carte de moins de 12 Go,
    ou moins de 24 Go de memoire vive), complet sinon."""
    global _machine
    if _machine is None:
        carte = carte_graphique()
        vive, video = memoire_systeme(), memoire_video(carte)
        if MAC:
            leger = not vive or vive < 24 * GO
        else:
            leger = bool(video and video < 11.5 * GO) or bool(vive and vive < 24 * GO)
        machine = {'profil': 'leger' if leger else 'complet', 'memoire': vive, 'video': video, 'mac': MAC,
                   'systeme': SYSTEME, 'carte': carte}
        machine['suggestion'] = suggerer_profil(machine)
        _machine = machine
    return _machine


def profil_conseille(machine):
    """Profil suggere, ou a defaut l'ensemble leger ou complet d'avant la detection detaillee."""
    if machine.get('suggestion'):
        return machine['suggestion']
    if machine.get('mac'):
        return 'mac-16go' if machine['profil'] == 'leger' else 'mac-32go'
    return 'gpu-8go' if machine['profil'] == 'leger' else 'gpu-12go'
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


def reglages_generation_automatiques(r):
    """Vrai si les reglages de generation sont ceux par defaut ou ceux d'un modele du catalogue : l'utilisateur ne les a
    pas changes, Prisme peut donc les adapter au modele de dessin choisi."""
    actuels = {cle: r[cle] for cle in ('etapes', 'cfg', 'methode', 'sigmas')}
    connus = [{cle: REGLAGES_DEFAUT[cle] for cle in actuels}] + [m['reglages'] for m in MODELES_CONSEILLES if m.get('reglages')]
    return any(actuels == {cle: c[cle] for cle in actuels} for c in connus)


def utiliser_modele(modele):
    """Choisit le modele telecharge dans les reglages : on le telecharge pour s'en servir."""
    with verrou_reglages:
        r = lire_reglages()
        avant = dict(r)
        for cle in modele['remplit']:
            r[cle] = modele['fichier']
        # Un modele de texte sans vision retire la vision d'un autre modele, qui ne marcherait pas avec lui
        for cle in modele.get('vide', []):
            r[cle] = ''
        # Reglages propres au modele de dessin (Turbo : 8 etapes), sauf si l'utilisateur a regle les siens
        if modele.get('reglages') and 'modele_diffusion' in modele['remplit'] and reglages_generation_automatiques(avant):
            r.update(modele['reglages'])
        if r != avant:
            ecrire_reglages(r)


# Roles qu'on peut donner a n'importe quel fichier du dossier models dans la fenetre des modeles (mode avance)
ROLES_CHOISIS = {'image': 'modele_diffusion', 'texte': 'modele_texte', 'edition': 'modele_vision', 'vae': 'vae'}


def utiliser_fichier(nom, role):
    """Choisit un fichier du dossier models pour un role, sans passer par un profil : la configuration reste libre.
    Un fichier du catalogue garde ses regles (etapes du modele de dessin, vision retiree si le texte n'en a pas)."""
    nom = str(nom).replace('\\', '/')
    fichier = MODELES / nom
    if role == 'edition' and not nom:
        # La vision est facultative : « Aucune »
        with verrou_reglages:
            reglages = lire_reglages()
            reglages['modele_vision'] = ''
            ecrire_reglages(reglages)
        return
    if not chemin_relatif_sur(nom) or not fichier.is_file() or fichier.suffix.lower() not in EXTENSIONS_MODELES \
            or LORAS in fichier.parents:
        raise ValueError('Modèle introuvable dans le dossier models.')
    connu = next((m for m in MODELES_CONSEILLES if m['fichier'] == nom and m['role_id'] == role), None)
    if connu:
        utiliser_modele(connu)
        return
    if role not in ROLES_CHOISIS:
        raise ValueError('Rôle inconnu.')
    with verrou_reglages:
        reglages = lire_reglages()
        reglages[ROLES_CHOISIS[role]] = nom
        ecrire_reglages(reglages)


def telecharger_modele(modele):
    """Telecharge un modele dans models/ en reprenant un telechargement interrompu, puis verifie son empreinte."""
    suivi = telechargements_modeles[modele['id']]
    final = MODELES / modele['fichier']
    partiel = MODELES / (modele['fichier'] + '.partiel')
    try:
        final.parent.mkdir(parents=True, exist_ok=True)
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
        # Un modele hors catalogue n'a pas toujours d'empreinte connue : sa taille est alors seule verifiee
        if partiel.stat().st_size != modele['taille'] or (modele['sha256'] and empreinte_fichier(partiel) != modele['sha256']):
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


MODELES_EXTERNES = {}
ROLES_EXTERNES = {'image': ['modele_diffusion'], 'texte': ['modele_texte'], 'edition': ['modele_vision'], 'vae': ['vae'],
                  'lora': [], None: []}


def trouver_modele(ident):
    return MODELES_PAR_ID.get(ident) or MODELES_EXTERNES.get(ident)


def infos_fichier_distant(url):
    """Taille et empreinte SHA-256 d'un fichier, lues dans les en-tetes sans le telecharger. Hugging Face donne
    l'empreinte des gros fichiers (X-Linked-Etag) ; ailleurs, seule la taille est connue."""
    class SansRedirection(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    ouvreur = urllib.request.build_opener(urllib.request.HTTPSHandler(context=contexte_ssl()), SansRedirection)
    requete = urllib.request.Request(url, method='HEAD', headers={'User-Agent': f'Prisme/{VERSION}'})
    redirection = False
    try:
        with ouvreur.open(requete, timeout=20) as reponse:
            en_tetes = reponse.headers
    except urllib.error.HTTPError as e:
        if e.code not in (301, 302, 303, 307, 308):
            raise erreur_lisible(e, url) from None
        en_tetes, redirection = e.headers, True
    except (urllib.error.URLError, OSError) as e:
        raise erreur_lisible(e, url) from None
    taille = en_tetes.get('X-Linked-Size') or ('' if redirection else en_tetes.get('Content-Length'))
    if not taille and redirection:
        try:
            with urllib.request.urlopen(urllib.request.Request(url, method='HEAD', headers={'User-Agent': f'Prisme/{VERSION}'}),
                                        context=contexte_ssl(), timeout=20) as reponse:
                taille = reponse.headers.get('Content-Length')
        except (urllib.error.URLError, OSError) as e:
            raise erreur_lisible(e, url) from None
    empreinte = (en_tetes.get('X-Linked-Etag') or '').strip('"').lower()
    return int(taille or 0), empreinte if re.fullmatch(r'[0-9a-f]{64}', empreinte) else None


def preparer_externe(url, role, nom=None):
    """Verifie une demande de modele hors catalogue : https, fichier .gguf ou .safetensors, pas deja present.
    nom : nom du fichier enregistre, s'il doit differer de celui du lien."""
    adresse = urlparse(str(url or ''))
    if adresse.scheme != 'https' or not adresse.hostname:
        raise ValueError('Adresse invalide : il faut un lien https vers le fichier.')
    if role not in ROLES_EXTERNES:
        raise ValueError('Rôle inconnu : image, texte, edition, vae ou lora.')
    nom = nom or unquote(adresse.path.rsplit('/', 1)[-1])
    if not re.fullmatch(r'[\w.+-]+', nom) or not nom.lower().endswith(EXTENSIONS_MODELES):
        raise ValueError('Seuls les fichiers .gguf et .safetensors peuvent être téléchargés.')
    fichier = ('loras/' if role == 'lora' else '') + nom
    if (MODELES / fichier).exists():
        raise ValueError(f'{nom} est déjà dans le dossier des modèles.')
    taille, empreinte = infos_fichier_distant(url)
    if taille <= 0:
        raise ValueError('La taille du fichier est inconnue : téléchargement refusé.')
    return {'url': url, 'hote': adresse.hostname, 'fichier': fichier, 'taille': taille, 'sha256': empreinte, 'role': role}


def creer_consentement(genre, details):
    with verrou_consentements:
        maintenant = time.time()
        for cle in [c for c, d in consentements.items() if maintenant - d['cree'] > DUREE_CONSENTEMENT]:
            consentements[cle]['etat'] = 'expiree' if consentements[cle]['etat'] == 'attente' else consentements[cle]['etat']
        if sum(d['etat'] == 'attente' for d in consentements.values()) >= CONSENTEMENTS_MAX:
            raise OverflowError
        ident = secrets.token_urlsafe(9)
        consentements[ident] = {'genre': genre, 'details': details, 'etat': 'attente', 'cree': maintenant, 'telechargements': []}
    # La demande doit etre vue : si aucune fenetre de Prisme n'est ouverte, on en ouvre une
    if time.time() - dernier_contact_fenetre > 8:
        threading.Thread(target=afficher_fenetre, daemon=True).start()
    return ident


def ajouter_externe(d):
    """Un fichier hors catalogue (verifie par preparer_externe) devient telechargeable : son identifiant."""
    ident = 'externe-' + hashlib.sha256(d['url'].encode()).hexdigest()[:12]
    MODELES_EXTERNES[ident] = {'id': ident, 'role': ROLES_MODELES.get(d['role'], 'Autre'), 'role_id': d['role'],
                               'titre': Path(d['fichier']).name, 'fichier': d['fichier'], 'url': d['url'],
                               'taille': d['taille'], 'sha256': d['sha256'], 'remplit': ROLES_EXTERNES[d['role']],
                               'vide': [], 'reglages': None, 'licence': {'nom': None, 'commercial': None}}
    return ident


# --- Bibliotheque de LoRA : ceux de Hugging Face faits pour le modele de dessin choisi
# Modeles de base sur Hugging Face pour chaque famille du catalogue (les LoRA y declarent leur base_model)
BASES_LORA = {'flux2-klein': ['black-forest-labs/FLUX.2-klein-4B', 'black-forest-labs/FLUX.2-klein-base-4B'],
              'z-image-turbo': ['Tongyi-MAI/Z-Image-Turbo'],
              'qwen-image-2.1': ['Qwen/Qwen-Image-2.1-Turbo', 'Qwen/Qwen-Image-2.1']}
# Pas proposes : contenus pour adultes (Hugging Face a une etiquette, mais beaucoup de depots ne la mettent pas) et
# echange de visages (deepfakes). shortcut: filtre par mots du nom, des etiquettes et des exemples ; une image d'apercu
# peut encore surprendre, a completer si des retours le montrent
MOTS_EXCLUS = re.compile(r'nsfw|uncensor|nud(e|ity)|naked|porn|hentai|erotic|sexy|\bsex|lingerie|breast|busty|cleavage|'
                         r'bikini|undress|nipple|\bboob|\bass\b|\bbutt|onlyfans|fetish|\badult|cum(shot)?\b|penis|\bdick|'
                         r'vagina|pussy|\b18\+|face.?swap|swap.?face|deep.?fake|face.?transfer', re.I)
ID_DEPOT = re.compile(r'[\w.-]+/[\w.-]+')
cache_bibliotheque = {}


def famille_du_modele(r):
    """Famille du catalogue du modele de dessin choisi (flux2-klein...), ou None pour un modele personnel."""
    m = next((m for m in MODELES_CONSEILLES if m['fichier'] == r['modele_diffusion'] and 'modele_diffusion' in m['remplit']), None)
    return (m['familles'] or [None])[0] if m else None


def lora_de_hugging_face(m):
    """Une entree de la bibliotheque d'apres la reponse de l'API Hugging Face, ou None si elle n'est pas proposee
    (prive, acces restreint, contenu pour adultes, pas de fichier .safetensors)."""
    carte = m.get('cardData') or {}
    widgets = [w for w in carte.get('widget') or [] if isinstance(w, dict)]
    texte = ' '.join([m['id'], ' '.join(m.get('tags') or []), ' '.join(str(w.get('text') or '') for w in widgets),
                      str(carte.get('instance_prompt') or '')])
    if m.get('private') or m.get('gated') or 'not-for-all-audiences' in (m.get('tags') or []) or MOTS_EXCLUS.search(texte):
        return None
    fichiers = [s['rfilename'] for s in m.get('siblings') or []
                if '/' not in s['rfilename'] and s['rfilename'].lower().endswith('.safetensors')]
    if not fichiers or not ID_DEPOT.fullmatch(m['id']):
        return None
    # Le format ComfyUI en dernier : sd-cli lit d'abord le format diffusers
    fichiers.sort(key=lambda f: ('comfy' in f.lower(), f))
    apercu = next((str((w.get('output') or {}).get('url') or '') for w in widgets if isinstance(w.get('output'), dict)), '')
    if apercu and not apercu.startswith('http'):
        apercu = f'https://huggingface.co/{m["id"]}/resolve/main/{apercu.lstrip("/")}'
    if not re.match(r'https://huggingface\.co/[^?#]+\.(png|jpe?g|webp)$', apercu, re.I):
        apercu = None
    licence = carte.get('license')
    return {'id': m['id'], 'auteur': m['id'].split('/')[0], 'nom': m['id'].split('/')[1].replace('-', ' ').replace('_', ' '),
            'page': f'https://huggingface.co/{m["id"]}', 'telechargements': m.get('downloads') or 0, 'likes': m.get('likes') or 0,
            'licence': str(licence) if licence else None, 'declencheur': str(carte.get('instance_prompt') or '') or None,
            'apercu': apercu, 'fichiers': fichiers[:8],
            'installe': any((LORAS / nom_fichier_lora(m['id'], f, len(fichiers))).is_file() for f in fichiers)}


def nom_fichier_lora(depot, fichier, nombre):
    """Nom du LoRA dans models/loras : celui du depot (les fichiers s'appellent souvent tous pareil), plus celui du
    fichier quand le depot en propose plusieurs."""
    nom = re.sub(r'[^\w.+-]+', '-', depot.split('/')[1]).strip('-.') or 'lora'
    if nombre > 1:
        nom += '-' + re.sub(r'[^\w.+-]+', '-', Path(fichier).stem).strip('-.')
    return nom + '.safetensors'


def bibliotheque_loras(r, recherche=''):
    """LoRA de Hugging Face pour le modele de dessin choisi, les plus telecharges d'abord (gardes 10 minutes)."""
    famille = famille_du_modele(r)
    if not famille or famille not in BASES_LORA:
        return {'famille': None, 'loras': []}
    cle = (famille, recherche.lower())
    connu = cache_bibliotheque.get(cle)
    if connu and time.time() - connu[0] < 600:
        return connu[1]
    trouves = {}
    for base in BASES_LORA[famille]:
        parametres = {'filter': f'base_model:adapter:{base}', 'sort': 'downloads', 'direction': '-1', 'limit': '40',
                      'full': 'true', 'cardData': 'true'}
        if recherche:
            parametres['search'] = recherche
        requete = urllib.request.Request('https://huggingface.co/api/models?' + urlencode(parametres),
                                         headers={'User-Agent': f'Prisme/{VERSION}'})
        try:
            with urllib.request.urlopen(requete, context=contexte_ssl(), timeout=15) as reponse:
                for m in json.load(reponse):
                    entree = isinstance(m, dict) and isinstance(m.get('id'), str) and lora_de_hugging_face(m)
                    if entree:
                        trouves.setdefault(entree['id'], entree)
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise RuntimeError('Hugging Face ne répond pas. Vérifie ta connexion, puis réessaie.') from e
    resultat = {'famille': famille, 'loras': sorted(trouves.values(), key=lambda l: -l['telechargements'])[:40]}
    cache_bibliotheque[cle] = (time.time(), resultat)
    return resultat


def executer_consentement(demande):
    """L'utilisateur a accepte dans la fenetre : les telechargements commencent."""
    if demande['genre'] == 'profil':
        profil = next(p for p in PROFILS if p['id'] == demande['details']['profil'])
        idents = list(profil['modeles'])
    else:
        idents = [ajouter_externe(demande['details'])]
    for ident in idents:
        demander_modele(ident)
    demande['telechargements'] = idents


def resume_telechargements():
    """Telechargements de modeles en cours ou recents, pour la fenetre et pour Claude."""
    with verrou_modeles:
        return [{'id': ident, 'fichier': trouver_modele(ident)['fichier'], 'phase': t['phase'], 'fait': t.get('fait', 0),
                 'total': t.get('total', 0), 'erreur': t.get('erreur')}
                for ident, t in telechargements_modeles.items() if trouver_modele(ident)]


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
        telecharger_modele(trouver_modele(ident))


def demander_modele(ident):
    global travailleur_modeles
    modele = trouver_modele(ident)
    final = MODELES / modele['fichier']
    # Verification et mise en file d'un seul tenant : deux demandes au meme instant ne telechargent pas deux fois
    with verrou_modeles:
        if telechargements_modeles.get(ident, {}).get('phase') in ('attente', 'telechargement', 'verification'):
            return
        present = final.is_file() and final.stat().st_size == modele['taille']
        if not present:
            telechargements_modeles[ident] = {'phase': 'attente', 'fait': 0, 'total': modele['taille'], 'erreur': None}
            file_modeles.append(ident)
            if travailleur_modeles is None:
                travailleur_modeles = threading.Thread(target=traiter_file_modeles, daemon=True)
                travailleur_modeles.start()
    if present:
        utiliser_modele(modele)
        with verrou_modeles:
            telechargements_modeles[ident] = {'phase': 'termine', 'fait': modele['taille'], 'total': modele['taille'], 'erreur': None}


def etat_profils():
    """Profils de modeles, avec ce qui est deja telecharge et le profil suggere pour cette machine."""
    machine = profil_machine()
    r = lire_reglages()
    profils = []
    for p in PROFILS:
        fichiers = [MODELES_PAR_ID[i] for i in p['modeles']]
        presents = {m['id'] for m in fichiers if (MODELES / m['fichier']).is_file()}
        profils.append({k: p[k] for k in ('id', 'nom', 'description', 'materiel', 'cible', 'categorie', 'taille_totale', 'vitesse',
                                          'statut', 'edition', 'licence_a_accepter')}
                       | {'modeles': [{k: m[k] for k in ('id', 'role_id', 'nom', 'quantification', 'fichier', 'url', 'page',
                                                          'taille', 'sha256', 'licence')} | {'present': m['id'] in presents}
                                      for m in fichiers],
                          'taille_restante': sum(m['taille'] for m in fichiers if m['id'] not in presents),
                          'installe': len(presents) == len(fichiers),
                          'actif': all(r[m['remplit'][0]] == m['fichier'] for m in fichiers)})
    MODELES.mkdir(parents=True, exist_ok=True)
    return {'profils': profils, 'suggestion': machine['suggestion'], 'conseille': profil_conseille(machine),
            'machine': machine, 'libre': shutil.disk_usage(MODELES).free}


def etat_modeles_conseilles():
    profils = etat_profils()
    conseilles = set(next(p for p in PROFILS if p['id'] == profils['conseille'])['modeles'])
    reglages = lire_reglages()
    with verrou_modeles:
        machine = profil_machine()
        modeles = [{k: m[k] for k in ('id', 'role', 'role_id', 'titre', 'detail', 'detail_en', 'fichier', 'taille', 'licence')}
                   | {'conseille': m['id'] in conseilles, 'present': (MODELES / m['fichier']).is_file(),
                      'utilise': (MODELES / m['fichier']).is_file() and all(reglages.get(c) == m['fichier'] for c in m['remplit']),
                      'reprise': (MODELES / (m['fichier'] + '.partiel')).is_file(),
                      'telechargement': dict(telechargements_modeles[m['id']]) if m['id'] in telechargements_modeles else None}
                   for m in MODELES_CONSEILLES]
    MODELES.mkdir(parents=True, exist_ok=True)
    # Le moteur de texte (pour Ameliorer) est propose dans la meme fenetre
    du_catalogue = {m['fichier'] for m in MODELES_CONSEILLES}
    # Fichiers ajoutes a la main, avec les roles qu'ils tiennent dans les reglages
    autres = [m | {'roles': [role for role, cle in ROLES_CHOISIS.items() if reglages.get(cle) == m['nom']]}
              for m in lister_modeles() if m['nom'] not in du_catalogue]
    # Configuration actuelle : celle d'un profil, ou personnalisee (fichiers choisis un par un)
    configuration = {role: reglages.get(cle) or '' for role, cle in ROLES_CHOISIS.items()}
    profil_actif = next((p['id'] for p in profils['profils'] if p['actif']), None)
    return {'modeles': modeles, 'autres': autres, 'libre': shutil.disk_usage(MODELES).free, 'machine': machine, 'moteurs': etat_moteurs(),
            'profils': profils['profils'], 'suggestion': profils['suggestion'], 'conseille': profils['conseille'],
            'configuration': configuration, 'profil_actif': profil_actif}


# Avis de nouvelle version : le numero de la derniere version publiee sur GitHub, lu une fois au lancement
PAGE_VERSIONS = 'https://github.com/d3Ita/prisme/releases/latest'
mise_a_jour = {}


def numero_version(texte):
    """Version comparable : (majeur, mineur, correctif, finale, numero de pre-version).
    2.0 vaut 2.0.0, et une pre-version (2.0.0-beta.2) passe avant la version finale (2.0.0)."""
    m = re.match(r'\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(.*)', str(texte))
    if not m:
        return (0, 0, 0, 0, 0)
    reste = m.group(4)
    if not re.search(r'[A-Za-z]', reste):
        return (*(int(x or 0) for x in m.groups()[:3]), 1, 0)
    pre = re.search(r'\d+', reste)
    return (*(int(x or 0) for x in m.groups()[:3]), 0, int(pre.group()) if pre else 0)


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


def version_par_la_page():
    """Derniere version d'apres la redirection de la page des releases, qui ne compte pas dans la limite de l'API."""
    with urllib.request.urlopen(requete_github(PAGE_VERSIONS), context=contexte_ssl(), timeout=8) as reponse:
        m = re.search(r'/releases/tag/v?([^/?#]+)$', reponse.geturl())
    return m.group(1) if m else ''


def verifier_mise_a_jour(discret=True):
    """Au lancement, en silence ; depuis le bouton des reglages (discret=False), l'erreur remonte."""
    try:
        requete = requete_github('https://api.github.com/repos/d3Ita/prisme/releases/latest', Accept='application/vnd.github+json')
        try:
            with urllib.request.urlopen(requete, context=contexte_ssl(), timeout=8) as reponse:
                version, fichier = lire_release(json.load(reponse))
        except urllib.error.HTTPError as e:
            if e.code not in (403, 429):
                raise
            # Limite de l'API (60 demandes par heure et par connexion, partagee par un bureau ou une ecole) : la version
            # d'apres la page, sans empreinte, donc avec le lien de telechargement au lieu de la mise a jour en un clic
            version, fichier = version_par_la_page(), None
        if numero_version(version) > numero_version(VERSION):
            # La mise a jour en un clic ne vaut que pour le programme construit, pas pour le script Python
            mise_a_jour.update(version=version, url=PAGE_VERSIONS, fichier=fichier, auto=bool(EXE and fichier and not TRANSLOQUE),
                               raison=DEPLACER_MAC if TRANSLOQUE else None)
    except Exception:
        if not discret:
            raise


def etat_mise_a_jour():
    with verrou_maj:
        if not mise_a_jour:
            return None
        return {k: mise_a_jour.get(k) for k in ('version', 'url', 'auto', 'raison')} | \
            {'installation': dict(mise_a_jour['installation']) if mise_a_jour.get('installation') else None}


def programme_actuel():
    """Ce qu'il faut remplacer : l'exe (Windows, Linux) ou le paquet Prisme.app (Mac)."""
    exe = Path(sys.executable).resolve()
    return exe.parents[2] if MAC else exe


# Journal des mises a jour, et message d'une mise a jour echouee, montre au lancement suivant
FICHIER_JOURNAL_MAJ = DONNEES / 'mise-a-jour.log'
FICHIER_ECHEC_MAJ = DONNEES / 'maj-echec.txt'
ECHEC_ATTENTE = 'Prisme ne s\'est pas arrêté à temps pour être mis à jour.'
ECHEC_REMPLACEMENT = ('Le nouveau programme n\'a pas pu remplacer l\'ancien : un antivirus ou un autre programme '
                      'l\'utilise peut-être.')
echec_maj = None
# Option du Prisme relance apres une mise a jour : sans fenetre pour la version web (la fenetre ouverte se recharge
# toute seule), --qt pour l'application Qt, dont la fenetre se ferme avec l'ancienne version
OPTION_RELANCE = '--sans-fenetre'


def script_remplacement(nouveau, cible, pids, temporaires=(), moteurs=(), essais=60, attente=120, relance=None):
    """Script qui attend la fin de Prisme et de ses moteurs, met le nouveau programme a sa place et le relance sans
    ouvrir de fenetre (la fenetre deja ouverte se recharge toute seule). En cas d'echec, il ne relance jamais
    l'ancienne version en silence : il ecrit l'erreur dans le journal et dans FICHIER_ECHEC_MAJ (affiche au lancement),
    supprime les fichiers temporaires, puis relance l'ancienne version, qui montre le message."""
    if WINDOWS:
        return script_powershell(nouveau, cible, pids, temporaires, moteurs, essais, attente, relance)
    return script_sh(nouveau, cible, pids, temporaires, moteurs, essais, attente, relance)


def script_powershell(nouveau, cible, pids, temporaires, moteurs, essais, attente, relance):
    q = lambda texte: "'" + str(texte).replace("'", "''") + "'"
    liste = lambda elements: '@(' + ', '.join(q(e) for e in elements) + ')'
    return '\r\n'.join([
        "$ErrorActionPreference = 'Stop'",
        f'$cible = {q(cible)}', f'$nouveau = {q(nouveau)}', f'$journal = {q(FICHIER_JOURNAL_MAJ)}', f'$echec = {q(FICHIER_ECHEC_MAJ)}',
        f'$temporaires = {liste(temporaires)}', f'$moteurs = {liste(str(d) + os.sep for d in moteurs)}',
        f'$pids = @({", ".join(str(p) for p in pids)})',
        "$ancien = $cible + '.ancien-' + (Get-Date -Format 'yyyyMMddHHmmss')",
        "function Noter($texte) { Add-Content -LiteralPath $journal -Value ((Get-Date -Format s) + ' ' + $texte) -Encoding UTF8 }",
        'function Lancer { ' + (relance or f"Start-Process -FilePath $cible -ArgumentList '{OPTION_RELANCE}'") + ' }',
        'function Echouer($raison) {',
        "  Noter ('echec : ' + $raison)",
        '  Set-Content -LiteralPath $echec -Value $raison -Encoding UTF8',
        '  foreach ($t in $temporaires) { Remove-Item -LiteralPath $t -Recurse -Force -ErrorAction SilentlyContinue }',
        '  if (-not (Test-Path -LiteralPath $cible) -and (Test-Path -LiteralPath $ancien)) { Move-Item -LiteralPath $ancien -Destination $cible -Force }',
        "  # L'ancienne version redemarre et montre l'echec : jamais de retour en silence",
        '  if (Test-Path -LiteralPath $cible) { Lancer }',
        '  Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue',
        '  exit 1',
        '}',
        "Noter ('mise a jour de ' + $cible)",
        '# Attend la fin de Prisme (lanceur et Python) et des moteurs lances depuis son dossier',
        f'$limite = (Get-Date).AddSeconds({attente})',
        'while ($true) {',
        '  $restants = @($pids | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue })',
        '  if ($moteurs.Count) { $restants += @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {',
        '    $chemin = $_.ExecutablePath; $chemin -and @($moteurs | Where-Object { $chemin.StartsWith($_, [StringComparison]::OrdinalIgnoreCase) }).Count }) }',
        '  if ($restants.Count -eq 0) { break }',
        f'  if ((Get-Date) -gt $limite) {{ Echouer {q(ECHEC_ATTENTE)} }}',
        '  Start-Sleep -Milliseconds 500',
        '}',
        "$erreur = ''",
        f'for ($i = 1; $i -le {essais}; $i++) {{',
        '  try {',
        "    # Renommer l'exe actuel est permis meme s'il tourne encore (serveur MCP de Claude, antivirus)",
        '    Move-Item -LiteralPath $cible -Destination $ancien -Force',
        '    try { Move-Item -LiteralPath $nouveau -Destination $cible -Force } catch { Move-Item -LiteralPath $ancien -Destination $cible -Force; throw }',
        "    $erreur = ''; break",
        '  } catch { $erreur = $_.Exception.Message; Start-Sleep -Seconds 2 }',
        '}',
        f"if ($erreur) {{ Noter $erreur; Echouer {q(ECHEC_REMPLACEMENT)} }}",
        "# L'ancien exe encore utilise (serveur MCP) sera supprime au prochain lancement",
        'Remove-Item -LiteralPath $ancien -Force -ErrorAction SilentlyContinue',
        "Noter 'remplacement fait'",
        'Lancer',
        'Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue',
    ]) + '\r\n'


def script_sh(nouveau, cible, pids, temporaires, moteurs, essais, attente, relance):
    q = lambda texte: shlex.quote(str(texte))
    if MAC:
        lancer = f'open {q(cible)} --args {OPTION_RELANCE}'
        remplacer = (f'rm -rf {q(str(cible) + ".ancien")}; mv {q(cible)} {q(str(cible) + ".ancien")} && '
                     f'{{ mv {q(nouveau)} {q(cible)} || {{ mv {q(str(cible) + ".ancien")} {q(cible)}; false; }}; }}')
    else:
        lancer = f'nohup {q(cible)} {OPTION_RELANCE} >/dev/null 2>&1 &'
        remplacer = f'mv -f {q(nouveau)} {q(cible)} && chmod 755 {q(cible)}'
    vivants = ' || '.join([f'kill -0 {pid} 2>/dev/null' for pid in pids]
                          + [f'pgrep -f -- {q(str(d) + "/")} >/dev/null 2>&1' for d in moteurs]) or 'false'
    temporaires = ' '.join(q(t) for t in temporaires)
    return '\n'.join([
        '#!/bin/sh',
        f'journal={q(FICHIER_JOURNAL_MAJ)}',
        'noter() { printf \'%s %s\\n\' "$(date \'+%Y-%m-%dT%H:%M:%S\')" "$1" >> "$journal"; }',
        f'lancer() {{ {relance or lancer}; }}',
        'echouer() {',
        '  noter "echec : $1"',
        f'  printf \'%s\\n\' "$1" > {q(FICHIER_ECHEC_MAJ)}',
        f'  rm -rf -- {temporaires}' if temporaires else '  :',
        f'  [ -e {q(cible)} ] || mv {q(str(cible) + ".ancien")} {q(cible)} 2>/dev/null',
        '  # L\'ancienne version redemarre et montre l\'echec : jamais de retour en silence',
        f'  [ -e {q(cible)} ] && lancer',
        '  rm -f -- "$0"; exit 1',
        '}',
        f'noter {q("mise a jour de " + str(cible))}',
        '# Attend la fin de Prisme et des moteurs lances depuis son dossier',
        'n=0',
        f'while {vivants}; do n=$((n + 1)); [ "$n" -ge {attente * 2} ] && echouer {q(ECHEC_ATTENTE)}; sleep 0.5; done',
        'n=0',
        f'until {{ {remplacer}; }} 2>/dev/null; do n=$((n + 1)); [ "$n" -ge {essais} ] && echouer {q(ECHEC_REMPLACEMENT)}; sleep 2; done',
        f'rm -rf -- {q(str(cible) + ".ancien")} {temporaires}',
        'noter "remplacement fait"',
        'lancer',
        'rm -f -- "$0"',
    ]) + '\n'


def reprendre_apres_maj():
    """Au lancement : garde le message d'une mise a jour echouee (pour l'interface) et supprime les fichiers laisses
    par une mise a jour (telechargement, ancien programme encore utilise lors du remplacement)."""
    global echec_maj
    if FICHIER_ECHEC_MAJ.exists():
        message = FICHIER_ECHEC_MAJ.read_text(encoding='utf-8-sig', errors='replace').strip()
        echec_maj = {'message': message or 'La mise à jour a échoué.', 'url': PAGE_VERSIONS, 'journal': str(FICHIER_JOURNAL_MAJ)}
        FICHIER_ECHEC_MAJ.unlink(missing_ok=True)
    if EXE:
        programme = programme_actuel()
        for reste in [*programme.parent.glob('.prisme-maj-*'), *programme.parent.glob(programme.name + '.ancien*')]:
            try:
                shutil.rmtree(reste) if reste.is_dir() else reste.unlink()
            except OSError:
                pass  # encore utilise (serveur MCP de Claude) : ce sera pour le lancement suivant


def installer_mise_a_jour():
    suivi = mise_a_jour['installation']

    def avancer(octets):
        with verrou_maj:
            suivi['fait'] += octets

    try:
        fichier, cible = mise_a_jour['fichier'], programme_actuel()
        dossier = cible.parent
        if TRANSLOQUE:
            raise RuntimeError(DEPLACER_MAC)
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
        # Sous Windows et Linux, l'exe tourne dans deux processus (lanceur et Python) : on attend les deux, et les moteurs
        pids = [os.getpid()] + ([] if MAC else [os.getppid()])
        temporaires = [telechargement] + ([extrait] if MAC else [] if WINDOWS else [nouveau])
        texte = script_remplacement(nouveau, cible, pids, temporaires, [RACINE / 'sd', RACINE / 'llama'])
        script = Path(tempfile.gettempdir()) / f'prisme-maj-{os.getpid()}.{"ps1" if WINDOWS else "sh"}'
        # PowerShell 5 ne lit l'UTF-8 (chemins avec accents) qu'avec la marque d'ordre des octets
        script.write_text(texte, encoding='utf-8-sig' if WINDOWS else 'utf-8', newline='')
        # Sans cela, le nouveau Prisme heriterait des variables internes de l'exe actuel et se croirait son sous-processus
        environnement = {k: v for k, v in os.environ.items() if not k.startswith(('_PYI_', '_MEIPASS'))}
        environnement['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
        if WINDOWS:
            options = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            commande = ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-File', str(script)]
            try:
                # Hors du groupe de processus de Prisme, pour que le script survive a sa fermeture
                subprocess.Popen(commande, env=environnement, creationflags=options | subprocess.CREATE_BREAKAWAY_FROM_JOB)
            except OSError:
                subprocess.Popen(commande, env=environnement, creationflags=options)
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


def mode_edition(r):
    """Comment le modele de dessin choisi modifie une image : 'reference' (l'image seule, FLUX.2 klein), 'vision' (avec
    le fichier de vision du modele de texte, Qwen-Image) ou None (creation seulement, ou fichier de vision manquant)."""
    connu = next((m for m in MODELES_CONSEILLES if m['role_id'] == 'image' and m['fichier'] == r['modele_diffusion']), None)
    if connu and connu['edition'] == 'reference':
        return 'reference'
    if connu and connu['edition'] != 'vision':
        return None
    # Modele du catalogue qui passe par la vision, ou modele personnel : il faut le fichier de vision
    return 'vision' if r['modele_vision'] else None


def arguments(r, prompt, largeur, hauteur, seed, source, sortie, vision=True):
    edition = []
    if source:
        edition = (['--llm_vision', str(MODELES / r['modele_vision'])] if vision else []) + ['-r', str(source)]
    options = (['--sigmas', r['sigmas']] if r['sigmas'] else []) \
        + (['--diffusion-fa'] if r['flash_attention'] else []) \
        + (['--offload-to-cpu'] if r['dechargement_cpu'] else []) \
        + (['--vae-tiling'] if r['vae_tuiles'] else []) \
        + options_reserve_sd(r)
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


def nouveau_chemin(dossier=IMAGES):
    dossier.mkdir(exist_ok=True)
    base = 'image_' + datetime.now().strftime('%Y%m%d_%H%M%S')
    chemin = dossier / (base + '.png')
    n = 2
    while chemin.exists():
        chemin = dossier / f'{base}_{n}.png'
        n += 1
    return chemin


def force_lisible(force):
    """Force d'un LoRA telle que sd-cli l'ecrit (float32 : 0.800000011920929), arrondie : 0.8."""
    try:
        return f'{round(float(force), 2):g}'
    except ValueError:
        return force


def parametres_png(texte):
    """Conditions d'une creation, lues dans le bloc structure que sd-cli ecrit dans le PNG (schema sdcpp.generation/v1),
    ou None pour une image sans ce bloc (versions anciennes du moteur, image venue d'ailleurs)."""
    try:
        donnees = json.loads(texte.split('SDCPP: ', 1)[1])
    except (IndexError, ValueError):
        return None
    if not isinstance(donnees, dict):
        return None
    echantillon, modeles = donnees.get('sample_params') or {}, donnees.get('models') or {}
    loras = []
    for nom, force in BALISE_LORA.findall(texte.split('\nSteps:')[0]):
        try:
            # sd-cli ecrit la force en float32 (0.800000011920929)
            loras.append({'nom': nom, 'force': round(float(force), 2)})
        except ValueError:
            pass
    return {'loras': loras, 'etapes': echantillon.get('sample_steps'), 'cfg': (echantillon.get('guidance') or {}).get('txt_cfg'),
            'methode': echantillon.get('sample_method'), 'modele_diffusion': modeles.get('diffusion_model'),
            'modele_texte': modeles.get('llm'), 'vae': modeles.get('vae')}


def fichier_modele(nom):
    """Chemin, dans le dossier models, du fichier qu'une image nomme (sd-cli ne garde que son nom), ou None."""
    nom = str(nom or '').replace('\\', '/')
    if chemin_relatif_sur(nom) and (MODELES / nom).is_file():
        return nom
    return next((m['nom'] for m in lister_modeles() if m['nom'].rsplit('/', 1)[-1] == nom), None)


def reglages_d_une_creation(r, parametres):
    """Reglages pour une seule creation, avec les parametres d'une image a refaire : (reglages, erreur)."""
    if not isinstance(parametres, dict):
        return None, 'Paramètres invalides.'
    r = dict(r)
    for cle in ('modele_diffusion', 'modele_texte', 'vae'):
        if parametres.get(cle):
            r[cle] = fichier_modele(parametres[cle])
            if not r[cle]:
                return None, f'Modèle introuvable dans le dossier models : {parametres[cle]}'
    try:
        if parametres.get('etapes') is not None:
            r['etapes'] = int(parametres['etapes'])
        if parametres.get('cfg') is not None:
            r['cfg'] = float(parametres['cfg'])
    except (TypeError, ValueError):
        return None, 'Paramètres invalides.'
    if parametres.get('methode'):
        r['methode'] = str(parametres['methode'])
    # LoRA de cette creation (une liste vide : aucun) ; sd-cli les nomme sans extension
    if isinstance(parametres.get('loras'), list):
        loras = []
        for l in parametres['loras']:
            nom = str(l.get('nom') or '') if isinstance(l, dict) else ''
            fichier = next((x['nom'] for x in lister_loras() if nom in (x['nom'], Path(x['nom']).with_suffix('').as_posix())), None)
            if not fichier:
                return None, f'LoRA introuvable dans models/loras : {nom}'
            try:
                force = round(float(l.get('force', 1.0)), 2)
            except (TypeError, ValueError):
                return None, 'Paramètres invalides.'
            if not -2 <= force <= 2:
                return None, 'Paramètres invalides.'
            loras.append({'nom': fichier, 'force': force, 'actif': True})
        r['loras'] = loras
    if not 1 <= r['etapes'] <= 150 or not 0 <= r['cfg'] <= 30 or r['methode'] not in METHODES:
        return None, 'Paramètres invalides.'
    # Des sigmas reglees pour un autre nombre d'etapes ne vont plus : sd-cli choisit les siennes
    if r['sigmas'] and len(r['sigmas'].split(',')) != r['etapes'] + 1:
        r['sigmas'] = ''
    return r, None


def modeles_de_creation(profil):
    """Fichiers d'un profil qui servent a creer : sans la vision, utile seulement pour modifier une image."""
    return [MODELES_PAR_ID[i] for i in profil['modeles'] if MODELES_PAR_ID[i]['role_id'] != 'edition']


def reglages_du_profil(r, profil):
    """Reglages pour creer avec les modeles d'un profil (et les reglages conseilles de son modele de dessin), pour une
    comparaison : les Reglages ne changent pas."""
    r = dict(r)
    for m in modeles_de_creation(profil):
        for cle in m['remplit']:
            r[cle] = m['fichier']
        for cle in m.get('vide', []):
            r[cle] = ''
        if m.get('reglages') and 'modele_diffusion' in m['remplit']:
            r.update(m['reglages'])
    return r


def nom_du_profil(profil):
    """Nom du modele de dessin d'un profil, pour legender une comparaison."""
    m = next(MODELES_PAR_ID[i] for i in profil['modeles'] if 'modele_diffusion' in MODELES_PAR_ID[i]['remplit'])
    return f"{m['nom']} {m['quantification']}"


# --- Projets : {nom d'image: projet}, a cote des images
verrou_projets = threading.Lock()


def lire_projets():
    try:
        projets = json.loads((IMAGES / 'projets.json').read_text('utf-8'))
    except (OSError, ValueError):
        return {}
    return projets if isinstance(projets, dict) else {}


def ranger(noms, projet):
    """Range des images dans un projet ('' : dans aucun) ; les images qui n'existent plus sont oubliees."""
    with verrou_projets:
        projets = lire_projets()
        for nom in noms:
            if projet:
                projets[nom] = projet
            else:
                projets.pop(nom, None)
        projets = {n: p for n, p in projets.items() if (IMAGES / n).is_file()}
        IMAGES.mkdir(exist_ok=True)
        temporaire = IMAGES / 'projets.json.tmp'
        temporaire.write_text(json.dumps(projets, ensure_ascii=False, indent=1), 'utf-8')
        os.replace(temporaire, IMAGES / 'projets.json')


def nom_projet(valeur):
    """Nom de projet propre : espaces simplifies, 60 caracteres au plus."""
    return ' '.join(str(valeur or '').split())[:60]


def noter_dans_png(chemin, donnees):
    """Ajoute a une image le morceau texte « prisme » (JSON : duree, memoire, comparaison...), avant les pixels pour que
    lire_infos le trouve sans lire toute l'image."""
    morceaux = agrandir.morceaux_png(chemin.read_bytes())
    texte = agrandir.morceau_png(b'tEXt', b'prisme\x00' + json.dumps(donnees, ensure_ascii=True).encode())
    i = next(n for n, (genre, _) in enumerate(morceaux) if genre == b'IDAT')
    contenu = agrandir.SIGNATURE_PNG + b''.join(agrandir.morceau_png(g, c) for g, c in morceaux[:i]) + texte \
        + b''.join(agrandir.morceau_png(g, c) for g, c in morceaux[i:])
    temporaire = chemin.with_name(chemin.name + '.tmp')
    temporaire.write_bytes(contenu)
    os.replace(temporaire, chemin)


def lire_infos(chemin):
    """Lit taille, prompt et seed dans les metadonnees PNG ecrites par sd-cli."""
    statut = chemin.stat()
    mtime = statut.st_mtime
    # La taille aussi : sous Windows, une image reecrite aussitot (mesures ajoutees) peut garder la meme date
    cle = (statut.st_mtime_ns, statut.st_size)
    connu = cache_infos.get(chemin.name)
    if connu and connu[0] == cle:
        return connu[1]

    infos = {'nom': chemin.name, 'prompt': '', 'seed': None, 'loras': [], 'largeur': 0, 'hauteur': 0, 'parametres': None,
             'mesures': None,
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
                        infos['loras'] = [f'{nom} ({force_lisible(force)})' for nom, force in BALISE_LORA.findall(prompt)]
                        infos['prompt'] = BALISE_LORA.sub('', prompt).strip()
                        seed = re.search(r'Seed: (-?\d+)', texte)
                        if seed:
                            infos['seed'] = int(seed.group(1))
                        infos['parametres'] = parametres_png(texte)
                    elif genre == b'tEXt' and donnees.startswith(b'prisme\x00'):
                        try:
                            infos['mesures'] = json.loads(donnees[len(b'prisme\x00'):])
                        except ValueError:
                            pass
    except OSError:
        pass
    cache_infos[chemin.name] = (cle, infos)
    return infos


def lister_images():
    if not IMAGES.exists():
        return []
    fichiers = sorted(IMAGES.glob('*.png'), key=lambda p: p.stat().st_mtime, reverse=True)
    projets = lire_projets()
    return [{**lire_infos(p), 'projet': projets.get(p.name, '')} for p in fichiers]


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

        # Une comparaison : les memes description et variante, avec les reglages de chaque profil
        liste = params.get('liste_reglages') or [r] * params['nombre']
        mode = mode_edition(r) if source else None
        if source and not mode:
            raise RuntimeError('Ces modèles ne savent pas modifier une image : choisis un profil qui sait le faire '
                               '(FLUX.2 klein ou Qwen-Image) dans la fenêtre des modèles.')
        for r in liste:
            manquants = modeles_manquants(r, mode == 'vision')
            if manquants:
                raise RuntimeError('Modèle introuvable dans le dossier models : ' + ', '.join(manquants) + '. Vérifie les réglages.')

        for i in range(params['nombre']):
            if annule:
                break
            r = liste[i]
            seed = params['seed'] + (0 if params.get('comparaison') else i)
            sortie = nouveau_chemin(IMAGES_CLAUDE if params['claude'] else IMAGES)
            with verrou:
                etat.update(phase='chargement', etape=0, total=r['etapes'], index=i + 1, seed=seed, debut_image=time.time())
            journal = deque(maxlen=80)
            processus = lancer_moteur(
                [str(SD_CLI)] + arguments(r, params['prompt'], params['largeur'], params['hauteur'], seed, source, sortie,
                                          vision=mode == 'vision'),
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
                    pas = agrandir.PAS.findall(ligne)
                    if pas:
                        fait, total = map(int, pas[-1])
                        with verrou:
                            if total == r['etapes'] and etat['phase'] != 'finalisation':
                                etat.update(phase='finalisation' if fait >= total else 'dessin', etape=fait)
                            elif etat['phase'] == 'dessin':
                                etat['phase'] = 'finalisation'
            code, memoire = attendre_moteur(processus)

            if annule:
                sortie.unlink(missing_ok=True)
                break
            if code != 0 or not sortie.exists():
                erreurs = [l for l in journal if re.search(r'^\[E\]|error|out of memory', l, re.I)]
                with verrou:
                    etat['erreur'] = '\n'.join(erreurs[-3:]) or f'sd-cli s\'est arrete (code {code}).'
                break
            # Mesures de cette creation, gardees dans l'image : combien de temps et de memoire sur cet ordinateur
            mesures = {'duree': round(time.time() - etat['debut_image'], 1), 'memoire': memoire}
            if params.get('comparaison'):
                mesures['comparaison'] = params['comparaison'][i]
            try:
                noter_dans_png(sortie, mesures)
            except (OSError, ValueError, StopIteration):
                pass
            if params.get('projet') and not params['claude']:
                ranger([sortie.name], params['projet'])
            with verrou:
                etat['resultats'].append(sortie.name)
    except Exception as e:
        with verrou:
            etat['erreur'] = str(e)
    finally:
        if source_temp:
            source_temp.unlink(missing_ok=True)
        terminer_calcul()


def terminer_calcul():
    """Fin d'une creation ou d'un agrandissement : Prisme redevient libre."""
    global processus
    processus = None
    with verrou:
        etat['occupe'] = False
        etat['phase'] = 'annule' if annule else ('erreur' if etat.get('erreur') else 'termine')
        etat['fin'] = time.time()


# Agrandissement : le modele choisi dans les reglages, ou celui du catalogue s'il est dans le dossier models
AGRANDISSEMENT = next(m for m in MODELES_CONSEILLES if m['role_id'] == 'agrandissement')


def modele_agrandissement(r):
    nom = r.get(agrandir.CLE) or AGRANDISSEMENT['fichier']
    return MODELES / nom if chemin_relatif_sur(nom) and (MODELES / nom).is_file() else None


def generer_agrandissement(params):
    """Agrandit une image de la galerie x4 dans une nouvelle image ; meme etat, meme annulation que les creations."""
    global processus
    source, sortie = params['source'], params['sortie']

    def lancer(commande):
        global processus
        processus = lancer_moteur(commande, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=str(RACINE))
        return processus

    def rapporter(**champs):
        with verrou:
            etat.update(champs)

    try:
        commande = [str(SD_CLI)] + agrandir.arguments(params['modele'], source, sortie) + options_reserve_sd(params['reglages'])
        code, erreurs = agrandir.executer(commande, lancer, rapporter, lambda: annule)
        if annule:
            sortie.unlink(missing_ok=True)
        elif code != 0 or not sortie.exists():
            with verrou:
                etat['erreur'] = '\n'.join(erreurs[-3:]) or f'sd-cli s\'est arrete (code {code}).'
        else:
            agrandir.copier_description(source, sortie)
            if lire_projets().get(source.name):
                ranger([sortie.name], lire_projets()[source.name])
            with verrou:
                etat['resultats'].append(sortie.name)
    except Exception as e:
        with verrou:
            etat['erreur'] = str(e)
    finally:
        terminer_calcul()


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

    def vient_du_mcp(self):
        return self.headers.get('X-Prisme-Client') == 'mcp'

    def noter_contact_local(self):
        global dernier_contact_local, fermeture_demandee, dernier_contact_fenetre, dernier_contact_mcp
        if not self.est_local():
            return
        if self.vient_du_mcp():
            dernier_contact_mcp = time.time()
            return
        dernier_contact_local = dernier_contact_fenetre = time.time()
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

    def send_response(self, *args, **kwargs):
        self.repondu = True
        super().send_response(*args, **kwargs)

    def proteger(self, traitement):
        """Une erreur imprevue recoit quand meme une reponse : sans elle, la fenetre croirait Prisme plante."""
        self.repondu = False
        try:
            traitement()
        except (BrokenPipeError, ConnectionResetError):
            pass  # l'appareil est parti avant la reponse
        except Exception as e:
            if self.repondu:
                raise
            self.envoyer(500, {'erreur': f'Erreur inattendue dans Prisme : {e}'})

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
        self.proteger(self.traiter_get)

    def traiter_get(self):
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
            reglages = lire_reglages()
            self.envoyer(200, {'reglages': reglages, 'version': version_reglages(),
                               'edition_possible': mode_edition(reglages) is not None,
                               'defauts': REGLAGES_DEFAUT, 'modeles': lister_modeles(),
                               'methodes': METHODES, 'dossier': str(MODELES),
                               'loras': lister_loras(), 'dossier_loras': str(LORAS)})
        elif chemin == '/api/images':
            self.envoyer(200, lister_images())
        elif chemin == '/api/modeles-conseilles':
            if not self.est_local():
                return self.envoyer(403, {'erreur': 'Disponible seulement sur le PC.'})
            self.envoyer(200, etat_modeles_conseilles())
        elif chemin == '/api/loras/bibliotheque':
            # Bibliotheque de LoRA : seulement sur le PC, et pas pour Claude
            if not self.est_local() or self.vient_du_mcp():
                return self.envoyer(403, {'erreur': 'Disponible seulement sur le PC.'})
            recherche = ' '.join(parse_qs(url.query).get('q', [''])[0].split())[:80]
            try:
                self.envoyer(200, bibliotheque_loras(lire_reglages(), recherche))
            except RuntimeError as e:
                self.envoyer(502, {'erreur': str(e)})
        elif chemin == '/api/consentement':
            if not self.est_local():
                return self.envoyer(403, {'erreur': 'Disponible seulement sur le PC.'})
            with verrou_consentements:
                demande = consentements.get(parse_qs(url.query).get('id', [''])[0])
                if demande and demande['etat'] == 'attente' and time.time() - demande['cree'] > DUREE_CONSENTEMENT:
                    demande['etat'] = 'expiree'
            if not demande:
                return self.envoyer(404, {'erreur': 'Demande inconnue.'})
            self.envoyer(200, {'etat': demande['etat'], 'telechargements': demande['telechargements']})
        elif chemin == '/api/claude':
            if not self.est_local():
                return self.envoyer(403, {'erreur': 'Disponible seulement sur le PC.'})
            self.envoyer(200, etat_claude())
        elif chemin == '/api/profils':
            if not self.est_local():
                return self.envoyer(403, {'erreur': 'Disponible seulement sur le PC.'})
            self.envoyer(200, etat_profils())
        elif chemin == '/api/etat':
            with verrou:
                copie = dict(etat)
            # La fenetre ne voit pas les images de Claude (hors de sa galerie) ; Claude ne voit pas celles de Prisme
            if bool(copie.get('claude')) != self.vient_du_mcp():
                copie['resultats'] = []
                if self.vient_du_mcp():
                    copie.pop('prompt', None)
            debut = copie.get('debut')
            if debut:
                copie['ecoule'] = round((copie.get('fin') if not copie['occupe'] else time.time()) - debut, 1)
            copie['local'] = self.est_local()
            r = lire_reglages()
            copie['modele'] = r['modele_diffusion']
            copie['version'] = VERSION
            copie['fenetre'] = FENETRE
            copie['problemes'] = problemes_configuration(r)
            copie['amelioration'] = {'modele': amelioration_active(r), 'auto': r['amelioration_auto']}
            copie['moteurs'] = etat_moteurs()
            copie['agrandissement'] = {'pret': modele_agrandissement(r) is not None, 'id': AGRANDISSEMENT['id'],
                                       'taille': AGRANDISSEMENT['taille'], 'licence': AGRANDISSEMENT['licence']['nom']}
            if self.est_local():
                with verrou_demandes:
                    copie['demandes'] = [{'id': i, 'ip': d['ip'], 'appareil': d['appareil'], 'code': d['code']}
                                         for i, d in demandes.items()
                                         if d['etat'] == 'attente' and time.time() - d['cree'] <= DUREE_DEMANDE]
                copie['mise_a_jour'] = etat_mise_a_jour()
                copie['maj_echec'] = echec_maj
                with verrou_consentements:
                    copie['consentements'] = [{'id': i, 'genre': d['genre'], 'details': d['details']}
                                              for i, d in consentements.items()
                                              if d['etat'] == 'attente' and time.time() - d['cree'] <= DUREE_CONSENTEMENT]
                copie['telechargements'] = resume_telechargements()
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
        elif chemin.startswith(('/images/', '/images-claude/')):
            claude = chemin.startswith('/images-claude/')
            if claude != self.vient_du_mcp() or (claude and not self.est_local()):
                return self.envoyer(403, {'erreur': 'Image réservée.'})
            nom = unquote(chemin.split('/', 2)[2])
            fichier = (IMAGES_CLAUDE if claude else IMAGES) / nom
            if NOM_IMAGE.match(nom) and fichier.exists():
                self.envoyer(200, fichier.read_bytes(), 'image/png', cache=True)
            else:
                self.envoyer(404, {'erreur': 'Image introuvable'})
        else:
            self.envoyer(404, {'erreur': 'Introuvable'})

    def do_POST(self):
        self.corps_lu = False
        self.proteger(self.traiter_requete_post)

    def traiter_requete_post(self):
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
                modele = str(p.get('modele') or '')
                comparer = [str(x) for x in p.get('comparer') or []]
                projet = nom_projet(p.get('projet'))
            except (ValueError, TypeError, json.JSONDecodeError):
                return self.envoyer(400, {'erreur': 'Paramètres invalides.'})
            if not prompt:
                return self.envoyer(400, {'erreur': 'Écris d\'abord ce que tu veux obtenir.'})
            if not (256 <= largeur <= 2048 and 256 <= hauteur <= 2048) or largeur % 16 or hauteur % 16:
                return self.envoyer(400, {'erreur': 'Taille invalide : multiples de 16, entre 256 et 2048.'})

            r = lire_reglages()
            # Refaire une image : ses modeles, etapes, CFG et methode, pour cette creation seulement
            if p.get('parametres'):
                r, erreur = reglages_d_une_creation(r, p['parametres'])
                if erreur:
                    return self.envoyer(400, {'erreur': erreur})
            # Modele de dessin choisi pour cette creation seulement (serveur MCP) ; les reglages ne changent pas
            if modele:
                if not chemin_relatif_sur(modele) or not (MODELES / modele).is_file():
                    return self.envoyer(400, {'erreur': 'Modèle introuvable dans le dossier models.'})
                r = {**r, 'modele_diffusion': modele}
            # Comparer des modeles : une image par profil installe, meme description, meme variante
            liste_reglages = comparaison = None
            if comparer:
                profils = [next((x for x in PROFILS if x['id'] == i), None) for i in comparer]
                if not 2 <= len(comparer) <= 4 or len(set(comparer)) != len(comparer) or None in profils:
                    return self.envoyer(400, {'erreur': 'Choisis de 2 à 4 profils différents à comparer.'})
                if any(not (MODELES / m['fichier']).is_file() for x in profils for m in modeles_de_creation(x)):
                    return self.envoyer(400, {'erreur': 'Télécharge d\'abord les modèles de chaque profil à comparer.'})
                if p.get('source_nom') or p.get('source_data'):
                    return self.envoyer(400, {'erreur': 'La comparaison crée à partir d\'une description, sans image de départ.'})
                liste_reglages = [reglages_du_profil(r, x) for x in profils]
                comparaison = [nom_du_profil(x) for x in profils]
                nombre = len(profils)
            claude = self.vient_du_mcp()
            with verrou:
                if etat['occupe']:
                    return self.envoyer(409, {'erreur': 'Une génération est déjà en cours.'})
                if amelioration_en_cours.locked():
                    return self.envoyer(409, {'erreur': 'Attends la fin de l\'amélioration de la description.'})
                annule = False
                etat.clear()
                etat.update(occupe=True, phase='chargement', etape=0, total=r['etapes'], index=1, nombre=nombre,
                            seed=seed, seed_base=seed, debut=time.time(), resultats=[], erreur=None,
                            largeur=largeur, hauteur=hauteur, prompt=prompt, claude=claude)
            # Claude n'envoie que ses propres images (source_data), jamais un nom d'image de Prisme
            params = dict(prompt=prompt, largeur=largeur, hauteur=hauteur, nombre=nombre, seed=seed, reglages=r,
                          source_nom=None if claude else p.get('source_nom'), source_data=p.get('source_data'),
                          claude=claude, liste_reglages=liste_reglages, comparaison=comparaison, projet=projet)
            threading.Thread(target=generer, args=(params,), daemon=True).start()
            self.envoyer(200, {'seed': seed})

        elif chemin == '/api/agrandir':
            nom = str(self.lire_json().get('nom') or '')
            if not NOM_IMAGE.match(nom) or not (IMAGES / nom).is_file():
                return self.envoyer(404, {'erreur': 'Image introuvable.'})
            if self.vient_du_mcp():
                return self.envoyer(403, {'erreur': 'Les images de Prisme ne sont pas accessibles à Claude.'})
            r = lire_reglages()
            modele = modele_agrandissement(r)
            if not modele:
                return self.envoyer(409, {'erreur': 'Télécharge d\'abord le modèle d\'agrandissement.', 'telecharger': AGRANDISSEMENT['id']})
            taille = agrandir.taille_png(IMAGES / nom)
            if not taille or max(taille) > agrandir.COTE_MAX_SOURCE:
                return self.envoyer(400, {'erreur': f'Image trop grande pour être agrandie (plus de {agrandir.COTE_MAX_SOURCE} pixels de côté).'})
            sortie = nouveau_chemin(IMAGES)
            with verrou:
                if etat['occupe']:
                    return self.envoyer(409, {'erreur': 'Une génération est déjà en cours.'})
                if amelioration_en_cours.locked():
                    return self.envoyer(409, {'erreur': 'Attends la fin de l\'amélioration de la description.'})
                annule = False
                etat.clear()
                etat.update(occupe=True, genre='agrandissement', phase='chargement', etape=0, total=0, index=1, nombre=1,
                            debut=time.time(), resultats=[], erreur=None, source=nom, claude=False,
                            largeur=taille[0] * agrandir.FACTEUR, hauteur=taille[1] * agrandir.FACTEUR)
            params = dict(source=IMAGES / nom, sortie=sortie, modele=modele, reglages=r)
            threading.Thread(target=generer_agrandissement, args=(params,), daemon=True).start()
            self.envoyer(200, {'largeur': taille[0] * agrandir.FACTEUR, 'hauteur': taille[1] * agrandir.FACTEUR})

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
            with verrou:
                libre = not etat.get('occupe') and amelioration_en_cours.acquire(blocking=False)
            if not libre:
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

        elif chemin == '/api/montrer-fenetre':
            # Prisme relance alors qu'il tourne deja : sa fenetre reapparait au lieu d'en ouvrir une seconde
            if not self.est_local() or self.vient_du_mcp():
                return self.envoyer(403, {'erreur': 'Disponible seulement sur le PC.'})
            afficher_fenetre()
            self.envoyer(200, {})

        elif chemin == '/api/verifier-mise-a-jour':
            if not self.est_local():
                return self.envoyer(403, {'erreur': 'Disponible seulement sur le PC.'})
            try:
                verifier_mise_a_jour(discret=False)
            except Exception:
                return self.envoyer(502, {'erreur': 'GitHub ne répond pas. Vérifie ta connexion, puis réessaie.'})
            self.envoyer(200, {'version': VERSION, 'mise_a_jour': etat_mise_a_jour()})

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
            donnees = self.lire_json()
            ident = str(donnees.get('id') or '')
            if ident not in MODELES_PAR_ID:
                return self.envoyer(400, {'erreur': 'Modèle inconnu.'})
            if chemin == '/api/telecharger-modele':
                modele = MODELES_PAR_ID[ident]
                deja = (MODELES / modele['fichier']).is_file()
                if not modele['licence']['commercial'] and not deja and donnees.get('licence_acceptee') is not True:
                    return self.envoyer(400, {'erreur': f'Accepte d\'abord la licence de ce modèle ({modele["licence"]["nom"]} : '
                                                        'pas d\'usage commercial).'})
                demander_modele(ident)
            else:
                with verrou_modeles:
                    if ident in telechargements_modeles:
                        telechargements_modeles[ident]['annule'] = True
            self.envoyer(200, {})

        elif chemin == '/api/utiliser-modele':
            # Choisir un modele pour un role depuis la fenetre des modeles, comme dans les Reglages : seulement sur le PC
            if not self.est_local() or self.vient_du_mcp():
                return self.envoyer(403, {'erreur': 'Disponible seulement dans la fenêtre de Prisme sur le PC.'})
            donnees = self.lire_json()
            try:
                utiliser_fichier(donnees.get('nom') or '', str(donnees.get('role') or ''))
            except ValueError as e:
                return self.envoyer(400, {'erreur': str(e)})
            self.envoyer(200, {})

        elif chemin == '/api/supprimer-modele':
            # Seulement depuis la fenetre de Prisme sur le PC : ni le telephone, ni Claude ne suppriment de modele
            if not self.est_local() or self.vient_du_mcp():
                return self.envoyer(403, {'erreur': 'Disponible seulement dans la fenêtre de Prisme sur le PC.'})
            with verrou:
                occupe = etat.get('occupe')
            if occupe or amelioration_en_cours.locked():
                return self.envoyer(409, {'erreur': 'Attends la fin du calcul en cours avant de supprimer un modèle.'})
            try:
                libere = supprimer_modele(self.lire_json().get('nom') or '')
            except ValueError as e:
                return self.envoyer(404, {'erreur': str(e)})
            except (RuntimeError, OSError) as e:
                return self.envoyer(409, {'erreur': str(e)})
            self.envoyer(200, {'libere': libere})

        elif chemin == '/api/demander-telechargement':
            # Claude demande un telechargement qui demande l'accord de l'utilisateur dans la fenetre de Prisme
            if not self.est_local():
                return self.envoyer(403, {'erreur': 'Disponible seulement sur le PC.'})
            donnees = self.lire_json()
            if donnees.get('profil'):
                profil = next((x for x in PROFILS if x['id'] == donnees['profil']), None)
                if not profil:
                    return self.envoyer(400, {'erreur': 'Profil inconnu.'})
                if not profil['licence_a_accepter']:
                    return self.envoyer(400, {'erreur': 'Ce profil n\'a pas de licence à accepter : télécharge ses fichiers directement.'})
                licence = next(MODELES_PAR_ID[i]['licence'] for i in profil['modeles'] if not MODELES_PAR_ID[i]['licence']['commercial'])
                details = {'profil': profil['id'], 'nom': profil['nom'], 'licence': licence,
                           'taille': sum(MODELES_PAR_ID[i]['taille'] for i in profil['modeles']
                                         if not (MODELES / MODELES_PAR_ID[i]['fichier']).is_file())}
                genre = 'profil'
            else:
                try:
                    details = preparer_externe(donnees.get('url'), donnees.get('role') or None)
                except (ValueError, RuntimeError) as e:
                    return self.envoyer(400, {'erreur': str(e)})
                genre = 'externe'
            try:
                ident = creer_consentement(genre, details)
            except OverflowError:
                return self.envoyer(429, {'erreur': 'Trop de demandes en attente dans la fenêtre de Prisme.'})
            self.envoyer(200, {'id': ident, 'details': details, 'expire': DUREE_CONSENTEMENT})

        elif chemin == '/api/repondre-consentement':
            # Seule la fenetre de Prisme repond : le serveur MCP ne peut pas accepter a la place de l'utilisateur
            if not self.est_local() or self.vient_du_mcp():
                return self.envoyer(403, {'erreur': 'Disponible seulement dans la fenêtre de Prisme.'})
            donnees = self.lire_json()
            with verrou_consentements:
                demande = consentements.get(str(donnees.get('id') or ''))
                if not demande or demande['etat'] != 'attente' or time.time() - demande['cree'] > DUREE_CONSENTEMENT:
                    return self.envoyer(404, {'erreur': 'Cette demande a expiré.'})
                demande['etat'] = 'acceptee' if donnees.get('accepter') is True else 'refusee'
            if demande['etat'] == 'acceptee':
                executer_consentement(demande)
            self.envoyer(200, {'etat': demande['etat']})

        elif chemin == '/api/connecter-claude':
            if not self.est_local() or self.vient_du_mcp():
                return self.envoyer(403, {'erreur': 'Disponible seulement dans la fenêtre de Prisme.'})
            donnees = self.lire_json()
            retirer = donnees.get('retirer') is True
            if TRANSLOQUE and not retirer:
                return self.envoyer(409, {'erreur': DEPLACER_MAC})
            faits, erreurs = [], []
            for dossier in dossiers_claude_desktop():
                try:
                    connecter_claude_desktop(dossier, retirer)
                    faits.append('desktop')
                except (OSError, RuntimeError) as e:
                    erreurs.append(str(e))
            if shutil.which('claude'):
                try:
                    connecter_claude_code(retirer)
                    faits.append('code')
                except (OSError, RuntimeError, subprocess.SubprocessError) as e:
                    erreurs.append(str(e))
            if not faits and not erreurs:
                return self.envoyer(404, {'erreur': 'Claude n\'est pas installé sur cet ordinateur.'})
            self.envoyer(200 if faits else 500, {'faits': faits, 'erreurs': erreurs, 'claude': etat_claude()})

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

        elif chemin == '/api/loras/telecharger':
            if not self.est_local() or self.vient_du_mcp():
                return self.envoyer(403, {'erreur': 'Disponible seulement sur le PC.'})
            donnees = self.lire_json()
            depot, fichier, nombre = str(donnees.get('id') or ''), str(donnees.get('fichier') or ''), donnees.get('nombre') or 1
            if not ID_DEPOT.fullmatch(depot) or not re.fullmatch(r'[\w.+-]+\.safetensors', fichier) or not isinstance(nombre, int):
                return self.envoyer(400, {'erreur': 'LoRA invalide.'})
            try:
                details = preparer_externe(f'https://huggingface.co/{depot}/resolve/main/{fichier}', 'lora',
                                           nom_fichier_lora(depot, fichier, nombre))
            except (ValueError, RuntimeError) as e:
                return self.envoyer(400, {'erreur': str(e)})
            # Sans empreinte, le fichier ne pourrait pas etre verifie apres le telechargement
            if not details['sha256']:
                return self.envoyer(400, {'erreur': 'Hugging Face ne donne pas l\'empreinte de ce fichier : téléchargement refusé.'})
            ident = ajouter_externe(details)
            demander_modele(ident)
            cache_bibliotheque.clear()
            self.envoyer(200, {'id': ident, 'fichier': details['fichier'], 'taille': details['taille']})

        elif chemin == '/api/projet':
            if self.vient_du_mcp():
                return self.envoyer(403, {'erreur': 'Les images de Prisme ne sont pas accessibles à Claude.'})
            donnees = self.lire_json()
            noms = donnees.get('noms')
            if not isinstance(noms, list) or not noms or any(not isinstance(n, str) or not NOM_IMAGE.match(n)
                                                             or not (IMAGES / n).is_file() for n in noms):
                return self.envoyer(404, {'erreur': 'Image introuvable.'})
            ranger(noms, nom_projet(donnees.get('projet')))
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
                    tuer_arbre(processus)
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
            with verrou_reglages:
                # Un telechargement ou une suppression a change les modeles pendant que la fenetre Reglages etait ouverte
                if donnees.get('version') is not None and str(donnees['version']) != version_reglages():
                    return self.envoyer(409, {'erreur': 'Les réglages ont changé pendant que la fenêtre était ouverte '
                                                        '(un modèle a été choisi ou supprimé) : rouvre les Réglages.'})
                r, erreur = valider_reglages(donnees)
                if erreur:
                    return self.envoyer(400, {'erreur': erreur})
                ecrire_reglages(r)
            self.envoyer(200, {'reglages': r, 'version': version_reglages()})

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


def dossiers_claude_desktop():
    """Dossiers de configuration de Claude Desktop presents sur cette machine (version classique et Microsoft Store)."""
    if WINDOWS:
        local = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local')
        # Les versions recentes de Claude Desktop gardent leurs donnees (et leur configuration) dans
        # Claude-Data\claude_<paquet> : l'ancien dossier AppData\Roaming\Claude n'y est alors plus lu
        recents = sorted(d for d in local.glob('Claude-Data/claude_*') if (d / 'claude_desktop_config.json').is_file())
        if recents:
            return recents
        candidats = [Path(os.environ.get('APPDATA') or Path.home() / 'AppData' / 'Roaming') / 'Claude']
        paquets = local / 'Packages'
        candidats += sorted(paquets.glob('Claude_*/LocalCache/Roaming/Claude')) if paquets.is_dir() else []
    elif MAC:
        candidats = [Path.home() / 'Library' / 'Application Support' / 'Claude']
    else:
        candidats = [Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'Claude']
    return [d for d in candidats if d.is_dir()]


def commande_mcp():
    """Comment Claude lance le serveur MCP de Prisme : ce programme lui-meme, avec --mcp."""
    if EXE:
        # L'ecran de demarrage de l'exe ne doit pas s'afficher a chaque lancement de Claude
        entree = {'command': sys.executable, 'args': ['--mcp'], 'env': {'PYINSTALLER_SUPPRESS_SPLASH_SCREEN': '1'}}
    else:
        entree = {'command': sys.executable, 'args': [str(Path(__file__).resolve()), '--mcp'], 'env': {}}
    if PORT != 7861:
        entree['env']['PRISME_URL'] = f'http://127.0.0.1:{PORT}'
    if os.environ.get('PRISME_RACINE'):
        entree['env']['PRISME_RACINE'] = str(RACINE)
    if not entree['env']:
        del entree['env']
    return entree


def lire_json_claude(fichier):
    if not fichier.exists():
        return {}
    donnees = json.loads(fichier.read_text(encoding='utf-8-sig') or '{}')
    if not isinstance(donnees, dict):
        raise ValueError
    return donnees


def etat_claude():
    """Claude Desktop et Claude Code sont-ils sur cette machine, et Prisme y est-il deja branche ?"""
    attendu = commande_mcp()
    desktop = []
    for dossier in dossiers_claude_desktop():
        try:
            entree = lire_json_claude(dossier / 'claude_desktop_config.json').get('mcpServers', {}).get('prisme')
        except (OSError, ValueError):
            entree = None
        desktop.append('connecte' if entree == attendu else 'ancien' if entree else 'absent')
    code_cli = shutil.which('claude')
    try:
        entree_code = lire_json_claude(Path.home() / '.claude.json').get('mcpServers', {}).get('prisme')
    except (OSError, ValueError):
        entree_code = None
    return {'desktop': bool(desktop), 'desktop_connecte': bool(desktop) and all(e == 'connecte' for e in desktop),
            'desktop_a_mettre_a_jour': 'ancien' in desktop,
            'code': bool(code_cli or entree_code), 'code_connecte': bool(entree_code)
            and entree_code.get('command') == attendu['command'] and entree_code.get('args') == attendu['args'],
            'commande': attendu}


def connecter_claude_desktop(dossier, retirer=False):
    """Ajoute (ou retire) Prisme dans la configuration de Claude Desktop, en gardant une copie de l'original."""
    fichier = dossier / 'claude_desktop_config.json'
    try:
        donnees = lire_json_claude(fichier)
    except ValueError:
        raise RuntimeError(f'La configuration de Claude est illisible, Prisme n\'y touche pas : {fichier}') from None
    serveurs = donnees.setdefault('mcpServers', {})
    if not isinstance(serveurs, dict):
        raise RuntimeError(f'La configuration de Claude est inattendue, Prisme n\'y touche pas : {fichier}')
    if retirer:
        if 'prisme' not in serveurs:
            return
        del serveurs['prisme']
    else:
        serveurs['prisme'] = commande_mcp()
    sauvegarde = fichier.with_name('claude_desktop_config.avant-prisme.json')
    if fichier.exists() and not sauvegarde.exists():
        shutil.copy2(fichier, sauvegarde)
    provisoire = fichier.with_name(fichier.name + '.prisme')
    provisoire.write_text(json.dumps(donnees, indent=2, ensure_ascii=False), encoding='utf-8')
    provisoire.replace(fichier)


def connecter_claude_code(retirer=False):
    """Branche Prisme dans Claude Code (portee utilisateur) avec sa propre commande `claude mcp`."""
    claude = shutil.which('claude')
    if not claude:
        raise RuntimeError('Claude Code est introuvable (commande claude).')
    subprocess.run([claude, 'mcp', 'remove', '--scope', 'user', 'prisme'], capture_output=True, timeout=60,
                   creationflags=SANS_CONSOLE)
    if retirer:
        return
    c = commande_mcp()
    options = [x for cle, valeur in c.get('env', {}).items() for x in ('-e', f'{cle}={valeur}')]
    fin = subprocess.run([claude, 'mcp', 'add', '--scope', 'user', *options, 'prisme', '--', c['command'], *c['args']],
                         capture_output=True, text=True, timeout=60, creationflags=SANS_CONSOLE)
    if fin.returncode != 0:
        raise RuntimeError('Claude Code a refusé la connexion : ' + (fin.stderr or fin.stdout).strip()[:300])


# Fenetre de Prisme : 'web' (navigateur), 'qt-chargement' puis 'qt' (Prisme 2). Avec Qt, MONTRER_FENETRE la montre ;
# une demande arrivee pendant le chargement attend qu'elle soit prete (MONTRER_A_LA_FIN)
FENETRE = 'web'
MONTRER_FENETRE = None
MONTRER_A_LA_FIN = False


def afficher_fenetre():
    """Montre la fenetre de Prisme : la fenetre Qt (cachee, ou encore en chargement) apparait, sinon une fenetre web s'ouvre."""
    global MONTRER_A_LA_FIN
    if MONTRER_FENETRE:
        MONTRER_FENETRE()
    elif FENETRE == 'qt-chargement':
        MONTRER_A_LA_FIN = True
    else:
        ouvrir_fenetre()


def ouvrir_fenetre():
    adresse = f'http://127.0.0.1:{PORT}/'
    navigateur = navigateur_application()
    if navigateur:
        subprocess.Popen([str(navigateur), f'--app={adresse}', '--window-size=1440,920'])
    else:
        import webbrowser
        webbrowser.open(adresse)


def arreter():
    """Arrete Prisme et les moteurs qu'il a lances, avec tout ce qu'ils ont eux-memes lance."""
    for moteur in (processus, processus_texte):
        if moteur and moteur.poll() is None:
            tuer_arbre(moteur)
    if WINDOWS and _job:
        _noyau.TerminateJobObject(ctypes.c_void_p(_job), 1)
    FICHIER_MOTEURS.unlink(missing_ok=True)
    os._exit(0)


def telechargement_en_cours():
    """Modele, moteur ou mise a jour en train de se telecharger ou de s'installer : Prisme doit rester ouvert."""
    with verrou_modeles:
        if any(t['phase'] in ('attente', 'telechargement', 'verification') for t in telechargements_modeles.values()):
            return True
    with verrou_installations:
        if any(i.get('phase') in ('telechargement', 'extraction') for i in installations.values()):
            return True
    with verrou_maj:
        return (mise_a_jour.get('installation') or {}).get('phase') in ('telechargement', 'installation')


def doit_s_arreter(maintenant, reglages):
    """Vrai si le serveur doit s'arreter : inactivite trop longue, ou fenetre du PC fermee et pas rouverte."""
    if etat.get('occupe') or amelioration_en_cours.locked() or telechargement_en_cours():
        return False
    if maintenant - dernier_contact > reglages['arret_auto_minutes'] * 60:
        return True
    # Fenetre fermee (elle l'a dit, ou ne donne plus de nouvelles) : arret, sauf si Claude se sert de Prisme en ce moment
    fermee = bool(fermeture_demandee and dernier_contact_local <= fermeture_demandee
                  and maintenant - fermeture_demandee > DELAI_FERMETURE)
    muette = bool(dernier_contact_fenetre and maintenant - dernier_contact_fenetre > SILENCE_FENETRE)
    return bool(reglages['arret_fermeture'] and (fermee or muette) and maintenant - dernier_contact_mcp > DELAI_MCP)


def surveiller():
    while True:
        time.sleep(2)
        if doit_s_arreter(time.time(), lire_reglages()):
            arreter()


def fermer_demarrage(delai=0.0):
    """Ferme l'ecran de demarrage de l'exe, apres un court delai pour laisser la fenetre apparaitre."""
    # Seul l'exe Windows en a un ; ailleurs, importer pyi_splash affiche une erreur inutile
    if not (WINDOWS and EXE):
        return
    try:
        import pyi_splash
    except ImportError:
        return
    threading.Timer(delai, pyi_splash.close).start()


# Instance unique : un seul serveur par dossier de donnees et par port (une version de travail peut tourner a cote)
_instance = None


def nom_instance():
    return 'Prisme-' + hashlib.sha256(f'{RACINE}|{PORT}'.encode()).hexdigest()[:16]


def prendre_instance():
    """Vrai si ce processus devient le seul Prisme de ce dossier, faux si un autre tourne deja.
    Windows : mutex nomme, libere par le systeme a la fin du processus ; Linux et Mac : verrou flock sur un fichier
    qui garde le PID, libere de meme, meme apres un plantage."""
    global _instance
    if WINDOWS:
        noyau = ctypes.WinDLL('kernel32', use_last_error=True)
        noyau.CreateMutexW.restype = ctypes.c_void_p
        poignee = noyau.CreateMutexW(None, False, 'Local\\' + nom_instance())
        if not poignee:
            return True  # mutex refuse par le systeme : Prisme demarre quand meme
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            noyau.CloseHandle(ctypes.c_void_p(poignee))
            return False
        _instance = poignee
        return True
    import fcntl
    DONNEES.mkdir(exist_ok=True)
    fichier = open(DONNEES / f'instance-{PORT}.verrou', 'a+', encoding='ascii')
    try:
        fcntl.flock(fichier, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fichier.close()
        return False
    fichier.seek(0)
    fichier.truncate()
    fichier.write(str(os.getpid()))
    fichier.flush()
    _instance = fichier
    return True


def liberer_instance():
    global _instance
    if _instance is None:
        return
    if WINDOWS:
        ctypes.WinDLL('kernel32').CloseHandle(ctypes.c_void_p(_instance))
    else:
        _instance.close()
    _instance = None


def deja_lance():
    """Un autre Prisme tient deja ce dossier : il montre sa fenetre (sauf lancement sans fenetre, apres une mise a jour)."""
    if '--sans-fenetre' not in sys.argv:
        try:
            requete = urllib.request.Request(f'http://127.0.0.1:{PORT}/api/montrer-fenetre', data=b'{}',
                                             headers={'Content-Type': 'application/json'})
            urllib.request.urlopen(requete, timeout=5).close()
        except OSError:
            ouvrir_fenetre()
    fermer_demarrage(0)


def commande_demarrage():
    """Commande qui lance Prisme normalement (sans --mcp), pour le serveur MCP quand Prisme n'est pas ouvert."""
    return [sys.executable] if EXE else [sys.executable, str(Path(__file__).resolve())]


def main():
    if '--mcp' in sys.argv:
        # Serveur MCP sur l'entree et la sortie standard : rien d'autre ne doit y ecrire
        fermer_demarrage(0)
        import mcp_prisme
        mcp_prisme.principal(version=VERSION, demarrage=commande_demarrage(), racine=RACINE)
        return
    # Relance avec python.exe : le pare-feu l'autorise deja, pythonw.exe non
    executable = Path(sys.executable)
    if not EXE and executable.name.lower() == 'pythonw.exe' and (executable.parent / 'python.exe').exists():
        subprocess.Popen([str(executable.parent / 'python.exe'), __file__] + sys.argv[1:],
                         creationflags=SANS_CONSOLE, cwd=str(Path(__file__).resolve().parent))
        return

    if not prendre_instance():
        return deja_lance()
    reprendre_apres_maj()
    arreter_moteurs_orphelins()
    try:
        global SERVEUR_RESEAU
        SERVEUR_RESEAU = lire_reglages()['acces_reseau']
        hote = '0.0.0.0' if SERVEUR_RESEAU else '127.0.0.1'
        serveur = Serveur((hote, PORT), Gestionnaire)
    except OSError:
        # Port tenu par un Prisme qui ne s'est pas encore arrete (ou par un autre programme)
        liberer_instance()
        return deja_lance()
    # Prisme 2 : fenetre Qt Quick sous Windows et Mac (--web garde la fenetre du navigateur). Sous Linux, --qt seulement :
    # sans certaines bibliotheques du systeme, Qt arreterait Prisme au lieu de rendre la main
    # Avec --sans-fenetre (relance apres une mise a jour), la fenetre Qt se charge cachee : la fenetre web de Prisme 1,
    # rechargee par la mise a jour, lui passe la main (/api/montrer-fenetre)
    fenetre_qt = None
    global FENETRE
    voulu = '--qt' in sys.argv or (not sys.platform.startswith('linux') and '--web' not in sys.argv)
    if voulu:
        try:
            import fenetre_qt
            FENETRE = 'qt-chargement'
        except ImportError:
            pass  # PySide6 absent : fenetre web
    fermer_demarrage(1.5 if '--sans-fenetre' not in sys.argv else 0)
    threading.Thread(target=surveiller, daemon=True).start()
    if lire_reglages()['verifier_mises_a_jour'] and not os.environ.get('PRISME_RACINE'):
        threading.Thread(target=verifier_mise_a_jour, daemon=True).start()
    if fenetre_qt:
        # Qt garde le fil principal (obligatoire sur Mac) ; le serveur repond a cote, pour la fenetre, le telephone et Claude
        threading.Thread(target=serveur.serve_forever, daemon=True).start()
        if fenetre_qt.lancer(f'http://127.0.0.1:{PORT}', RESSOURCES, quand_prete, '--sans-fenetre' not in sys.argv) == 0:
            # L'utilisateur a quitte (Cmd + Q, menu) : les moteurs s'arretent avec Prisme
            return arreter()
        # La fenetre Qt n'a pas pu se charger : la fenetre web prend le relais
        FENETRE = 'web'
        if '--sans-fenetre' not in sys.argv or MONTRER_A_LA_FIN:
            ouvrir_fenetre()
        threading.Event().wait()
    if '--sans-fenetre' not in sys.argv:
        ouvrir_fenetre()
    serveur.serve_forever()


def quand_prete(montrer):
    """La fenetre Qt est chargee : Prisme la montre a la demande, et se relance avec elle apres une mise a jour."""
    global FENETRE, MONTRER_FENETRE, OPTION_RELANCE
    FENETRE, MONTRER_FENETRE, OPTION_RELANCE = 'qt', montrer, '--qt'
    if MONTRER_A_LA_FIN:
        montrer()


if __name__ == '__main__':
    main()
