"""Tests de la planche webtoon : ordre des cases, mise en page, decoupe en morceaux, routes et export.

Lancement : py -3 -m unittest tests.test_planches -v
"""

import http.client
import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

DOSSIER = tempfile.TemporaryDirectory(prefix='prisme_tests_planches_', ignore_cleanup_errors=True)
if 'serveur' not in sys.modules:
    os.environ['PRISME_RACINE'] = DOSSIER.name
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'app'))

import planches  # noqa: E402
import serveur  # noqa: E402

QT = importlib.util.find_spec('PySide6') is not None


def tearDownModule():
    DOSSIER.cleanup()


class CalculsTest(unittest.TestCase):
    def test_ordre(self):
        images = ['a', 'b', 'c', 'd']
        # Rien de place : ordre de creation
        self.assertEqual(planches.ordonner(images, [], []), (['a', 'b', 'c', 'd'], []))
        # Ordre choisi, puis les nouvelles images en bas ; les retirees n'y sont pas, les disparues sont oubliees
        self.assertEqual(planches.ordonner(images, ['c', 'a', 'x', 'c'], ['b', 'y']), (['c', 'a', 'd'], ['b']))

    def test_mise_en_page(self):
        positions, total = planches.mise_en_page([(1024, 1024), (720, 1280), (0, 0)], 800, 80)
        self.assertEqual(positions, [(0, 800), (880, 1422), (2382, 0)])
        self.assertEqual(total, 2382)
        self.assertEqual(planches.mise_en_page([], 800, 80), ([], 0))

    def test_decoupe(self):
        # Une seule image, ou une planche courte : un morceau
        self.assertEqual(planches.decouper([(0, 800)], 800, 0), [(0, 800)])
        self.assertEqual(planches.decouper([(0, 800)], 800, 1280), [(0, 800)])
        self.assertEqual(planches.decouper([], 0, 1280), [])
        # Deux cases de 800 et un espace de 80 : la coupe tombe dans l'espace, pas dans une case
        positions, total = planches.mise_en_page([(1, 1), (1, 1)], 800, 80)
        self.assertEqual(planches.decouper(positions, total, 1280), [(0, 800), (800, 880)])
        # Une case tres haute : coupee a la hauteur maximale ; chaque morceau en respecte la limite
        positions, total = planches.mise_en_page([(800, 4000)], 800, 0)
        morceaux = planches.decouper(positions, total, 1280)
        self.assertEqual(morceaux, [(0, 1280), (1280, 1280), (2560, 1280), (3840, 160)])
        # Un espace trop haut dans le morceau (premiere moitie) ne fait pas de tout petit morceau
        positions, total = planches.mise_en_page([(1, 1), (1, 1)], 400, 0)
        self.assertTrue(all(h <= 1280 for _, h in planches.decouper(positions, total, 1280)))
        positions, total = planches.mise_en_page([(800, 300), (800, 2000)], 800, 50)
        self.assertEqual(planches.decouper(positions, total, 1280), [(0, 1280), (1280, 1070)])

    def test_reglages(self):
        self.assertEqual(planches.reglages_propres(None), planches.REGLAGES_DEFAUT)
        r = planches.reglages_propres({'largeur': 940, 'gouttiere': 0, 'fond': '#000000', 'decoupe': 0, 'format': 'png'})
        self.assertEqual(r, {'largeur': 940, 'gouttiere': 0, 'fond': '#000000', 'decoupe': 0, 'format': 'png'})
        r = planches.reglages_propres({'largeur': 123, 'gouttiere': 999, 'fond': 'red', 'decoupe': 5, 'format': 'gif'})
        self.assertEqual(r, planches.REGLAGES_DEFAUT)

    def test_nom_de_fichier(self):
        self.assertEqual(planches.nom_de_fichier('Épisode 1 : la pluie'), 'Épisode-1-la-pluie')
        self.assertEqual(planches.nom_de_fichier('../..'), 'planche')


