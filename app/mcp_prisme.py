"""Serveur MCP de Prisme : Claude (Desktop ou Code) cree et modifie des images avec Prisme, sur cet ordinateur.

Integre au programme : Claude lance `Prisme.exe --mcp` (ou `python app/serveur.py --mcp`), sans Python ni paquet
a installer. Le protocole MCP (JSON-RPC sur l'entree et la sortie standard) est ecrit avec la bibliotheque standard.

Il parle a l'API HTTP locale de Prisme (app/serveur.py), et le lance s'il n'est pas ouvert :
  GET  /api/etat                     etat, problemes, moteurs, telechargements
  POST /api/generer                  creation, ou modification avec source_data
  GET  /images/<nom>                 image PNG terminee
  GET  /api/reglages, /api/profils   modeles et profils (PC seulement)
  POST /api/installer-moteur, /api/telecharger-modele
  POST /api/demander-telechargement  licence non commerciale ou modele hors catalogue : l'utilisateur accepte
                                     lui-meme dans la fenetre de Prisme, Claude ne peut pas le faire a sa place
  GET  /api/consentement             reponse de l'utilisateur

Les messages d'erreur sont faits pour etre lus par Claude puis par l'utilisateur : pas de trace Python.
"""

import base64
import json
import os
import re
import socket
import struct
import subprocess
import sys
import threading
import time
import zlib
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote, urlparse

PORT_PAR_DEFAUT = 7861
TAILLE_MIN, TAILLE_MAX = 256, 2048
PROMPT_MAX = 4000
IMAGE_SOURCE_MAX = 32 * 1024 * 1024
APERCU_MAX = 900 * 1024
NOM_IMAGE = re.compile(r'^[\w.-]+\.png$')
HOTES_LOCAUX = ('127.0.0.1', 'localhost', '::1')
COMMENT_TELECHARGER = ('Ask Claude to call download_profile with that profile, or in Prisme click "Download the models" '
                       '(Télécharger les modèles), pick that profile, then "Download this profile".')
ATTENTE_ACCORD = 180


class PrismeErreur(Exception):
    """Erreur expliquee a l'utilisateur ; le message suffit, sans trace."""


def configuration(environ=None, racine=None):
    """PRISME_URL, PRISME_TIMEOUT et PRISME_OUTPUT_DIR, verifies."""
    environ = os.environ if environ is None else environ
    url = (environ.get('PRISME_URL') or f'http://127.0.0.1:{PORT_PAR_DEFAUT}').rstrip('/')
    adresse = urlparse(url)
    if adresse.scheme not in ('http', 'https') or not adresse.hostname:
        raise PrismeErreur(f'PRISME_URL is not a valid address: {url}')
    # Les prompts et les images restent sur cet ordinateur
    if adresse.hostname not in HOTES_LOCAUX:
        raise PrismeErreur(f'PRISME_URL must point to this computer (127.0.0.1 or localhost), not {adresse.hostname}.')
    try:
        # Claude abandonne un appel d'outil après 60 s : rendre la main avant, avec un task_id
        delai = float(environ.get('PRISME_TIMEOUT') or 50)
    except ValueError:
        raise PrismeErreur('PRISME_TIMEOUT must be a number of seconds.') from None
    if not 1 <= delai <= 3600:
        raise PrismeErreur('PRISME_TIMEOUT must be between 1 and 3600 seconds.')
    # Par defaut, le dossier ou Prisme range les images demandees par Claude
    defaut = Path(racine) / 'images-claude' if racine else Path.home() / 'Prisme-MCP'
    dossier = Path(environ.get('PRISME_OUTPUT_DIR') or defaut).expanduser()
    return {'url': url, 'delai': delai, 'dossier': dossier}


