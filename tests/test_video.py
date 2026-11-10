"""Tests de la creation de video (branche video, Prisme 2.0) : commande de sd-cli, progression, routes du serveur.

Le moteur est remplace par un faux processus : aucun modele n'est charge et rien n'est calcule.
Lancement : py -3 -m unittest tests.test_video -v
"""

import http.client
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

DOSSIER = tempfile.TemporaryDirectory(prefix='prisme_tests_video_', ignore_cleanup_errors=True)
if 'serveur' not in sys.modules:
    os.environ['PRISME_RACINE'] = DOSSIER.name
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'app'))

import serveur  # noqa: E402
import video  # noqa: E402


def tearDownModule():
    DOSSIER.cleanup()


# Lignes reelles de sd-cli (Wan 2.2 TI2V 5B, 1280 x 704, 49 images) ; \r separe les mises a jour d'une barre
JOURNAL = [
    '[I] generate_video 1280x704x49 --- video.cpp:1679\n',
    '  |==>                         |  1/20 -   8.67s/it - ETA 02:44\x1b[K\r',
    '  |=====>                      | 10/20 -   5.60s/it - ETA 00:56\x1b[K\r',
    '  |============================| 20/20 -   5.60s/it\x1b[K\n',
    '[I] sampling completed, taking 112.01s --- video.cpp:1776\n',
    '  |#######################      |  49/110 -   1.13GB/s\x1b[K\r',
    '  |=====>                      | 1/9 -  13.10s/it - ETA 01:44\x1b[K\r',
    '  |============================| 9/9 -  12.24s/it\x1b[K\n',
    '[I] decode_first_stage completed, taking 110.98s --- video.cpp:1290\n',
]
REGLAGES = {'video_modele': 'Wan2.2-TI2V-5B-Q8_0.gguf', 'video_texte': 'umt5-xxl-encoder-Q8_0.gguf',
            'video_vae': 'wan2.2_vae.safetensors'}


class CommandeTest(unittest.TestCase):
    def test_nombre_d_images_compatible_avec_le_vae(self):
        for duree in video.DUREES:
            with self.subTest(duree=duree):
                n = video.nombre_images(duree)
                self.assertEqual((n - 1) % 4, 0)
                self.assertEqual(n, 24 * duree + 1)

    def test_tailles_multiples_de_32(self):
        for qualite, formats in video.TAILLES.items():
            for format_, (largeur, hauteur) in formats.items():
                with self.subTest(qualite=qualite, format=format_):
                    self.assertEqual((largeur % 32, hauteur % 32), (0, 0))

    def test_validation(self):
        v, erreur = video.valider({'prompt': ' un renard ', 'qualite': '704p', 'format': 'portrait', 'duree': 3, 'seed': '7'})
        self.assertIsNone(erreur)
        self.assertEqual((v['prompt'], v['largeur'], v['hauteur'], v['images'], v['seed']), ('un renard', 704, 1280, 73, 7))
        self.assertIsNone(video.valider({'prompt': 'x'})[0]['seed'])
        for mauvais in ({'prompt': ''}, {'prompt': 'x', 'duree': 9}, {'prompt': 'x', 'qualite': '4k'},
                        {'prompt': 'x', 'format': 'rond'}, {'prompt': 'x', 'duree': 'deux'}, {'prompt': 'x', 'seed': 'a'}):
            with self.subTest(demande=mauvais):
                self.assertIsNone(video.valider(mauvais)[0])
                self.assertTrue(video.valider(mauvais)[1])

    def test_arguments(self):
        v, _ = video.valider({'prompt': 'un renard', 'qualite': '704p', 'duree': 2})
        modeles = Path('models')
        args = video.arguments(REGLAGES, modeles, v, 42, None, Path('sortie.webm'))
        self.assertEqual(args[:2], ['-M', 'vid_gen'])
        valeur = lambda option: args[args.index(option) + 1]
        self.assertEqual(valeur('--diffusion-model'), str(modeles / REGLAGES['video_modele']))
        self.assertEqual(valeur('--t5xxl'), str(modeles / REGLAGES['video_texte']))
        self.assertEqual(valeur('--vae'), str(modeles / REGLAGES['video_vae']))
        self.assertEqual((valeur('-W'), valeur('-H'), valeur('--video-frames'), valeur('--fps')), ('1280', '704', '49', '24'))
        # Decodage par morceaux d'un quart de l'image : sans eux, le VAE manque de memoire et repart plus petit
        self.assertIn('--vae-tiling', args)
        self.assertEqual(valeur('--vae-tile-size'), '640x352')
        self.assertEqual(args[-2:], ['-o', 'sortie.webm'])
        self.assertNotIn('-i', args)
        avec_image = video.arguments(REGLAGES, modeles, v, 42, Path('depart.png'), Path('sortie.webm'), fils=6)
        self.assertEqual(avec_image[avec_image.index('-i') + 1], 'depart.png')
        self.assertEqual(avec_image[avec_image.index('--threads') + 1], '6')

    def test_fichiers_manquants(self):
        with tempfile.TemporaryDirectory() as d:
            modeles = Path(d)
            self.assertEqual(video.fichiers_manquants({}, modeles), list(video.CLES))
            for nom in REGLAGES.values():
                (modeles / nom).write_bytes(b'x')
            self.assertEqual(video.fichiers_manquants(REGLAGES, modeles), [])
            self.assertEqual(video.fichiers_manquants({**REGLAGES, 'video_vae': ''}, modeles), ['video_vae'])

    def test_noms_de_fichier(self):
        self.assertTrue(video.NOM_VIDEO.match('video_20261110_120000.webm'))
        self.assertTrue(video.NOM_VIDEO.match('video_20261110_120000_2.webm'))
        for nom in ('image_1.png', 'video_x.webm.png', '../video_1.webm', 'video_1.webm/..', 'video_1.avi'):
            self.assertFalse(video.NOM_VIDEO.match(nom), nom)
        with tempfile.TemporaryDirectory() as d:
            premier = video.nouveau_chemin(Path(d) / 'images')
            premier.write_bytes(b'')
            second = video.nouveau_chemin(Path(d) / 'images')
            self.assertNotEqual(premier, second)
            self.assertTrue(video.NOM_VIDEO.match(second.name))