def creer_png(chemin, largeur, hauteur, couleur=b'\xff\x00\x00'):
    """Un vrai PNG uni, sans dependance."""
    import struct
    import zlib
    brut = b''.join(b'\x00' + couleur * largeur for _ in range(hauteur))
    morceau = lambda genre, donnees: struct.pack('>I', len(donnees)) + genre + donnees + struct.pack('>I', zlib.crc32(genre + donnees))
    chemin.write_bytes(b'\x89PNG\r\n\x1a\n' + morceau(b'IHDR', struct.pack('>IIBBBBB', largeur, hauteur, 8, 2, 0, 0, 0))
                       + morceau(b'IDAT', zlib.compress(brut)) + morceau(b'IEND', b''))


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
        self.images = Path(self.dossier.name) / 'images'
        self.images.mkdir()
        for patch in (mock.patch.object(serveur, 'PORT', self.port), mock.patch.object(serveur, 'dernier_contact_mcp', 0.0),
                      mock.patch.object(serveur, 'IMAGES', self.images)):
            patch.start()
            self.addCleanup(patch.stop)
        # Trois cases dans le projet, une image hors projet ; dates de creation croissantes
        self.noms = [f'image_20261116_12000{i}.png' for i in range(4)]
        for i, nom in enumerate(self.noms):
            creer_png(self.images / nom, 16, 32 if i == 1 else 16)
            os.utime(self.images / nom, (1000 + i, 1000 + i))
        serveur.ranger(self.noms[:3], 'Épisode 1')

    def requete(self, methode, chemin, corps=None, entetes=None):
        connexion = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        connexion.request(methode, chemin, json.dumps(corps).encode() if corps is not None else None,
                          {'Host': f'127.0.0.1:{self.port}', 'Content-Type': 'application/json', **(entetes or {})})
        reponse = connexion.getresponse()
        resultat = reponse.status, json.loads(reponse.read() or b'{}')
        connexion.close()
        return resultat

    def test_lire_et_enregistrer(self):
        code, p = self.requete('GET', '/api/planche?projet=%C3%89pisode%201')
        self.assertEqual(code, 200)
        self.assertEqual([c['nom'] for c in p['cases']], self.noms[:3])
        self.assertEqual((p['cases'][1]['largeur'], p['cases'][1]['hauteur']), (16, 32))
        self.assertEqual(p['reglages'], planches.REGLAGES_DEFAUT)
        code, p = self.requete('POST', '/api/planche', {'projet': 'Épisode 1', 'ordre': [self.noms[2], self.noms[0]],
                                                        'retirees': [self.noms[1]], 'reglages': {'largeur': 940, 'gouttiere': 0}})
        self.assertEqual(code, 200)
        self.assertEqual(([c['nom'] for c in p['cases']], p['retirees'], p['reglages']['largeur']), ([self.noms[2], self.noms[0]], [self.noms[1]], 940))
        # Une nouvelle image rangee dans le projet arrive en bas
        serveur.ranger([self.noms[3]], 'Épisode 1')
        self.assertEqual([c['nom'] for c in self.requete('GET', '/api/planche?projet=%C3%89pisode%201')[1]['cases']],
                         [self.noms[2], self.noms[0], self.noms[3]])

    def test_refus(self):
        self.assertEqual(self.requete('GET', '/api/planche')[0], 400)
        self.assertEqual(self.requete('POST', '/api/planche', {'projet': 'x', 'ordre': 'pas une liste'})[0], 400)
        self.assertEqual(self.requete('GET', '/api/planche?projet=x', entetes={'X-Prisme-Client': 'mcp'})[0], 403)
        self.assertEqual(self.requete('POST', '/api/planche', {'projet': 'x'}, {'X-Prisme-Client': 'mcp'})[0], 403)

    @unittest.skipUnless(QT, 'PySide6 absent')
    def test_export(self):
        from PySide6.QtGui import QGuiApplication, QImage
        import fenetre_qt
        appli = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
        self.assertIsNotNone(appli)
        _, p = self.requete('GET', '/api/planche?projet=%C3%89pisode%201')
        sortie = Path(self.dossier.name) / 'export'
        sortie.mkdir()
        # 16 px de large mis a 800 : cases de 800, 1600 et 800 px, espaces de 80 px
        p['reglages'].update(decoupe=1280, format='png')
        r = json.loads(fenetre_qt.Fichiers().exporterPlanche(f'http://127.0.0.1:{self.port}', json.dumps(p), str(sortie)))
        self.assertEqual(r['hauteur'], 800 + 80 + 1600 + 80 + 800)
        self.assertEqual(r['fichiers'], [f'Épisode-1_0{i}.png' for i in range(1, len(r['fichiers']) + 1)])
        hauteurs = [QImage(str(sortie / f)).height() for f in r['fichiers']]
        self.assertEqual(sum(hauteurs), r['hauteur'])
        self.assertTrue(all(h <= 1280 for h in hauteurs))
        image = QImage(str(sortie / r['fichiers'][0]))
        self.assertEqual(image.width(), 800)
        # Le haut est la premiere case (rouge), et la coupe tombe dans l'espace blanc qui la suit
        self.assertEqual(image.pixelColor(400, 10).name(), '#ff0000')
        self.assertEqual(hauteurs[0], 800)
        # Une seule image en JPG
        p['reglages'].update(decoupe=0, format='jpg')
        r = json.loads(fenetre_qt.Fichiers().exporterPlanche(f'http://127.0.0.1:{self.port}', json.dumps(p), str(sortie)))
        self.assertEqual(r['fichiers'], ['Épisode-1.jpg'])
        self.assertEqual(QImage(str(sortie / 'Épisode-1.jpg')).height(), 3360)
        # Planche vide
        p['cases'] = []
        self.assertIn('vide', json.loads(fenetre_qt.Fichiers().exporterPlanche(f'http://127.0.0.1:{self.port}', json.dumps(p), str(sortie)))['erreur'])


if __name__ == '__main__':
    unittest.main()