class Prisme:
    def __init__(self, url, delai=50, dossier=None, pause=1.0, demarrage=None):
        self.url, self.delai, self.pause = url.rstrip('/'), delai, pause
        self.dossier = Path(dossier or Path.home() / 'Prisme-MCP').expanduser()
        # Commande qui lance Prisme s'il n'est pas ouvert (programme integre) ; None : ne rien lancer
        self.demarrage, self.verrou_demarrage = demarrage, threading.Lock()

    @classmethod
    def depuis_environnement(cls, environ=None, demarrage=None, racine=None):
        c = configuration(environ, racine)
        return cls(c['url'], c['delai'], c['dossier'], demarrage=demarrage)

    def demarrer_prisme(self):
        """Lance Prisme (sa fenetre s'ouvre) et attend qu'il reponde. Vrai s'il repond."""
        with self.verrou_demarrage:
            if self.joignable():
                return True
            port = urlparse(self.url).port or PORT_PAR_DEFAUT
            # Sans cela, le Prisme lance heriterait des variables internes de l'exe du serveur MCP
            environnement = {k: v for k, v in os.environ.items() if not k.startswith(('_PYI_', '_MEIPASS'))}
            environnement.update(PYINSTALLER_RESET_ENVIRONMENT='1', PRISME_PORT=str(port))
            environnement.pop('PYINSTALLER_SUPPRESS_SPLASH_SCREEN', None)
            options = {'stdin': subprocess.DEVNULL, 'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL,
                       'env': environnement}
            # Prisme doit survivre au serveur MCP : certains clients (dont le SDK officiel sous Windows) arretent tous les
            # processus lances par le serveur quand ils le ferment
            reglage_propre = any(os.environ.get(v) for v in ('PRISME_RACINE', 'PRISME_PORT')) or port != PORT_PAR_DEFAUT
            if sys.platform == 'win32' and getattr(sys, 'frozen', False) and not reglage_propre:
                # Comme un double-clic : l'explorateur lance Prisme, hors des processus de Claude
                subprocess.Popen(['explorer.exe', self.demarrage[0]], **options)
            elif sys.platform == 'win32':
                drapeaux = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
                try:
                    subprocess.Popen(self.demarrage, creationflags=drapeaux | subprocess.CREATE_BREAKAWAY_FROM_JOB, **options)
                except OSError:
                    subprocess.Popen(self.demarrage, creationflags=drapeaux, **options)
            else:
                # Un shell intermediaire qui se termine aussitot : Prisme n'est plus un descendant du serveur MCP
                subprocess.Popen(['/bin/sh', '-c', '"$@" >/dev/null 2>&1 &', 'prisme', *self.demarrage],
                                 start_new_session=True, **options)
            limite = time.monotonic() + 45
            while time.monotonic() < limite:
                time.sleep(0.5)
                if self.joignable():
                    return True
            return False

    def joignable(self):
        try:
            with urllib.request.urlopen(urllib.request.Request(self.url + '/api/etat', headers={'X-Prisme-Client': 'mcp'}),
                                        timeout=3):
                return True
        except (urllib.error.URLError, OSError):
            return False

    # --- HTTP
    def requete(self, chemin, corps=None, brut=False, delai=30, relance=True):
        donnees = None if corps is None else json.dumps(corps).encode('utf-8')
        en_tetes = {'X-Prisme-Client': 'mcp', **({'Content-Type': 'application/json'} if corps is not None else {})}
        requete = urllib.request.Request(self.url + chemin, data=donnees, method='POST' if corps is not None else 'GET',
                                         headers=en_tetes)
        try:
            with urllib.request.urlopen(requete, timeout=delai) as reponse:
                contenu = reponse.read()
        except urllib.error.HTTPError as e:
            try:
                message = json.loads(e.read() or b'{}').get('erreur') or e.reason
            except ValueError:
                message = e.reason
            if e.code == 409:
                raise PrismeErreur(f'Prisme is busy: {message} Wait for the current image, then try again.') from None
            if e.code in (401, 403):
                raise PrismeErreur(f'Prisme refused the request ({message}). The MCP server must run on the same '
                                   'computer as Prisme.') from None
            raise PrismeErreur(f'Prisme answered with an error ({e.code}): {message}') from None
        except (urllib.error.URLError, ConnectionError, socket.timeout, TimeoutError) as e:
            raison = getattr(e, 'reason', e)
            if isinstance(raison, (ConnectionRefusedError, ConnectionResetError)) or 'refused' in str(raison).lower():
                # Prisme n'est pas ouvert : le programme integre le lance, puis refait la requete
                if relance and self.demarrage and self.demarrer_prisme():
                    return self.requete(chemin, corps, brut, delai, relance=False)
                raise PrismeErreur(f'Prisme is not running at {self.url}. Start Prisme (Prisme.exe, Prisme.app or ./prisme), '
                                   'then try again.') from None
            raise PrismeErreur(f'Prisme cannot be reached at {self.url} ({raison}). Check that Prisme is running.') from None
        if brut:
            return contenu
        try:
            return json.loads(contenu or b'{}')
        except ValueError:
            raise PrismeErreur(f'{self.url} does not look like Prisme (unexpected answer).') from None

    # --- Lecture
    def etat(self):
        return self.requete('/api/etat')

    def profils(self):
        return self.requete('/api/profils')

    def statut(self):
        e = self.etat()
        statut = {'version': e.get('version'), 'busy': bool(e.get('occupe')), 'phase': e.get('phase'),
                  'drawing_model': e.get('modele') or None, 'problems': e.get('problemes') or []}
        # Une creation lancee dans la fenetre de Prisme n'est pas a Claude : pas d'identifiant pour la recuperer
        if e.get('occupe') and e.get('claude'):
            statut.update(task_id=identifiant_tache(e), step=e.get('etape'), steps=e.get('total'),
                          image=e.get('index'), images=e.get('nombre'), elapsed_seconds=e.get('ecoule'))
        if e.get('erreur'):
            statut['error'] = e['erreur']
        moteurs = e.get('moteurs') or {}
        statut['engines'] = {('text' if nom == 'texte' else nom): resume_moteur(m) for nom, m in moteurs.items()}
        telechargements = [{'file': t['fichier'], 'status': t['phase'], 'done_gb': round(t['fait'] / 1e9, 2),
                            'total_gb': round(t['total'] / 1e9, 2), **({'error': t['erreur']} if t.get('erreur') else {})}
                           for t in e.get('telechargements') or []]
        if telechargements:
            statut['downloads'] = telechargements
        if e.get('consentements'):
            statut['waiting_for_user_approval'] = len(e['consentements'])
        return statut

    def modeles(self):
        infos = self.requete('/api/reglages')
        r = infos.get('reglages', {})
        return {'models_folder': infos.get('dossier'), 'files': infos.get('modeles', []),
                'selected': {'drawing_model': r.get('modele_diffusion') or None, 'text_model': r.get('modele_texte') or None,
                             'vision': r.get('modele_vision') or None, 'vae': r.get('vae') or None},
                'can_edit_images': bool(infos.get('edition_possible', r.get('modele_vision'))),
                'loras': [l.get('nom') for l in infos.get('loras', []) if isinstance(l, dict)] or infos.get('loras', [])}

    def liste_profils(self):
        infos = self.profils()
        profils = [{'id': p['id'], 'name': p['nom']['en'], 'nom': p['nom']['fr'], 'hardware': p['materiel']['en'],
                    'download_size_gb': round(p['taille_totale'] / 1e9, 1), 'remaining_gb': round(p['taille_restante'] / 1e9, 1),
                    'status': 'recommended' if p['statut'] == 'recommande' else 'experimental',
                    'image_editing': p['edition'], 'downloaded': p['installe'], 'in_use': p['actif'],
                    'category': {'principal': 'main', 'video': 'video'}.get(p.get('categorie', 'principal'), 'option'),
                    'license_to_accept': bool(p.get('licence_a_accepter')),
                    'speed': p['vitesse']['en'], 'models': [m['fichier'] for m in p['modeles']]}
                   for p in infos.get('profils', [])]
        return {'suggested_profile': infos.get('suggestion'), 'default_profile': infos.get('conseille'),
                'free_disk_gb': round(infos.get('libre', 0) / 1e9, 1), 'profiles': profils,
                'how_to_download': COMMENT_TELECHARGER}

    # --- Installation : moteur, profils, autres modeles
    def installer_moteur(self, moteur='image'):
        nom = {'image': 'image', 'text': 'texte', 'texte': 'texte'}.get(str(moteur))
        if not nom:
            raise PrismeErreur('engine must be "image" or "text".')
        etat = (self.etat().get('moteurs') or {}).get(nom) or {}
        if etat.get('installe'):
            return {'status': 'installed', 'engine': moteur, 'message': f'{etat.get("nom")} {etat.get("version")} is already installed.'}
        self.requete('/api/installer-moteur', {'moteur': nom})
        return {'status': 'installing', 'engine': moteur, 'size_gb': round((etat.get('taille') or 0) / 1e9, 2),
                'message': 'Installing from the official release (checked by SHA-256). Follow it with get_status.'}

    def telecharger_profil(self, profil_id):
        infos = self.profils()
        profil = next((p for p in infos.get('profils', []) if p['id'] == profil_id), None)
        if not profil:
            raise PrismeErreur(f'Unknown profile "{profil_id}". Profiles: ' + ', '.join(p['id'] for p in infos.get('profils', [])))
        if profil.get('licence_a_accepter'):
            # Licence non commerciale : c'est l'utilisateur qui l'accepte, dans la fenetre de Prisme
            reponse = self.requete('/api/demander-telechargement', {'profil': profil_id})
            return self.attendre_accord(reponse['id'], f'the "{profil["nom"]["en"]}" profile under the '
                                        f'{reponse["details"]["licence"]["nom"]} (non-commercial)')
        for m in profil['modeles']:
            self.requete('/api/telecharger-modele', {'id': m['id']})
        # Les moteurs manquants : celui des images, puis celui du texte (pour Ameliorer)
        moteurs = self.etat().get('moteurs') or {}
        installes = []
        for nom in ('image', 'texte'):
            m = moteurs.get(nom) or {}
            prerequis = m.get('requiert') and not (moteurs.get(m['requiert']) or {}).get('installe') and m['requiert'] not in installes
            if m and not m.get('installe') and not prerequis and (m.get('installation') or {}).get('phase') not in ('telechargement', 'extraction'):
                try:
                    self.requete('/api/installer-moteur', {'moteur': nom})
                    installes.append(nom)
                except PrismeErreur:
                    pass
        return {'status': 'downloading', 'profile': profil_id, 'remaining_gb': round(profil['taille_restante'] / 1e9, 1),
                'engines_installing': ['text' if n == 'texte' else n for n in installes],
                'message': 'Files already present are only selected. Follow the downloads with get_status; Prisme '
                           'selects the models in its settings when they are ready.'}

    def telecharger_externe(self, url, role=None):
        role = {'drawing': 'image', 'image': 'image', 'text': 'texte', 'texte': 'texte', 'vision': 'edition',
                'edition': 'edition', 'vae': 'vae', 'lora': 'lora', None: None, '': None}.get(role, '?')
        if role == '?':
            raise PrismeErreur('use_as must be one of: image, text, vision, vae, lora (or empty).')
        reponse = self.requete('/api/demander-telechargement', {'url': url, 'role': role}, delai=60)
        d = reponse['details']
        quoi = f'{Path(d["fichier"]).name} ({d["taille"] / 1e9:.1f} GB from {d["hote"]}, not checked by Prisme)'
        return self.attendre_accord(reponse['id'], quoi)

    def attendre_accord(self, ident, quoi):
        """Attend que l'utilisateur accepte ou refuse dans la fenetre de Prisme."""
        limite = time.monotonic() + min(self.delai, ATTENTE_ACCORD)
        while time.monotonic() < limite:
            reponse = self.requete('/api/consentement?id=' + quote(ident))
            if reponse['etat'] == 'acceptee':
                return {'status': 'downloading', 'approved_by_user': True,
                        'message': f'The user accepted {quoi} in Prisme. Follow the download with get_status.'}
            if reponse['etat'] == 'refusee':
                raise PrismeErreur(f'The user refused {quoi} in Prisme\'s window. Do not ask again unless they want to.')
            if reponse['etat'] == 'expiree':
                raise PrismeErreur('The request expired without an answer in Prisme\'s window.')
            time.sleep(self.pause)
        return {'status': 'waiting_for_user_approval', 'request_id': ident,
                'message': f'Prisme is asking the user to accept {quoi} in its window. Tell the user to look at '
                           'Prisme\'s window and answer there; then call get_status.'}

    # --- Verifications avant de lancer
    def verifier_pret(self, etat):
        problemes = etat.get('problemes') or []
        if not problemes:
            return
        conseil = ''
        try:
            infos = self.profils()
            ident = infos.get('suggestion') or infos.get('conseille')
            profil = next((p for p in infos.get('profils', []) if p['id'] == ident), None)
            if profil:
                conseil = (f' Suggested profile for this computer: "{profil["nom"]["en"]}" ({profil["id"]}, '
                           f'{profil["taille_totale"] / 1e9:.1f} GB). {COMMENT_TELECHARGER}')
        except PrismeErreur:
            pass
        raise PrismeErreur('Prisme is not ready to create images: ' + '; '.join(problemes) + '.' + conseil)

    def verifier_libre(self, etat):
        if etat.get('occupe'):
            raise PrismeErreur(f'Prisme is busy with another image (task {identifiant_tache(etat)}). '
                               'Use get_status to follow it, then try again.')

    # --- Creation et modification
    def generer(self, prompt, width=1024, height=1024, seed=None, model=None):
        prompt = valider_prompt(prompt)
        width, height = valider_taille(width, 'width'), valider_taille(height, 'height')
        if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2 ** 31):
            raise PrismeErreur('seed must be a whole number between 0 and 2147483647.')
        etat = self.etat()
        self.verifier_pret(etat)
        self.verifier_libre(etat)
        corps = {'prompt': prompt, 'largeur': width, 'hauteur': height, 'nombre': 1, 'seed': seed}
        if model:
            fichiers = self.modeles()['files']
            if model not in fichiers:
                raise PrismeErreur(f'Model "{model}" is not in Prisme\'s models folder. Available files: '
                                   + (', '.join(fichiers) or 'none') + '.')
            corps['modele'] = model
        self.requete('/api/generer', corps)
        return self.attendre()

    def modifier(self, image_path, instruction, width=None, height=None):
        instruction = valider_prompt(instruction, 'instruction')
        chemin = self.chemin_autorise(image_path)
        donnees = chemin.read_bytes()
        genre = type_image(donnees)
        if not genre:
            raise PrismeErreur('Only PNG and JPEG images can be edited.')
        if width is None or height is None:
            width, height = taille_de_sortie(*dimensions_image(donnees))
        width, height = valider_taille(width, 'width'), valider_taille(height, 'height')
        etat = self.etat()
        self.verifier_pret(etat)
        self.verifier_libre(etat)
        if not self.modeles()['can_edit_images']:
            raise PrismeErreur('The models selected in Prisme cannot edit images. Choose a profile with image editing '
                               '(FLUX.2 klein or Qwen-Image) in Prisme\'s models window, or call list_profiles.')
        source = f'data:image/{genre};base64,' + base64.b64encode(donnees).decode('ascii')
        self.requete('/api/generer', {'prompt': instruction, 'largeur': width, 'hauteur': height, 'nombre': 1,
                                      'source_data': source}, delai=60)
        return self.attendre()

    def chemin_autorise(self, image_path):
        """L'image a modifier doit etre dans PRISME_OUTPUT_DIR : le serveur MCP ne lit rien d'autre sur le disque."""
        if not image_path or not str(image_path).strip():
            raise PrismeErreur('image_path is empty.')
        dossier = self.dossier.resolve()
        chemin = Path(str(image_path)).expanduser()
        if not chemin.is_absolute():
            chemin = dossier / chemin
        chemin = chemin.resolve()
        if not chemin.is_relative_to(dossier):
            raise PrismeErreur(f'For safety, only images inside {dossier} can be edited (PRISME_OUTPUT_DIR). '
                               'Copy the image there first, or edit an image created through this server.')
        if not chemin.is_file():
            raise PrismeErreur(f'Image not found: {chemin}')
        if chemin.stat().st_size > IMAGE_SOURCE_MAX:
            raise PrismeErreur(f'The image is too large (over {IMAGE_SOURCE_MAX // (1024 * 1024)} MB).')
        return chemin

    # --- Attente et resultats
    def attendre(self, delai=None):
        """Suit la creation jusqu'a la fin ; si elle dure plus que PRISME_TIMEOUT, renvoie un identifiant de tache."""
        limite = time.monotonic() + (self.delai if delai is None else delai)
        etat = self.etat()
        ident = identifiant_tache(etat)
        while etat.get('occupe'):
            if time.monotonic() >= limite:
                return {'status': 'running', 'task_id': ident, 'step': etat.get('etape'), 'steps': etat.get('total'),
                        'message': f'Still working after {self.delai:.0f} s. Call get_status with task_id "{ident}" to get '
                                   'the image when it is ready.'}
            time.sleep(self.pause)
            etat = self.etat()
        return self.resultat(etat)

    def resultat(self, etat):
        phase = etat.get('phase')
        if phase == 'annule':
            raise PrismeErreur('The creation was cancelled in Prisme.')
        if etat.get('erreur') or phase == 'erreur':
            raise PrismeErreur('Prisme could not create the image: ' + str(etat.get('erreur') or 'unknown error'))
        noms = [n for n in etat.get('resultats') or [] if NOM_IMAGE.match(str(n))]
        if not noms:
            raise PrismeErreur('Prisme finished without producing an image.')
        self.dossier.mkdir(parents=True, exist_ok=True)
        images = []
        for nom in noms:
            contenu = self.requete('/images-claude/' + quote(nom), brut=True, delai=60)
            chemin = self.dossier / nom
            if not chemin.is_file():  # deja la quand PRISME_OUTPUT_DIR est le dossier de Prisme pour Claude
                chemin.write_bytes(contenu)
            images.append({'path': str(chemin), 'png': contenu})
        return {'status': 'done', 'task_id': identifiant_tache(etat), 'seed': etat.get('seed_base'),
                'width': etat.get('largeur'), 'height': etat.get('hauteur'), 'prompt': etat.get('prompt'),
                'seconds': etat.get('ecoule'), 'images': images}

    def suivre(self, task_id=None):
        """get_status : etat de Prisme, ou resultat d'une tache lancee plus tot."""
        if not task_id:
            return self.statut()
        etat = self.etat()
        if not etat.get('claude') or identifiant_tache(etat) != str(task_id):
            raise PrismeErreur(f'Task {task_id} is not Prisme\'s latest creation anymore. Its images are in Prisme\'s '
                               '"images-claude" folder.')
        if etat.get('occupe'):
            return {'status': 'running', 'task_id': str(task_id), 'step': etat.get('etape'), 'steps': etat.get('total'),
                    'elapsed_seconds': etat.get('ecoule')}
        return self.resultat(etat)