class ProgressionTest(unittest.TestCase):
    def test_creation_puis_decodage(self):
        rapports = []
        suivi = video.Progression(lambda **champs: rapports.append(champs))
        # Les blocs du tube coupent les lignes n'importe ou
        texte = ''.join(JOURNAL)
        for i in range(0, len(texte), 7):
            suivi.lire(texte[i:i + 7])
        dessin = [r['etape'] for r in rapports if r['phase'] == 'dessin']
        self.assertEqual(dessin, [1, 10, 20])
        decodage = [(r['etape'], r['total_decodage']) for r in rapports if r['phase'] == 'decodage']
        # Le chargement du VAE (49/110 en Go/s) n'est pas une etape
        self.assertEqual(decodage, [(0, 0), (1, 9), (9, 9)])

    def test_erreurs_retenues(self):
        suivi = video.Progression(lambda **champs: None)
        suivi.lire('[I] ok\n[E] vae decode compute failed\nCUDA error: out of memory\n')
        self.assertEqual(len(suivi.erreurs()), 2)


class FauxMoteur:
    """Se comporte comme sd-cli : ecrit son journal dans le tube, puis la video demandee."""

    def __init__(self, commande, code=0):
        self.commande, self.code = commande, code
        self.sortie = Path(commande[commande.index('-o') + 1])
        self.blocs = [ligne.encode() for ligne in JOURNAL]
        self.stdout = self
        self.pid = 0

    def read1(self, _taille):
        if self.blocs:
            return self.blocs.pop(0)
        if self.code == 0:
            self.sortie.write_bytes(b'\x1a\x45\xdf\xa3 faux webm')
        return b''

    def wait(self):
        return self.code

    def poll(self):
        return self.code


