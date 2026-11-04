"""Serveur local de Prisme : sert l'interface web et lance sd-cli (stable-diffusion.cpp)."""

import base64
import ctypes
import json
import os
import random
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, unquote, urlparse

VERSION = '1.0.0'
PORT = 7861
# Dans l'exe, les fichiers de l'interface sont extraits a part ; les donnees restent a cote de l'exe
EXE = getattr(sys, 'frozen', False)
RESSOURCES = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
RACINE = Path(sys.executable).resolve().parent if EXE else Path(__file__).resolve().parent.parent
DONNEES = RACINE / 'app'
MODELES = RACINE / 'models'
LORAS = MODELES / 'loras'
IMAGES = RACINE / 'images'
SD_CLI = RACINE / 'sd' / 'sd-cli.exe'
EDGE = Path(r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
FICHIER_CODE = DONNEES / 'code-acces.txt'
FICHIER_REGLAGES = DONNEES / 'reglages.json'

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
    'acces_reseau': True,
    'arret_auto_minutes': 30,
    # [{'nom': 'fichier.safetensors', 'force': 1.0, 'actif': True}], fichiers du dossier models/loras
    'loras': [],
}
METHODES = ['euler', 'euler_a', 'heun', 'dpm2', 'dpm++2s_a', 'dpm++2m', 'dpm++2mv2', 'ipndm', 'ipndm_v', 'lcm',
            'ddim_trailing', 'tcd', 'res_multistep', 'res_2s', 'er_sde', 'euler_cfg_pp', 'euler_a_cfg_pp', 'euler_ge',
            'dpm++2m_sde', 'dpm++2m_sde_bt', 'lms']
EXTENSIONS_MODELES = ('.gguf', '.safetensors', '.ckpt', '.pt', '.bin')
EXTENSIONS_LORA = ('.safetensors', '.gguf')
# sd-cli lit les LoRA dans la description sous la forme <lora:nom:force>
BALISE_LORA = re.compile(r'<lora:([^:>]+):([^>]+)>')

NOM_IMAGE = re.compile(r'^[\w.-]+\.png$')
PAS = re.compile(r'(\d+)/(\d+)\s*-\s*[\d.,]+\s*(?:s/it|it/s)')

verrou = threading.Lock()
dernier_contact = time.time()
etat = {'occupe': False}
processus = None
annule = False
cache_infos = {}
# Acces reseau du serveur en cours : un changement de reglage s'applique au prochain lancement
SERVEUR_RESEAU = True


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
        for cle in ('modele_diffusion', 'modele_texte', 'modele_vision', 'vae'):
            nom = str(donnees.get(cle, r[cle])).strip().replace('\\', '/')
            if nom and ('..' in Path(nom).parts or Path(nom).is_absolute()):
                return None, 'Les modèles doivent être dans le dossier models.'
            r[cle] = nom
        r['etapes'] = int(donnees.get('etapes', r['etapes']))
        r['cfg'] = float(donnees.get('cfg', r['cfg']))
        r['methode'] = str(donnees.get('methode', r['methode']))
        r['sigmas'] = ','.join(x.strip() for x in str(donnees.get('sigmas', r['sigmas'])).split(',') if x.strip())
        for cle in ('dechargement_cpu', 'vae_tuiles', 'flash_attention', 'acces_reseau'):
            r[cle] = bool(donnees.get(cle, r[cle]))
        r['arret_auto_minutes'] = int(donnees.get('arret_auto_minutes', r['arret_auto_minutes']))
        loras = []
        for l in donnees.get('loras', r['loras']) or []:
            nom = str(l.get('nom', '')).strip().replace('\\', '/')
            if not nom or '..' in Path(nom).parts or Path(nom).is_absolute() or re.search(r'[:<>]', nom) \
                    or Path(nom).suffix.lower() not in EXTENSIONS_LORA:
                return None, f'Nom de LoRA invalide : {nom}'
            loras.append({'nom': nom, 'force': round(float(l.get('force', 1.0)), 2), 'actif': bool(l.get('actif', True))})
        r['loras'] = loras
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


def problemes_configuration(r):
    """Ce qui empeche de generer, pour guider au premier lancement."""
    problemes = []
    if not SD_CLI.is_file():
        problemes.append(f'Moteur introuvable : place sd-cli.exe et ses DLL dans {SD_CLI.parent}')
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
    # FO_DELETE avec FOF_ALLOWUNDO : l'image reste recuperable dans la corbeille de Windows
    operation = _OperationFichier(wFunc=3, pFrom=str(chemin) + '\0', fFlags=0x40 | 0x10 | 0x4 | 0x400)
    resultat = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
    return resultat == 0 and not operation.fAnyOperationsAborted and not Path(chemin).exists()


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
        if code:
            return code
    code = secrets.token_hex(4)
    FICHIER_CODE.write_text(code, encoding='utf-8')
    return code


CODE = code_acces()


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
        '-W', str(largeur), '-H', str(hauteur), '--seed', str(seed),
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
    global processus, annule
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
            processus = subprocess.Popen(
                [str(SD_CLI)] + arguments(r, params['prompt'], params['largeur'], params['hauteur'], seed, source, sortie),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=str(RACINE),
                creationflags=subprocess.CREATE_NO_WINDOW)

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


