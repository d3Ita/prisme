"""Creation de videos (Prisme 2.0, en developpement) avec Wan 2.2 TI2V 5B, par le mode video de sd-cli.

Ce module ne connait ni le serveur ni ses reglages : il construit la commande du moteur, valide la demande et suit
la progression. serveur.py lui passe les fichiers, la fonction qui lance le moteur et celle qui met l'etat a jour.
Reglages mesures sur une RTX 4070 SUPER (12 Go) : voir le CHANGELOG et la PR de la branche video."""
import re
import time
from datetime import datetime
from pathlib import Path

# Wan 2.2 TI2V 5B produit 24 images par seconde ; son VAE demande un nombre d'images de la forme 4n + 1
IMAGES_PAR_SECONDE = 24
DUREES = (1, 2, 3, 4, 5)
# Tailles multiples de 32 (VAE de Wan 2.2), d'environ 0,4 et 0,9 million de pixels
TAILLES = {
    '480p': {'paysage': (832, 480), 'portrait': (480, 832), 'carre': (640, 640)},
    '704p': {'paysage': (1280, 704), 'portrait': (704, 1280), 'carre': (960, 960)},
}
ETAPES = 20
CFG = 5.0
DECALAGE = 3.0
# Description negative d'origine de Wan (en chinois) : ce que le modele doit eviter
NEGATIF = ('色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，低质量，JPEG压缩残留，丑陋的，'
           '残缺的，多余的手指，画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，杂乱的背景，'
           '三条腿，背景人很多，倒着走')
NOM_VIDEO = re.compile(r'^video_[\w.-]+\.webm$')
CLES = ('video_modele', 'video_texte', 'video_vae')
PAS = re.compile(r'(\d+)/(\d+)\s*-\s*[\d.,]+\s*(?:s/it|it/s)')
FIN_DESSIN = 'sampling completed'


def nombre_images(duree):
    return IMAGES_PAR_SECONDE * duree + 1


def taille(qualite, format_):
    return TAILLES[qualite][format_]


def valider(p):
    """Demande de video -> (parametres, None) ou (None, message d'erreur)."""
    try:
        prompt = str(p.get('prompt', '')).strip()
        qualite = str(p.get('qualite') or '480p')
        format_ = str(p.get('format') or 'paysage')
        duree = int(p.get('duree') or 2)
        seed = p.get('seed')
        seed = None if seed in (None, '') else int(seed)
    except (ValueError, TypeError):
        return None, 'Paramètres invalides.'
    if not prompt:
        return None, 'Écris d\'abord ce que tu veux voir dans la vidéo.'
    if qualite not in TAILLES or format_ not in TAILLES[qualite]:
        return None, 'Qualité ou format de vidéo inconnu.'
    if duree not in DUREES:
        return None, f'Durée possible : de {DUREES[0]} à {DUREES[-1]} secondes.'
    largeur, hauteur = taille(qualite, format_)
    return {'prompt': prompt, 'qualite': qualite, 'format': format_, 'duree': duree, 'seed': seed,
            'largeur': largeur, 'hauteur': hauteur, 'images': nombre_images(duree)}, None


def completer(r, modeles, connus):
    """Reglages video completes par les fichiers du catalogue deja dans le dossier models : des modeles Wan copies a la
    main, ou telecharges sans passer par la fenetre des modeles, servent sans avoir a choisir le profil.
    connus : {cle des reglages: [fichiers du catalogue qui la remplissent]}."""
    r = dict(r)
    for cle in CLES:
        if not r.get(cle):
            r[cle] = next((f for f in connus.get(cle, []) if (modeles / f).is_file()), '')
    return r


def fichiers_manquants(r, modeles):
    """Cles des reglages video sans fichier present dans le dossier models."""
    return [cle for cle in CLES if not r.get(cle) or not (modeles / r[cle]).is_file()]


