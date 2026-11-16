"""Planche verticale d'un webtoon : les images d'un projet, dans l'ordre choisi, les unes sous les autres, avec un
espace entre elles, exportees en morceaux au format des plateformes. Ici, seulement les calculs (ordre, positions,
decoupe) : l'assemblage des pixels se fait dans la fenetre de Prisme (Qt), morceau par morceau."""
import json
import os
import re
import threading
from pathlib import Path

# Largeurs des plateformes : Webtoon Canvas et Naver (800), Tapas (940), et une largeur courante pour le reste
LARGEURS = (800, 940, 1080)
# Hauteur de chaque morceau : 1280 px au plus sur Webtoon Canvas ; 0 = une seule image
DECOUPES = (1280, 0)
GOUTTIERE_MAX = 400
FONDS = ('#ffffff', '#000000')
FORMATS = ('jpg', 'png')
# Une seule image : au-dela, Qt ne sait plus dessiner (coordonnees sur 16 bits dans certains cas)
HAUTEUR_MAX_UNE_IMAGE = 30000
REGLAGES_DEFAUT = {'largeur': 800, 'gouttiere': 80, 'fond': '#ffffff', 'decoupe': 1280, 'format': 'jpg'}


def reglages_propres(r):
    """Reglages d'une planche, valeurs inconnues remplacees par celles par defaut."""
    r = r if isinstance(r, dict) else {}
    propre = dict(REGLAGES_DEFAUT)
    if r.get('largeur') in LARGEURS:
        propre['largeur'] = r['largeur']
    if isinstance(r.get('gouttiere'), int) and 0 <= r['gouttiere'] <= GOUTTIERE_MAX:
        propre['gouttiere'] = r['gouttiere']
    if r.get('fond') in FONDS:
        propre['fond'] = r['fond']
    if r.get('decoupe') in DECOUPES:
        propre['decoupe'] = r['decoupe']
    if r.get('format') in FORMATS:
        propre['format'] = r['format']
    return propre


def ordonner(images, ordre, retirees):
    """Cases de la planche : celles deja placees (ordre), puis les nouvelles images du projet de la plus ancienne a la
    plus recente (un webtoon se lit de haut en bas, dans l'ordre de creation). images : du projet, la plus ancienne
    d'abord. Les images retirees n'y sont pas ; celles qui n'existent plus sont oubliees."""
    presentes = set(images)
    retirees = [n for n in retirees if n in presentes]
    cases = [n for n in dict.fromkeys(ordre) if n in presentes and n not in retirees]
    cases += [n for n in images if n not in cases and n not in retirees]
    return cases, retirees


def mise_en_page(tailles, largeur, gouttiere):
    """Position de chaque case, mise a la largeur de la planche : [(y, hauteur)], et la hauteur totale.
    tailles : [(largeur, hauteur)] des images. Pas d'espace avant la premiere ni apres la derniere case."""
    positions, y = [], 0
    for i, (l, h) in enumerate(tailles):
        if i:
            y += gouttiere
        hauteur = max(1, round(h * largeur / l)) if l > 0 and h > 0 else 0
        positions.append((y, hauteur))
        y += hauteur
    return positions, y


def decouper(positions, total, hauteur_max):
    """Morceaux [(y, hauteur)] de hauteur_max au plus. Une coupe tombe de preference dans un espace entre deux cases
    (le plus bas possible), sinon dans une case. hauteur_max 0 : une seule image."""
    if total <= 0:
        return []
    if not hauteur_max or total <= hauteur_max:
        return [(0, total)]
    # Debut de chaque espace entre deux cases (une coupe a cet endroit ne traverse aucune image)
    espaces = [y + h for (y, h), (y2, _) in zip(positions, positions[1:]) if y2 > y + h]
    morceaux, debut = [], 0
    while total - debut > hauteur_max:
        limite = debut + hauteur_max
        # Un espace dans la seconde moitie du morceau, pour ne pas faire de tout petits morceaux
        coupe = max((e for e in espaces if debut + hauteur_max // 2 <= e <= limite), default=limite)
        morceaux.append((debut, coupe - debut))
        debut = coupe
    morceaux.append((debut, total - debut))
    return morceaux


def nom_de_fichier(projet):
    """Base des fichiers exportes : le nom du projet sans caracteres interdits."""
    return re.sub(r'[^\w.-]+', '-', projet, flags=re.UNICODE).strip('-.') or 'planche'


class Planches:
    """Ordre et reglages de chaque planche, dans planches.json a cote des images : {projet: {ordre, retirees, ...}}."""

    def __init__(self, dossier):
        self.dossier = Path(dossier)
        self.verrou = threading.Lock()

    @property
    def fichier(self):
        return self.dossier / 'planches.json'

    def lire(self):
        try:
            donnees = json.loads(self.fichier.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}
        return donnees if isinstance(donnees, dict) else {}

    def planche(self, projet, images):
        """Cases, images retirees et reglages de la planche d'un projet (images : du projet, la plus ancienne d'abord)."""
        p = self.lire().get(projet) or {}
        cases, retirees = ordonner(images, p.get('ordre') or [], p.get('retirees') or [])
        return {'projet': projet, 'cases': cases, 'retirees': retirees, 'reglages': reglages_propres(p.get('reglages'))}

    def enregistrer(self, projet, ordre, retirees, reglages):
        if not isinstance(ordre, list) or not isinstance(retirees, list) \
                or not all(isinstance(n, str) for n in ordre + retirees):
            raise ValueError('Planche invalide.')
        with self.verrou:
            donnees = self.lire()
            donnees[projet] = {'ordre': ordre, 'retirees': retirees, 'reglages': reglages_propres(reglages)}
            self.dossier.mkdir(parents=True, exist_ok=True)
            provisoire = self.fichier.with_suffix('.tmp')
            provisoire.write_text(json.dumps(donnees, ensure_ascii=False, indent=1), encoding='utf-8')
            os.replace(provisoire, self.fichier)
