"""Tests des fiches personnages (webtoon, manhwa) : nom, description et image de reference gardes d'une image a l'autre.

Lancement : py -3 -m unittest tests.test_personnages -v
"""

import base64
import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

DOSSIER = tempfile.TemporaryDirectory(prefix='prisme_tests_personnages_', ignore_cleanup_errors=True)
if 'serveur' not in sys.modules:
    os.environ['PRISME_RACINE'] = DOSSIER.name
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'app'))

import personnages  # noqa: E402
import serveur  # noqa: E402

PNG = b'\x89PNG\r\n\x1a\n' + b'x' * 50
JPEG = b'\xff\xd8\xff' + b'x' * 50


def tearDownModule():
    DOSSIER.cleanup()


class FichesTest(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.dossier.cleanup)
        self.fiches = personnages.Personnages(Path(self.dossier.name) / 'personnages')

    def test_creer_modifier_supprimer(self):
        mina = self.fiches.creer('  Mina ', 'cheveux   courts noirs, veste rouge', PNG)
        jun = self.fiches.creer('Jun', '', JPEG)
        self.assertEqual((mina['nom'], mina['description']), ('Mina', 'cheveux courts noirs, veste rouge'))
        self.assertTrue(mina['image'].endswith('.png') and jun['image'].endswith('.jpg'))
        self.assertEqual((self.fiches.dossier / mina['image']).read_bytes(), PNG)
        # Les plus recentes d'abord
        self.assertEqual([p['nom'] for p in self.fiches.lister()], ['Jun', 'Mina'])
        self.fiches.modifier(mina['id'], 'Mina Park', 'cheveux longs')
        self.assertEqual(self.fiches.choisir([mina['id']])[0]['description'], 'cheveux longs')
        self.fiches.supprimer(jun['id'])
        self.assertEqual([p['nom'] for p in self.fiches.lister()], ['Mina Park'])
        self.assertFalse((self.fiches.dossier / jun['image']).exists())

    def test_refus(self):
        self.fiches.creer('Mina', '', PNG)
        for nom, image in (('', PNG), ('mina', PNG), ('Jun', b'GIF89a'), ('Jun', b''), ('Jun', PNG[:8] + b'x' * (21 * 2**20))):
            with self.subTest(nom=nom, image=image[:6]):
                with self.assertRaises(ValueError):
                    self.fiches.creer(nom, '', image)
        with self.assertRaises(ValueError):
            self.fiches.modifier('p-000000000000', 'X', '')
        with self.assertRaises(ValueError):
            self.fiches.supprimer('p-000000000000')

    def test_choisir_deux_au_plus(self):
        idents = [self.fiches.creer(n, '', PNG)['id'] for n in ('A', 'B', 'C')]
        self.assertEqual([p['nom'] for p in self.fiches.choisir(idents[:2])], ['A', 'B'])
        for mauvais in (idents, [idents[0], idents[0]], ['p-000000000000'], 'p-1', [1]):
            with self.subTest(mauvais=mauvais):
                with self.assertRaises(ValueError):
                    self.fiches.choisir(mauvais)

    def test_image_controlee(self):
        mina = self.fiches.creer('Mina', '', PNG)
        self.assertEqual(self.fiches.image(mina['image']), self.fiches.dossier / mina['image'])
        for nom in ('personnages.json', '../x.png', 'p-zz.png', ''):
            with self.subTest(nom=nom):
                self.assertIsNone(self.fiches.image(nom))

    def test_fiche_sans_image_ignoree(self):
        mina = self.fiches.creer('Mina', '', PNG)
        (self.fiches.dossier / mina['image']).unlink()
        self.assertEqual(self.fiches.lister(), [])

    def test_description_pour_le_moteur(self):
        a = {'nom': 'Mina', 'description': 'veste rouge'}
        b = {'nom': 'Jun', 'description': ''}
        self.assertEqual(personnages.description_pour_le_moteur('dans un café', []), 'dans un café')
        self.assertEqual(personnages.description_pour_le_moteur('dans un café', [a, b]),
                         'dans un café\nMina (image 1) : veste rouge\nJun (image 2)')
        # Avec une image de depart (modification), elle est l'image 1
        self.assertEqual(personnages.description_pour_le_moteur('ajoute Mina', [a], 1), 'ajoute Mina\nMina (image 2) : veste rouge')