def identifiant_tache(etat):
    """Prisme fait une creation a la fois : l'heure de depart (ms) l'identifie."""
    debut = etat.get('debut')
    return str(int(float(debut) * 1000)) if debut else None


def valider_prompt(texte, nom='prompt'):
    texte = str(texte or '').strip()
    if not texte:
        raise PrismeErreur(f'{nom} is empty: describe what you want.')
    if len(texte) > PROMPT_MAX:
        raise PrismeErreur(f'{nom} is too long (over {PROMPT_MAX} characters).')
    return texte


def valider_taille(valeur, nom):
    if isinstance(valeur, bool) or not isinstance(valeur, int):
        raise PrismeErreur(f'{nom} must be a whole number of pixels.')
    if not TAILLE_MIN <= valeur <= TAILLE_MAX or valeur % 16:
        raise PrismeErreur(f'{nom} must be a multiple of 16 between {TAILLE_MIN} and {TAILLE_MAX} (got {valeur}).')
    return valeur


def type_image(donnees):
    if donnees.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if donnees.startswith(b'\xff\xd8'):
        return 'jpeg'
    return None


def dimensions_image(donnees):
    """Largeur et hauteur d'un PNG ou d'un JPEG, lues dans l'en-tete ; (0, 0) si illisibles."""
    if donnees.startswith(b'\x89PNG\r\n\x1a\n') and len(donnees) >= 24:
        return struct.unpack('>II', donnees[16:24])
    if donnees.startswith(b'\xff\xd8'):
        i = 2
        while i + 9 < len(donnees):
            if donnees[i] != 0xFF:
                i += 1
                continue
            marqueur = donnees[i + 1]
            if marqueur in (0xD8, 0x01) or 0xD0 <= marqueur <= 0xD7:
                i += 2
                continue
            longueur = struct.unpack('>H', donnees[i + 2:i + 4])[0]
            if 0xC0 <= marqueur <= 0xCF and marqueur not in (0xC4, 0xC8, 0xCC):
                hauteur, largeur = struct.unpack('>HH', donnees[i + 5:i + 9])
                return largeur, hauteur
            i += 2 + longueur
    return 0, 0


