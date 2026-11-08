"""Client de Prisme pour le serveur MCP : uniquement la bibliotheque standard, pour etre teste sans le SDK MCP.

Il parle a l'API HTTP locale de Prisme (app/serveur.py) :
  GET  /api/etat        etat de la creation en cours, problemes de configuration
  POST /api/generer     lance une creation, ou une modification avec source_data
  GET  /images/<nom>    image PNG terminee
  GET  /api/reglages    modeles choisis et fichiers du dossier models (PC seulement)
  GET  /api/profils     profils de modeles et profil suggere (PC seulement)

Les messages d'erreur sont faits pour etre lus par Claude puis par l'utilisateur : pas de trace Python.
"""

import base64
import json
import os
import re
import socket
import struct
import time
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
COMMENT_TELECHARGER = ('In Prisme, click "Download the models" (Télécharger les modèles), pick that profile, '
                       'then "Download this profile".')


class PrismeErreur(Exception):
    """Erreur expliquee a l'utilisateur ; le message suffit, sans trace."""


def configuration(environ=None):
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
        delai = float(environ.get('PRISME_TIMEOUT') or 120)
    except ValueError:
        raise PrismeErreur('PRISME_TIMEOUT must be a number of seconds.') from None
    if not 1 <= delai <= 3600:
        raise PrismeErreur('PRISME_TIMEOUT must be between 1 and 3600 seconds.')
    dossier = Path(environ.get('PRISME_OUTPUT_DIR') or Path.home() / 'Prisme-MCP').expanduser()
    return {'url': url, 'delai': delai, 'dossier': dossier}


class Prisme:
    def __init__(self, url, delai=120, dossier=None, pause=1.0):
        self.url, self.delai, self.pause = url.rstrip('/'), delai, pause
        self.dossier = Path(dossier or Path.home() / 'Prisme-MCP').expanduser()

    @classmethod
    def depuis_environnement(cls, environ=None):
        c = configuration(environ)
        return cls(c['url'], c['delai'], c['dossier'])

    # --- HTTP
    def requete(self, chemin, corps=None, brut=False, delai=30):
        donnees = None if corps is None else json.dumps(corps).encode('utf-8')
        requete = urllib.request.Request(self.url + chemin, data=donnees, method='POST' if corps is not None else 'GET',
                                         headers={'Content-Type': 'application/json'} if corps is not None else {})
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
        if e.get('occupe'):
            statut.update(task_id=identifiant_tache(e), step=e.get('etape'), steps=e.get('total'),
                          image=e.get('index'), images=e.get('nombre'), elapsed_seconds=e.get('ecoule'))
        if e.get('erreur'):
            statut['error'] = e['erreur']
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
                    'category': 'main' if p.get('categorie', 'principal') == 'principal' else 'option',
                    'license_to_accept': bool(p.get('licence_a_accepter')),
                    'speed': p['vitesse']['en'], 'models': [m['fichier'] for m in p['modeles']]}
                   for p in infos.get('profils', [])]
        return {'suggested_profile': infos.get('suggestion'), 'default_profile': infos.get('conseille'),
                'free_disk_gb': round(infos.get('libre', 0) / 1e9, 1), 'profiles': profils,
                'how_to_download': COMMENT_TELECHARGER}

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
            contenu = self.requete('/images/' + quote(nom), brut=True, delai=60)
            chemin = self.dossier / nom
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
        if identifiant_tache(etat) != str(task_id):
            raise PrismeErreur(f'Task {task_id} is not Prisme\'s latest creation anymore. Its images are in Prisme\'s '
                               'image list.')
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
        return None, None
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