class MoteurTest(unittest.TestCase):
    def test_plusieurs_images_de_reference(self):
        r = dict(serveur.REGLAGES_DEFAUT, modele_diffusion='d.gguf', modele_texte='t.gguf', vae='v.safetensors', modele_vision='m.gguf')
        a = serveur.arguments(r, 'x', 720, 1280, 1, [Path('depart.png'), Path('mina.png')], Path('s.png'), vision=False)
        self.assertEqual([a[i + 1] for i, v in enumerate(a) if v == '-r'], ['depart.png', 'mina.png'])
        self.assertNotIn('--llm_vision', a)
        a = serveur.arguments(r, 'x', 720, 1280, 1, Path('depart.png'), Path('s.png'))
        self.assertEqual(a.count('-r'), 1)
        self.assertIn('--llm_vision', a)
        self.assertNotIn('-r', serveur.arguments(r, 'x', 720, 1280, 1, None, Path('s.png')))


class RoutesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.serveur = serveur.Serveur(('127.0.0.1', 0), serveur.Gestionnaire)
        cls.port = cls.serveur.server_address[1]
        threading.Thread(target=cls.serveur.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.serveur.shutdown()
        cls.serveur.server_close()

    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.dossier.cleanup)
        racine = Path(self.dossier.name)
        (racine / 'images').mkdir()
        self.images = racine / 'images'
        self.fiches = personnages.Personnages(racine / 'personnages')
        for patch in (mock.patch.object(serveur, 'PORT', self.port), mock.patch.object(serveur, 'dernier_contact_mcp', 0.0),
                      mock.patch.object(serveur, 'PERSONNAGES', self.fiches), mock.patch.object(serveur, 'IMAGES', self.images)):
            patch.start()
            self.addCleanup(patch.stop)
        serveur.etat.clear()
        serveur.etat['occupe'] = False

    def requete(self, methode, chemin, corps=None, entetes=None):
        connexion = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        connexion.request(methode, chemin, json.dumps(corps).encode() if corps is not None else None,
                          {'Host': f'127.0.0.1:{self.port}', 'Content-Type': 'application/json', **(entetes or {})})
        reponse = connexion.getresponse()
        donnees = reponse.read()
        connexion.close()
        try:
            return reponse.status, json.loads(donnees or b'{}')
        except ValueError:
            return reponse.status, donnees

    def test_creer_depuis_la_galerie_et_un_fichier(self):
        (self.images / 'image_20261116_120000.png').write_bytes(PNG)
        code, mina = self.requete('POST', '/api/personnages', {'nom': 'Mina', 'description': 'veste rouge', 'source_nom': 'image_20261116_120000.png'})
        self.assertEqual(code, 200)
        code, jun = self.requete('POST', '/api/personnages', {'nom': 'Jun', 'source_data': 'data:image/jpeg;base64,' + base64.b64encode(JPEG).decode()})
        self.assertEqual(code, 200)
        code, liste = self.requete('GET', '/api/personnages')
        self.assertEqual([p['nom'] for p in liste['personnages']], ['Jun', 'Mina'])
        self.assertEqual(liste['nombre_max'], 2)
        self.assertEqual(self.requete('GET', '/personnages/' + mina['image']), (200, PNG))
        # Modifier, supprimer
        self.assertEqual(self.requete('POST', '/api/personnages', {'id': mina['id'], 'nom': 'Mina', 'description': 'cheveux longs'})[1]['description'], 'cheveux longs')
        self.assertEqual(self.requete('POST', '/api/personnages/supprimer', {'id': jun['id']})[0], 200)
        self.assertEqual(len(self.requete('GET', '/api/personnages')[1]['personnages']), 1)

    def test_refus(self):
        for corps in ({'nom': 'Mina', 'source_nom': '../reglages.json'}, {'nom': 'Mina', 'source_nom': 'image_20261116_120000.png'},
                      {'nom': 'Mina', 'source_data': 'data:image/png;base64,!!!'}, {'nom': '', 'source_data': 'data:,'}):
            with self.subTest(corps=corps):
                code, reponse = self.requete('POST', '/api/personnages', corps)
                self.assertEqual(code, 400)
                self.assertTrue(reponse['erreur'][:1].isupper())
        self.assertEqual(self.requete('GET', '/personnages/personnages.json')[0], 404)
        # Ni Claude, ni le telephone
        for methode, chemin in (('GET', '/api/personnages'), ('POST', '/api/personnages'), ('POST', '/api/personnages/supprimer')):
            with self.subTest(chemin=chemin):
                self.assertEqual(self.requete(methode, chemin, {} if methode == 'POST' else None, {'X-Prisme-Client': 'mcp'})[0], 403)

    def test_creation_avec_personnages(self):
        mina = self.fiches.creer('Mina', 'veste rouge', PNG)
        appel = threading.Event()
        with mock.patch.object(serveur, 'generer', side_effect=lambda params: appel.set()) as generer:
            code, _ = self.requete('POST', '/api/generer', {'prompt': 'dans un café', 'largeur': 720, 'hauteur': 1280, 'personnages': [mina['id']]})
            self.assertTrue(appel.wait(5))
        self.assertEqual(code, 200)
        self.assertEqual([p['nom'] for p in generer.call_args[0][0]['personnages']], ['Mina'])
        serveur.etat['occupe'] = False
        for corps, attendu in (({'personnages': ['p-000000000000']}, 400), ({'personnages': [mina['id']] * 3}, 400),
                               ({'personnages': [mina['id']], 'comparer': ['a', 'b']}, 400)):
            with self.subTest(corps=corps):
                self.assertEqual(self.requete('POST', '/api/generer', {'prompt': 'x', **corps})[0], attendu)
        # Claude ne se sert pas des personnages (ils viennent des images de l'utilisateur)
        self.assertEqual(self.requete('POST', '/api/generer', {'prompt': 'x', 'personnages': [mina['id']]}, {'X-Prisme-Client': 'mcp'})[0], 403)