PAGE_REFUSEE = '''<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Prisme</title><body style="margin:0;min-height:100vh;display:grid;place-items:center;background:#0e0e12;color:#ececf1;font:15px system-ui,sans-serif;text-align:center;padding:24px">
<div><h1 style="font-size:20px">Accès protégé</h1><p style="color:#a1a1b0;max-width:340px">Sur le PC, clique sur « Téléphone » dans Prisme, puis scanne le QR code ou ouvre le lien affiché.</p></div>'''


class Gestionnaire(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def est_local(self):
        return self.client_address[0] in ('127.0.0.1', '::1')

    def autorise(self):
        if self.est_local():
            return True
        cookie = SimpleCookie(self.headers.get('Cookie', ''))
        valeur = cookie['prisme_acces'].value if 'prisme_acces' in cookie else ''
        return secrets.compare_digest(valeur, CODE)

    def refuser(self):
        if urlparse(self.path).path.startswith('/api/'):
            self.envoyer(401, {'erreur': 'Accès refusé : reconnecte-toi avec le lien du PC.'})
        else:
            self.envoyer(401, PAGE_REFUSEE.encode('utf-8'), 'text/html; charset=utf-8')

    def envoyer(self, code, corps, type_contenu='application/json; charset=utf-8', cache=False):
        if not isinstance(corps, bytes):
            corps = json.dumps(corps, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', type_contenu)
        self.send_header('Content-Length', str(len(corps)))
        self.send_header('Cache-Control', 'max-age=31536000, immutable' if cache else 'no-store')
        self.end_headers()
        self.wfile.write(corps)

    def lire_json(self):
        taille = int(self.headers.get('Content-Length') or 0)
        return json.loads(self.rfile.read(taille) or b'{}')

    def do_GET(self):
        global dernier_contact
        url = urlparse(self.path)
        chemin = url.path

        # Le lien du QR code depose le code dans un cookie, puis recharge l'adresse sans le code
        code = parse_qs(url.query).get('code', [''])[0]
        if code:
            if not secrets.compare_digest(code, CODE):
                return self.refuser()
            self.send_response(302)
            self.send_header('Set-Cookie', f'prisme_acces={CODE}; Max-Age=31536000; Path=/; HttpOnly; SameSite=Lax')
            self.send_header('Location', '/')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        if not self.autorise():
            return self.refuser()
        dernier_contact = time.time()

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
            copie['loras_actifs'] = [{'nom': Path(l['nom']).stem, 'force': l['force']} for l in loras_actifs(r)]
            self.envoyer(200, copie)
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
        global dernier_contact, annule
        if not self.autorise():
            return self.refuser()
        dernier_contact = time.time()
        chemin = urlparse(self.path).path

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
                annule = False
                etat.clear()
                etat.update(occupe=True, phase='chargement', etape=0, total=r['etapes'], index=1, nombre=nombre,
                            seed=seed, seed_base=seed, debut=time.time(), resultats=[], erreur=None,
                            largeur=largeur, hauteur=hauteur)
            params = dict(prompt=prompt, largeur=largeur, hauteur=hauteur, nombre=nombre, seed=seed, reglages=r,
                          source_nom=p.get('source_nom'), source_data=p.get('source_data'))
            threading.Thread(target=generer, args=(params,), daemon=True).start()
            self.envoyer(200, {'seed': seed})

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
            os.startfile(dossier)
            self.envoyer(200, {})

        elif chemin == '/api/dossier':
            if not self.est_local():
                return self.envoyer(403, {'erreur': 'Disponible seulement sur le PC.'})
            nom = str(self.lire_json().get('nom') or '')
            if NOM_IMAGE.match(nom) and (IMAGES / nom).exists():
                subprocess.Popen(['explorer.exe', '/select,', str(IMAGES / nom)])
            else:
                IMAGES.mkdir(exist_ok=True)
                os.startfile(IMAGES)
            self.envoyer(200, {})
        else:
            self.envoyer(404, {'erreur': 'Introuvable'})


class Serveur(ThreadingHTTPServer):
    # Sous Windows, la reutilisation d'adresse laisserait deux serveurs ecouter le meme port
    allow_reuse_address = False

    def server_bind(self):
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def ouvrir_fenetre():
    adresse = f'http://127.0.0.1:{PORT}/'
    if EDGE.exists():
        subprocess.Popen([str(EDGE), f'--app={adresse}', '--window-size=1440,920'])
    else:
        import webbrowser
        webbrowser.open(adresse)


def surveiller():
    while True:
        time.sleep(10)
        limite = lire_reglages()['arret_auto_minutes'] * 60
        if not etat.get('occupe') and time.time() - dernier_contact > limite:
            os._exit(0)


def main():
    # Relance avec python.exe : le pare-feu l'autorise deja, pythonw.exe non
    executable = Path(sys.executable)
    if not EXE and executable.name.lower() == 'pythonw.exe' and (executable.parent / 'python.exe').exists():
        subprocess.Popen([str(executable.parent / 'python.exe'), __file__] + sys.argv[1:],
                         creationflags=subprocess.CREATE_NO_WINDOW, cwd=str(APP))
        return

    try:
        global SERVEUR_RESEAU
        SERVEUR_RESEAU = lire_reglages()['acces_reseau']
        hote = '0.0.0.0' if SERVEUR_RESEAU else '127.0.0.1'
        serveur = Serveur((hote, PORT), Gestionnaire)
    except OSError:
        # Deja lance : on rouvre seulement la fenetre
        ouvrir_fenetre()
        return
    if '--sans-fenetre' not in sys.argv:
        ouvrir_fenetre()
    threading.Thread(target=surveiller, daemon=True).start()
    serveur.serve_forever()


if __name__ == '__main__':
    main()