def taille_de_sortie(largeur, hauteur, cote=1024):
    """Garde les proportions de l'image de depart, plus grand cote a 1024, en multiples de 16."""
    if not largeur or not hauteur:
        return cote, cote
    echelle = cote / max(largeur, hauteur)
    arrondi = lambda v: max(TAILLE_MIN, min(TAILLE_MAX, int(round(v * echelle / 16)) * 16))
    return arrondi(largeur), arrondi(hauteur)


def apercu(png, maximum=APERCU_MAX):
    """Image a renvoyer a Claude : le PNG s'il est assez petit, sinon une version JPEG reduite si Pillow est installe."""
    if len(png) <= maximum:
        return png, 'png'
    try:
        from PIL import Image as ImagePil
    except ImportError:
        reduit = reduire_png(png, maximum)
        return (reduit, 'png') if reduit else (None, None)
    import io
    with ImagePil.open(io.BytesIO(png)) as image:
        image = image.convert('RGB')
        for cote, qualite in ((1024, 85), (768, 80), (512, 75)):
            copie = image.copy()
            copie.thumbnail((cote, cote))
            sortie = io.BytesIO()
            copie.save(sortie, 'JPEG', quality=qualite)
            if sortie.tell() <= maximum:
                return sortie.getvalue(), 'jpeg'
    return None, None


