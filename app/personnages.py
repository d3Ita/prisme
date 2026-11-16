"""Fiches personnages : un nom, une description et une image de reference, pour garder le meme personnage d'une image
a l'autre (webtoon, manhwa). Rangees dans le dossier personnages/ a cote des images : une copie de l'image, pour que la
fiche reste valable meme si l'image d'origine est mise a la corbeille."""
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

# Personnages dans une meme creation : chaque image de reference alourdit le calcul
NOMBRE_MAX = 2
LONGUEUR_NOM = 40
LONGUEUR_DESCRIPTION = 400
TAILLE_MAX_IMAGE = 20 * 2**20
SIGNATURES = ((b'\x89PNG\r\n\x1a\n', '.png'), (b'\xff\xd8\xff', '.jpg'))
IDENTIFIANT = re.compile(r'p-[0-9a-f]{12}')
FICHIER_IMAGE = re.compile(r'p-[0-9a-f]{12}\.(png|jpg)')


def propre(texte, longueur):
    return ' '.join(str(texte or '').split())[:longueur]


def extension(octets):
    return next((e for signature, e in SIGNATURES if octets.startswith(signature)), None)


class Personnages:
    def __init__(self, dossier):
        self.dossier = Path(dossier)
        self.verrou = threading.Lock()

    @property
    def fichier(self):
        return self.dossier / 'personnages.json'

    def lister(self):
        """Les fiches dont l'image est toujours la, les plus recentes d'abord."""
        try:
            liste = json.loads(self.fichier.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return []
        fiches = [p for p in liste if isinstance(p, dict) and IDENTIFIANT.fullmatch(str(p.get('id', '')))
                  and FICHIER_IMAGE.fullmatch(str(p.get('image', ''))) and (self.dossier / p['image']).is_file()]
        return sorted(({'id': p['id'], 'nom': propre(p.get('nom'), LONGUEUR_NOM),
                        'description': propre(p.get('description'), LONGUEUR_DESCRIPTION), 'image': p['image'],
                        'cree': p.get('cree') or 0} for p in fiches), key=lambda p: -p['cree'])

    def _ecrire(self, fiches):
        self.dossier.mkdir(parents=True, exist_ok=True)
        provisoire = self.fichier.with_suffix('.tmp')
        provisoire.write_text(json.dumps(fiches, ensure_ascii=False, indent=1), encoding='utf-8')
        os.replace(provisoire, self.fichier)

    def creer(self, nom, description, image):
        """Nouvelle fiche ; image : les octets d'une image PNG ou JPEG."""
        nom, description = propre(nom, LONGUEUR_NOM), propre(description, LONGUEUR_DESCRIPTION)
        if not nom:
            raise ValueError('Donne un nom au personnage.')
        if not image or len(image) > TAILLE_MAX_IMAGE or not extension(image):
            raise ValueError('Image de référence invalide : PNG ou JPEG, 20 Mo au plus.')
        with self.verrou:
            fiches = self.lister()
            if any(p['nom'].lower() == nom.lower() for p in fiches):
                raise ValueError(f'Un personnage s\'appelle déjà {nom}.')
            ident = 'p-' + secrets.token_hex(6)
            self.dossier.mkdir(parents=True, exist_ok=True)
            (self.dossier / (ident + extension(image))).write_bytes(image)
            fiche = {'id': ident, 'nom': nom, 'description': description, 'image': ident + extension(image), 'cree': time.time()}
            self._ecrire(fiches + [fiche])
        return fiche

    def modifier(self, ident, nom, description):
        nom, description = propre(nom, LONGUEUR_NOM), propre(description, LONGUEUR_DESCRIPTION)
        if not nom:
            raise ValueError('Donne un nom au personnage.')
        with self.verrou:
            fiches = self.lister()
            fiche = next((p for p in fiches if p['id'] == ident), None)
            if not fiche:
                raise ValueError('Personnage introuvable.')
            if any(p['nom'].lower() == nom.lower() and p['id'] != ident for p in fiches):
                raise ValueError(f'Un personnage s\'appelle déjà {nom}.')
            fiche.update(nom=nom, description=description)
            self._ecrire(fiches)
        return fiche

    def supprimer(self, ident):
        with self.verrou:
            fiches = self.lister()
            fiche = next((p for p in fiches if p['id'] == ident), None)
            if not fiche:
                raise ValueError('Personnage introuvable.')
            self._ecrire([p for p in fiches if p['id'] != ident])
            (self.dossier / fiche['image']).unlink(missing_ok=True)

    def choisir(self, idents):
        """Les fiches demandees pour une creation, dans l'ordre, ou ValueError."""
        if not isinstance(idents, list) or not all(isinstance(i, str) for i in idents):
            raise ValueError('Personnages invalides.')
        if len(set(idents)) != len(idents) or len(idents) > NOMBRE_MAX:
            raise ValueError(f'Choisis {NOMBRE_MAX} personnages au plus.')
        fiches = {p['id']: p for p in self.lister()}
        if any(i not in fiches for i in idents):
            raise ValueError('Personnage introuvable : il a peut-être été supprimé.')
        return [fiches[i] for i in idents]

    def image(self, nom):
        """Chemin de l'image d'une fiche (nom de fichier controle), ou None."""
        chemin = self.dossier / nom
        return chemin if FICHIER_IMAGE.fullmatch(nom) and chemin.is_file() else None


def description_pour_le_moteur(prompt, fiches, decalage=0):
    """La description, suivie de chaque personnage et de son image de reference (numerotee comme les -r du moteur ;
    decalage : images de reference placees avant, comme l'image de depart d'une modification)."""
    if not fiches:
        return prompt
    lignes = [f'{p["nom"]} (image {i + 1 + decalage})' + (f' : {p["description"]}' if p['description'] else '')
              for i, p in enumerate(fiches)]
    return prompt + '\n' + '\n'.join(lignes)