class GenerationTest(unittest.TestCase):
    """generer() avec un faux moteur : les images de reference et la description recues par sd-cli."""

    def test_references_et_description(self):
        dossier = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(dossier.cleanup)
        fiches = personnages.Personnages(Path(dossier.name) / 'personnages')
        mina = fiches.creer('Mina', 'veste rouge', PNG)
        r = dict(serveur.REGLAGES_DEFAUT, modele_diffusion='flux-2-klein-4b-Q8_0.gguf', modele_texte='t.gguf', vae='v.safetensors')
        commandes = []
        # Un autre test a pu laisser une annulation en cours : elle arreterait la boucle avant le moteur
        self.addCleanup(setattr, serveur, 'annule', serveur.annule)
        serveur.annule = False
        images = mock.patch.object(serveur, 'IMAGES', Path(dossier.name) / 'images')
        images.start()
        self.addCleanup(images.stop)

        def lancer(commande, **_):
            commandes.append(commande)
            raise RuntimeError('arret du test')

        with mock.patch.object(serveur, 'PERSONNAGES', fiches), mock.patch.object(serveur, 'lancer_moteur', lancer), \
                mock.patch.object(serveur, 'modeles_manquants', return_value=[]), mock.patch.object(serveur, 'mode_edition', return_value='reference'):
            serveur.etat.update(occupe=True, resultats=[])
            serveur.generer(dict(prompt='dans un café', largeur=720, hauteur=1280, nombre=1, seed=1, reglages=r, source_nom=None,
                                 source_data=None, claude=False, liste_reglages=None, comparaison=None, projet=None, personnages=[mina]))
        self.assertTrue(commandes, serveur.etat.get('erreur'))
        commande = commandes[0]
        self.assertEqual(commande[commande.index('-r') + 1], str(fiches.dossier / mina['image']))
        self.assertEqual(commande[commande.index('-p') + 1], 'dans un café\nMina (image 1) : veste rouge')
        # Un modele qui ne sait pas partir d'une image : message clair, pas de moteur lance
        commandes.clear()
        with mock.patch.object(serveur, 'PERSONNAGES', fiches), mock.patch.object(serveur, 'lancer_moteur', lancer), \
                mock.patch.object(serveur, 'modeles_manquants', return_value=[]), mock.patch.object(serveur, 'mode_edition', return_value=None):
            serveur.etat.update(occupe=True, resultats=[], erreur=None)
            serveur.generer(dict(prompt='x', largeur=720, hauteur=1280, nombre=1, seed=1, reglages=r, source_nom=None, source_data=None,
                                 claude=False, liste_reglages=None, comparaison=None, projet=None, personnages=[mina]))
        self.assertEqual(commandes, [])
        self.assertIn('personnage', serveur.etat['erreur'])


if __name__ == '__main__':
    unittest.main()