def resume(resultat):
    """Texte court pour Claude, sans les octets des images."""
    if resultat.get('status') != 'done':
        return json.dumps({k: v for k, v in resultat.items()}, ensure_ascii=False)
    infos = {k: resultat[k] for k in ('status', 'task_id', 'seed', 'width', 'height', 'seconds') if resultat.get(k) is not None}
    infos['files'] = [i['path'] for i in resultat['images']]
    return json.dumps(infos, ensure_ascii=False)


def resume_moteur(m):
    inst = m.get('installation') or {}
    if m.get('installe'):
        return 'installed'
    if inst.get('phase') in ('telechargement', 'extraction'):
        return f'installing ({round(inst.get("fait", 0) / max(1, inst.get("total", 1)) * 100)} %)'
    if inst.get('phase') == 'erreur':
        return 'error: ' + str(inst.get('erreur'))
    return 'not installed'


# --- Apercu sans Pillow : PNG RVB(A) 8 bits lu, reduit (un pixel sur n), puis reecrit en PNG

def lire_png(donnees):
    """Largeur, hauteur, octets par pixel et pixels bruts d'un PNG 8 bits RVB ou RVBA non entrelace, ou None."""
    if not donnees.startswith(b'\x89PNG\r\n\x1a\n'):
        return None
    i, idat, entete = 8, [], None
    while i + 8 <= len(donnees):
        longueur, genre = struct.unpack('>I4s', donnees[i:i + 8])
        bloc = donnees[i + 8:i + 8 + longueur]
        if genre == b'IHDR':
            entete = struct.unpack('>IIBBBBB', bloc)
        elif genre == b'IDAT':
            idat.append(bloc)
        elif genre == b'IEND':
            break
        i += 12 + longueur
    if not entete:
        return None
    largeur, hauteur, profondeur, couleur, _, _, entrelace = entete
    if profondeur != 8 or couleur not in (2, 6) or entrelace:
        return None
    bpp = 3 if couleur == 2 else 4
    brut = zlib.decompress(b''.join(idat))
    pas = largeur * bpp
    pixels = bytearray(pas * hauteur)
    precedente = bytearray(pas)
    for y in range(hauteur):
        filtre = brut[y * (pas + 1)]
        ligne = bytearray(brut[y * (pas + 1) + 1:(y + 1) * (pas + 1)])
        if filtre == 1:
            for x in range(bpp, pas):
                ligne[x] = (ligne[x] + ligne[x - bpp]) & 255
        elif filtre == 2:
            ligne = bytearray((a + b) & 255 for a, b in zip(ligne, precedente))
        elif filtre == 3:
            for x in range(pas):
                gauche = ligne[x - bpp] if x >= bpp else 0
                ligne[x] = (ligne[x] + ((gauche + precedente[x]) >> 1)) & 255
        elif filtre == 4:
            for x in range(pas):
                a = ligne[x - bpp] if x >= bpp else 0
                b = precedente[x]
                c = precedente[x - bpp] if x >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                ligne[x] = (ligne[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        pixels[y * pas:(y + 1) * pas] = ligne
        precedente = ligne
    return largeur, hauteur, bpp, pixels


def ecrire_png(largeur, hauteur, pixels):
    def bloc(genre, donnees):
        return struct.pack('>I', len(donnees)) + genre + donnees + struct.pack('>I', zlib.crc32(genre + donnees))
    pas = largeur * 3
    brut = b''.join(b'\x00' + bytes(pixels[y * pas:(y + 1) * pas]) for y in range(hauteur))
    return (b'\x89PNG\r\n\x1a\n' + bloc(b'IHDR', struct.pack('>IIBBBBB', largeur, hauteur, 8, 2, 0, 0, 0))
            + bloc(b'IDAT', zlib.compress(brut, 9)) + bloc(b'IEND', b''))


def reduire_png(png, maximum=APERCU_MAX):
    """PNG plus petit (un pixel sur n, en RVB) qui tient dans `maximum` octets, ou None."""
    lu = lire_png(png)
    if not lu:
        return None
    largeur, hauteur, bpp, pixels = lu
    for cote in (640, 512, 384, 256):
        n = max(1, -(-max(largeur, hauteur) // cote))
        l, h = len(range(0, largeur, n)), len(range(0, hauteur, n))
        sortie = bytearray(l * h * 3)
        for j, y in enumerate(range(0, hauteur, n)):
            ligne = pixels[y * largeur * bpp:(y + 1) * largeur * bpp]
            debut = j * l * 3
            for canal in range(3):
                sortie[debut + canal:debut + l * 3:3] = ligne[canal::bpp * n][:l]
        reduit = ecrire_png(l, h, sortie)
        if len(reduit) <= maximum:
            return reduit
    return None


# --- Outils MCP et protocole JSON-RPC sur l'entree et la sortie standard

INSTRUCTIONS = (
    'Prisme creates and edits images locally on this computer. One image at a time: from about 30 seconds on a recent '
    'graphics card to several minutes on a Mac or without one. If Prisme is not ready, call list_profiles, suggest the '
    'recommended profile to the user, and with their agreement call download_profile (and install_engine if needed). '
    'Licenses that are not open (Qwen-Image) and models outside Prisme\'s catalog are approved by the user in Prisme\'s '
    'window, never by you. If a tool returns a task_id, call get_status with it later. Images are saved in PRISME_OUTPUT_DIR.')

SCHEMA_VIDE = {'type': 'object', 'properties': {}}
OUTILS = [
    {'name': 'generate_image',
     'description': 'Create an image from a description with Prisme, on this computer. width and height: multiples of 16 '
                    'between 256 and 2048 (1024 x 1024 by default). seed: optional, to reproduce an image. model: optional '
                    'drawing model file from list_models, used for this image only. Returns the saved file path and the '
                    'image, or a task_id to pass to get_status if it takes longer than PRISME_TIMEOUT.',
     'inputSchema': {'type': 'object', 'required': ['prompt'], 'properties': {
         'prompt': {'type': 'string', 'description': 'What the image shows.'},
         'width': {'type': 'integer', 'default': 1024, 'minimum': 256, 'maximum': 2048, 'multipleOf': 16},
         'height': {'type': 'integer', 'default': 1024, 'minimum': 256, 'maximum': 2048, 'multipleOf': 16},
         'seed': {'type': 'integer', 'minimum': 0, 'maximum': 2147483647},
         'model': {'type': 'string', 'description': 'Drawing model file name from list_models.'}}}},
    {'name': 'edit_image',
     'description': 'Edit an image with Prisme, following an instruction such as "add snow on the roof". image_path: a PNG '
                    'or JPEG inside PRISME_OUTPUT_DIR (for example an image created by generate_image). The result keeps '
                    'the starting image\'s proportions. Needs a profile with image editing (FLUX.2 klein or Qwen-Image).',
     'inputSchema': {'type': 'object', 'required': ['image_path', 'instruction'], 'properties': {
         'image_path': {'type': 'string'}, 'instruction': {'type': 'string'}}}},
    {'name': 'list_models',
     'description': 'Model files in Prisme\'s models folder, the ones currently selected, and whether image editing is possible.',
     'inputSchema': SCHEMA_VIDE},
    {'name': 'list_profiles',
     'description': 'Model profiles by hardware (CPU only, 4 to 16 GB graphics cards, Apple Silicon) and other choices, '
                    'their size and license, what is already downloaded, and the profile Prisme suggests for this computer.',
     'inputSchema': SCHEMA_VIDE},
    {'name': 'get_status',
     'description': 'Prisme\'s status: busy or not, progress, engines, downloads, configuration problems. With a task_id '
                    'from generate_image or edit_image, returns the finished image, or its progress if it is still running.',
     'inputSchema': {'type': 'object', 'properties': {'task_id': {'type': 'string'}}}},
    {'name': 'install_engine',
     'description': 'Install a Prisme engine from its pinned official release: "image" (stable-diffusion.cpp, needed to '
                    'create images) or "text" (llama.cpp, for prompt enhancement). Downloaded once.',
     'inputSchema': {'type': 'object', 'properties': {'engine': {'type': 'string', 'enum': ['image', 'text'], 'default': 'image'}}}},
    {'name': 'download_profile',
     'description': 'Download a model profile from list_profiles, and the missing engines. Use it when the user agrees. '
                    'Profiles under a non-commercial license (Qwen-Image) are only downloaded if the user accepts the '
                    'license in Prisme\'s window: tell them to look at Prisme. Follow the downloads with get_status.',
     'inputSchema': {'type': 'object', 'required': ['profile_id'], 'properties': {'profile_id': {'type': 'string'}}}},
    {'name': 'download_model',
     'description': 'Download a model that is not in Prisme\'s catalog: an https link to a .gguf or .safetensors file '
                    '(for example a Hugging Face "resolve" link). Only when the user asks for it. Prisme shows a warning '
                    '(license and content not checked by Prisme) and the user must accept in Prisme\'s window. use_as '
                    'selects it in the settings: image, text, vision, vae or lora.',
     'inputSchema': {'type': 'object', 'required': ['url'], 'properties': {
         'url': {'type': 'string'}, 'use_as': {'type': 'string', 'enum': ['image', 'text', 'vision', 'vae', 'lora']}}}},
]


def contenu_resultat(resultat):
    """Texte (chemins, graine) et apercu des images pour Claude."""
    sortie = [{'type': 'text', 'text': resume(resultat)}]
    for image in resultat.get('images', []):
        donnees, genre = apercu(image['png'])
        if donnees:
            sortie.append({'type': 'image', 'data': base64.b64encode(donnees).decode('ascii'), 'mimeType': f'image/{genre}'})
        else:
            sortie.append({'type': 'text', 'text': f'The image is too large to show here; open {image["path"]}.'})
    return sortie


def appeler_outil(prisme, nom, arguments):
    """Execute un outil ; renvoie le contenu MCP. Les erreurs de Prisme deviennent PrismeErreur."""
    a = arguments or {}
    texte = lambda donnees: [{'type': 'text', 'text': json.dumps(donnees, ensure_ascii=False, indent=2)}]
    if nom == 'generate_image':
        return contenu_resultat(prisme.generer(a.get('prompt'), a.get('width', 1024), a.get('height', 1024),
                                               a.get('seed'), a.get('model')))
    if nom == 'edit_image':
        return contenu_resultat(prisme.modifier(a.get('image_path'), a.get('instruction')))
    if nom == 'list_models':
        return texte(prisme.modeles())
    if nom == 'list_profiles':
        return texte(prisme.liste_profils())
    if nom == 'get_status':
        resultat = prisme.suivre(a.get('task_id'))
        return contenu_resultat(resultat) if resultat.get('status') == 'done' else texte(resultat)
    if nom == 'install_engine':
        return texte(prisme.installer_moteur(a.get('engine', 'image')))
    if nom == 'download_profile':
        return texte(prisme.telecharger_profil(a.get('profile_id')))
    if nom == 'download_model':
        return texte(prisme.telecharger_externe(a.get('url'), a.get('use_as')))
    raise KeyError(nom)


VERSIONS_PROTOCOLE = ('2025-06-18', '2025-03-26', '2024-11-05')


class ServeurMcp:
    """Protocole MCP (JSON-RPC 2.0, un message par ligne) sur l'entree et la sortie standard."""

    def __init__(self, prisme, version, entree, sortie):
        self.prisme, self.version, self.entree, self.sortie = prisme, version, entree, sortie
        self.verrou = threading.Lock()

    def envoyer(self, message):
        donnees = (json.dumps(message, ensure_ascii=False) + '\n').encode('utf-8')
        with self.verrou:
            self.sortie.write(donnees)
            self.sortie.flush()

    def repondre(self, ident, resultat=None, erreur=None):
        self.envoyer({'jsonrpc': '2.0', 'id': ident, **({'error': erreur} if erreur else {'result': resultat})})

    def traiter(self, message):
        methode, ident, params = message.get('method'), message.get('id'), message.get('params') or {}
        if ident is None:
            return  # notification (initialized, cancelled...) : rien a repondre
        if methode == 'initialize':
            demandee = params.get('protocolVersion')
            self.repondre(ident, {'protocolVersion': demandee if demandee in VERSIONS_PROTOCOLE else VERSIONS_PROTOCOLE[0],
                                  'capabilities': {'tools': {'listChanged': False}},
                                  'serverInfo': {'name': 'prisme', 'title': 'Prisme', 'version': self.version},
                                  'instructions': INSTRUCTIONS})
        elif methode == 'ping':
            self.repondre(ident, {})
        elif methode == 'tools/list':
            self.repondre(ident, {'tools': OUTILS})
        # Claude Desktop demande aussi ces listes a chaque serveur : Prisme n'en a pas, il le dit sans erreur
        elif methode == 'prompts/list':
            self.repondre(ident, {'prompts': []})
        elif methode == 'resources/list':
            self.repondre(ident, {'resources': []})
        elif methode == 'resources/templates/list':
            self.repondre(ident, {'resourceTemplates': []})
        elif methode == 'tools/call':
            nom = params.get('name')
            if nom not in {o['name'] for o in OUTILS}:
                return self.repondre(ident, erreur={'code': -32602, 'message': f'Unknown tool: {nom}'})
            # Une creation peut durer : l'outil tourne a part, le serveur reste disponible (ping, autres appels)
            threading.Thread(target=self.executer, args=(ident, nom, params.get('arguments')), daemon=True).start()
        else:
            self.repondre(ident, erreur={'code': -32601, 'message': f'Method not found: {methode}'})

    def executer(self, ident, nom, arguments):
        try:
            self.repondre(ident, {'content': appeler_outil(self.prisme, nom, arguments), 'isError': False})
        except PrismeErreur as e:
            self.repondre(ident, {'content': [{'type': 'text', 'text': str(e)}], 'isError': True})
        except OSError as e:
            self.repondre(ident, {'content': [{'type': 'text', 'text': f'File error: {e.strerror or e}'}], 'isError': True})
        except Exception as e:  # jamais de trace Python vers Claude
            self.repondre(ident, {'content': [{'type': 'text', 'text': f'Unexpected error in Prisme\'s MCP server: {e}'}],
                                  'isError': True})

    def boucle(self):
        for ligne in self.entree:
            if not ligne.strip():
                continue
            try:
                message = json.loads(ligne)
            except ValueError:
                self.envoyer({'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'Parse error'}})
                continue
            for m in message if isinstance(message, list) else [message]:
                if isinstance(m, dict) and m.get('method'):
                    self.traiter(m)


def principal(version='?', demarrage=None, racine=None):
    """Point d'entree : `Prisme --mcp` ou `python app/serveur.py --mcp`."""
    entree, sortie = sys.stdin.buffer, sys.stdout.buffer
    # Le protocole occupe la sortie standard : tout autre affichage part vers la sortie d'erreur
    sys.stdout = sys.stderr
    try:
        prisme = Prisme.depuis_environnement(demarrage=demarrage, racine=racine)
    except PrismeErreur as e:
        print(f'Prisme MCP: configuration error: {e}', file=sys.stderr)
        sys.exit(1)
    if '--check' in sys.argv:
        print(f'Prisme MCP {version}: {prisme.url}, timeout {prisme.delai:.0f} s, images in {prisme.dossier}', file=sys.stderr)
        print('Tools: ' + ', '.join(sorted(o['name'] for o in OUTILS)), file=sys.stderr)
        return
    ServeurMcp(prisme, version, entree, sortie).boucle()