def arguments(r, modeles, v, seed, source, sortie, fils=None):
    """Arguments de sd-cli pour une video. Le VAE de Wan 2.2 manque de memoire sur une carte de 12 Go s'il decode
    tout d'un coup, puis reessaie en morceaux de plus en plus petits (5 min au lieu de 2) : on le fait decoder
    tout de suite en morceaux d'un quart de l'image."""
    largeur, hauteur = v['largeur'], v['hauteur']
    return [
        '-M', 'vid_gen',
        '--diffusion-model', str(modeles / r['video_modele']),
        '--t5xxl', str(modeles / r['video_texte']),
        '--vae', str(modeles / r['video_vae']),
        '-p', v['prompt'], '-n', NEGATIF,
        '--steps', str(ETAPES), '--cfg-scale', str(CFG), '--sampling-method', 'euler', '--flow-shift', str(DECALAGE),
        '-W', str(largeur), '-H', str(hauteur),
        '--video-frames', str(v['images']), '--fps', str(IMAGES_PAR_SECONDE),
        '--seed', str(seed),
        '--vae-tiling', '--vae-tile-size', f'{largeur // 2}x{hauteur // 2}',
    ] + (['-i', str(source)] if source else []) + (['--threads', str(fils)] if fils else []) + ['-o', str(sortie)]


def nouveau_chemin(dossier):
    dossier.mkdir(parents=True, exist_ok=True)
    base = 'video_' + datetime.now().strftime('%Y%m%d_%H%M%S')
    chemin, n = dossier / (base + '.webm'), 2
    while chemin.exists():
        chemin = dossier / f'{base}_{n}.webm'
        n += 1
    return chemin


class Progression:
    """Lit la sortie de sd-cli : etapes de creation (n/20), puis morceaux decodes par le VAE (n/k)."""

    def __init__(self, rapporter):
        self.rapporter = rapporter
        self.phase = 'chargement'
        self.reste = ''
        self.journal = []

    def lire(self, bloc):
        lignes = re.split(r'[\r\n]+', self.reste + bloc)
        self.reste = lignes.pop()
        for ligne in lignes:
            if ligne.strip():
                self.journal = (self.journal + [ligne])[-80:]
            if FIN_DESSIN in ligne:
                self.phase = 'decodage'
                self.rapporter(phase='decodage', etape=0, total_decodage=0)
                continue
            pas = PAS.findall(ligne)
            if not pas:
                continue
            fait, total = map(int, pas[-1])
            if self.phase in ('chargement', 'dessin') and total == ETAPES:
                self.phase = 'dessin'
                self.rapporter(phase='dessin', etape=fait, total=ETAPES)
            elif self.phase == 'decodage':
                self.rapporter(phase='decodage', etape=fait, total_decodage=total)

    def erreurs(self):
        return [l for l in self.journal if re.search(r'^\[E\]|error|out of memory', l, re.I)]


def executer(commande, lancer, rapporter, annule):
    """Lance sd-cli et suit sa progression. lancer(commande) renvoie le processus (Popen, sortie en tube) ;
    rapporter(**champs) met a jour l'etat de Prisme ; annule() dit si l'utilisateur a arrete. Renvoie (code, erreurs)."""
    suivi = Progression(rapporter)
    processus = lancer(commande)
    while True:
        bloc = processus.stdout.read1(4096)
        if not bloc:
            break
        suivi.lire(bloc.decode('utf-8', 'replace'))
    code = processus.wait()
    return code, ([] if annule() else suivi.erreurs())


def infos(chemin, details=None):
    """Description d'une video pour la galerie : details enregistres a cote (prompt, taille, duree, seed)."""
    mtime = chemin.stat().st_mtime
    return {'nom': chemin.name, 'video': True, 'date': datetime.fromtimestamp(mtime).isoformat(timespec='seconds'),
            'version': int(mtime), 'taille_fichier': chemin.stat().st_size, **(details or {})}


def details_a_enregistrer(v, seed, source, duree_calcul):
    return {'prompt': v['prompt'], 'largeur': v['largeur'], 'hauteur': v['hauteur'], 'duree': v['duree'],
            'images': v['images'], 'ips': IMAGES_PAR_SECONDE, 'seed': seed, 'depuis_image': bool(source),
            'calcul_s': round(duree_calcul, 1), 'modele': 'Wan 2.2 TI2V 5B', 'cree': time.time()}


def chemin_details(chemin: Path):
    return chemin.with_suffix('.json')