class RoutesVideoTest(unittest.TestCase):
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
        racine = Path(self.dossier.name)
        self.images, self.modeles = racine / 'images', racine / 'models'
        self.modeles.mkdir()
        self.reglages = dict(serveur.REGLAGES_DEFAUT, **REGLAGES)
        self.moteurs = []
        for patch in (mock.patch.object(serveur, 'IMAGES', self.images), mock.patch.object(serveur, 'MODELES', self.modeles),
                      mock.patch.object(serveur, 'PORT', self.port),
                      mock.patch.object(serveur, 'lire_reglages', lambda: dict(self.reglages)),
                      mock.patch.object(serveur, 'lancer_moteur', self.lancer)):
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(self.dossier.cleanup)
        serveur.etat.clear()
        serveur.etat['occupe'] = False
        self.code_moteur = 0

    def lancer(self, commande, **_options):
        moteur = FauxMoteur(commande, self.code_moteur)
        self.moteurs.append(moteur)
        return moteur

    def installer_modeles(self):
        for nom in REGLAGES.values():
            (self.modeles / nom).write_bytes(b'x')

    def requete(self, methode, chemin, corps=None, entetes=None):
        connexion = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        donnees = json.dumps(corps).encode() if corps is not None else None
        connexion.request(methode, chemin, donnees, {'Host': f'127.0.0.1:{self.port}', 'Content-Type': 'application/json',
                                                      **(entetes or {})})
        reponse = connexion.getresponse()
        resultat = (reponse.status, reponse.getheader('Content-Type'), reponse.read())
        connexion.close()
        return resultat

    def attendre_fin(self):
        limite = time.time() + 10
        while serveur.etat.get('occupe') and time.time() < limite:
            time.sleep(0.02)
        self.assertFalse(serveur.etat.get('occupe'))

    def test_modeles_manquants(self):
        code, _, corps = self.requete('POST', '/api/video', {'prompt': 'un renard'})
        self.assertEqual(code, 409)
        self.assertEqual(json.loads(corps)['manquants'], list(video.CLES))
        self.assertEqual(self.moteurs, [])

    def test_demande_invalide(self):
        self.installer_modeles()
        self.assertEqual(self.requete('POST', '/api/video', {'prompt': 'un renard', 'duree': 30})[0], 400)
        self.assertEqual(self.moteurs, [])

    def test_pas_encore_pour_claude(self):
        self.installer_modeles()
        code, _, _ = self.requete('POST', '/api/video', {'prompt': 'un renard'}, {'X-Prisme-Client': 'mcp'})
        self.assertEqual(code, 403)
        self.assertEqual(self.moteurs, [])

    def test_une_creation_a_la_fois(self):
        self.installer_modeles()
        serveur.etat['occupe'] = True
        self.assertEqual(self.requete('POST', '/api/video', {'prompt': 'un renard'})[0], 409)

    def test_video_creee_listee_et_servie(self):
        self.installer_modeles()
        code, _, corps = self.requete('POST', '/api/video', {'prompt': 'un renard', 'qualite': '704p', 'duree': 2, 'seed': 5})
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(corps)['seed'], 5)
        self.attendre_fin()
        self.assertEqual(serveur.etat['phase'], 'termine', serveur.etat.get('erreur'))
        commande = self.moteurs[0].commande
        self.assertEqual(commande[0], str(serveur.SD_CLI))
        self.assertIn('vid_gen', commande)
        nom = serveur.etat['resultats'][0]
        self.assertTrue(video.NOM_VIDEO.match(nom))
        # La progression est passee par l'etat de Prisme, comme pour les images
        self.assertEqual((serveur.etat['genre'], serveur.etat['etape'], serveur.etat['total_decodage']), ('video', 9, 9))
        details = json.loads((self.images / nom).with_suffix('.json').read_text(encoding='utf-8'))
        self.assertEqual((details['prompt'], details['seed'], details['images'], details['largeur']), ('un renard', 5, 49, 1280))
        code, _, corps = self.requete('GET', '/api/videos')
        liste = json.loads(corps)
        self.assertEqual([v['nom'] for v in liste], [nom])
        self.assertEqual(liste[0]['prompt'], 'un renard')
        code, type_contenu, corps = self.requete('GET', f'/images/{nom}')
        self.assertEqual((code, type_contenu), (200, 'video/webm'))
        self.assertTrue(corps.startswith(b'\x1a\x45\xdf\xa3'))
        # Les images de Prisme ne sont jamais servies a Claude, les videos non plus
        self.assertEqual(self.requete('GET', f'/images/{nom}', entetes={'X-Prisme-Client': 'mcp'})[0], 403)

    def test_echec_du_moteur(self):
        self.installer_modeles()
        self.code_moteur = 1
        self.assertEqual(self.requete('POST', '/api/video', {'prompt': 'un renard'})[0], 200)
        self.attendre_fin()
        self.assertEqual(serveur.etat['phase'], 'erreur')
        self.assertTrue(serveur.etat['erreur'])
        self.assertEqual(list(self.images.glob('*.webm')), [])

    def test_depuis_une_image_de_la_galerie(self):
        self.installer_modeles()
        self.images.mkdir()
        (self.images / 'image_1.png').write_bytes(b'\x89PNG')
        self.requete('POST', '/api/video', {'prompt': 'un renard', 'source_nom': 'image_1.png'})
        self.attendre_fin()
        commande = self.moteurs[0].commande
        self.assertEqual(commande[commande.index('-i') + 1], str(self.images / 'image_1.png'))
        # Un nom hors de la galerie est ignore
        self.requete('POST', '/api/video', {'prompt': 'un renard', 'source_nom': '../secret.png'})
        self.attendre_fin()
        self.assertNotIn('-i', self.moteurs[1].commande)


if __name__ == '__main__':
    unittest.main()
