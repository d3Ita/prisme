"""Tests de l'agrandissement d'une image (Real-ESRGAN x4, Prisme 2.0). Le moteur est remplace par un faux processus.

Lancement : py -3 -m unittest tests.test_agrandir -v
"""

import http.client
import json
import os
import struct
import sys
import tempfile
import threading
import time
import unittest
import zlib
from pathlib import Path
from unittest import mock

DOSSIER = tempfile.TemporaryDirectory(prefix='prisme_tests_agrandir_', ignore_cleanup_errors=True)
if 'serveur' not in sys.modules:
    os.environ['PRISME_RACINE'] = DOSSIER.name
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'app'))

import agrandir  # noqa: E402
import serveur  # noqa: E402


def tearDownModule():
    DOSSIER.cleanup()


def png(largeur, hauteur, description=None):
    """Petit PNG valide, avec la description ecrite par sd-cli si demandee."""
    morceau = lambda genre, contenu: (struct.pack('>I', len(contenu)) + genre + contenu
                                      + struct.pack('>I', zlib.crc32(genre + contenu) & 0xffffffff))
    brut = b''.join(b'\x00' + b'\x80\x80\x80' * largeur for _ in range(hauteur))
    texte = morceau(b'tEXt', b'parameters\x00' + description.encode()) if description else b''
    return (agrandir.SIGNATURE_PNG + morceau(b'IHDR', struct.pack('>IIBBBBB', largeur, hauteur, 8, 2, 0, 0, 0)) + texte
            + morceau(b'IDAT', zlib.compress(brut)) + morceau(b'IEND', b''))


class PngTest(unittest.TestCase):
    def test_taille_et_description_recopiee(self):
        with tempfile.TemporaryDirectory() as d:
            source, sortie = Path(d) / 'source.png', Path(d) / 'sortie.png'
            source.write_bytes(png(8, 4, 'un renard roux\nSteps: 8, Seed: 42'))
            sortie.write_bytes(png(32, 16, '{"kind":"image","upscale":{}}'))
            self.assertEqual(agrandir.taille_png(source), (8, 4))
            agrandir.copier_description(source, sortie)
            infos = serveur.lire_infos(sortie)
            # La galerie voit la description et la variante d'origine, et la nouvelle taille
            self.assertEqual((infos['prompt'], infos['seed'], infos['largeur'], infos['hauteur']), ('un renard roux', 42, 32, 16))
            textes = [c for g, c in agrandir.morceaux_png(sortie.read_bytes()) if g == b'tEXt']
            self.assertEqual(len(textes), 1)

    def test_arguments(self):
        args = agrandir.arguments(Path('m.safetensors'), Path('a.png'), Path('b.png'))
        self.assertEqual(args[:2], ['-M', 'upscale'])
        self.assertEqual(args[args.index('--upscale-model') + 1], 'm.safetensors')
        self.assertEqual(args[-2:], ['-o', 'b.png'])


class FauxMoteur:
    JOURNAL = ['[I] upscaling from (8 x 4) to (32 x 16)\n', '  |=>   |  1/3 -   8.00it/s\r', '  |===| 3/3 -   8.00it/s\n']

    def __init__(self, commande, code=0):
        self.commande, self.code = commande, code
        self.sortie = Path(commande[commande.index('-o') + 1])
        self.blocs = [l.encode() for l in self.JOURNAL]
        self.stdout = self
        self.pid = 0

    def read1(self, _taille):
        if self.blocs:
            return self.blocs.pop(0)
        if self.code == 0:
            self.sortie.write_bytes(png(32, 16, '{"kind":"image"}'))
        return b''

    def wait(self):
        return self.code


class RouteAgrandirTest(unittest.TestCase):
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
        self.images.mkdir(), self.modeles.mkdir()
        (self.images / 'image_1.png').write_bytes(png(8, 4, 'un renard\nSteps: 8, Seed: 7'))
        self.moteurs = []
        # Une requete marquee MCP note une activite de Claude : on la remet comme avant pour les autres tests
        for patch in (mock.patch.object(serveur, 'IMAGES', self.images), mock.patch.object(serveur, 'MODELES', self.modeles),
                      mock.patch.object(serveur, 'PORT', self.port), mock.patch.object(serveur, 'dernier_contact_mcp', 0.0),
                      mock.patch.object(serveur, 'lire_reglages', lambda: dict(serveur.REGLAGES_DEFAUT)),
                      mock.patch.object(serveur, 'lancer_moteur', lambda c, **o: self.moteurs.append(FauxMoteur(c)) or self.moteurs[-1])):
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(self.dossier.cleanup)
        serveur.etat.clear()
        serveur.etat['occupe'] = False

    def requete(self, chemin, corps=None, entetes=None):
        connexion = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        connexion.request('POST' if corps is not None else 'GET', chemin, json.dumps(corps).encode() if corps is not None else None,
                          {'Host': f'127.0.0.1:{self.port}', 'Content-Type': 'application/json', **(entetes or {})})
        reponse = connexion.getresponse()
        resultat = (reponse.status, json.loads(reponse.read() or b'{}'))
        connexion.close()
        return resultat

    def test_modele_a_telecharger(self):
        self.assertEqual(self.requete('/api/etat')[1]['agrandissement']['pret'], False)
        code, corps = self.requete('/api/agrandir', {'nom': 'image_1.png'})
        self.assertEqual((code, corps['telecharger']), (409, 'realesrgan-x4plus'))
        self.assertEqual(self.moteurs, [])

    def test_agrandit_dans_une_nouvelle_image(self):
        (self.modeles / 'RealESRGAN_x4plus.safetensors').write_bytes(b'x')
        self.assertTrue(self.requete('/api/etat')[1]['agrandissement']['pret'])
        self.assertEqual(self.requete('/api/agrandir', {'nom': 'image_1.png'}), (200, {'largeur': 32, 'hauteur': 16}))
        limite = time.time() + 10
        while serveur.etat.get('occupe') and time.time() < limite:
            time.sleep(0.02)
        self.assertEqual(serveur.etat['phase'], 'termine', serveur.etat.get('erreur'))
        self.assertEqual((serveur.etat['genre'], serveur.etat['etape'], serveur.etat['total']), ('agrandissement', 3, 3))
        nom = serveur.etat['resultats'][0]
        self.assertNotEqual(nom, 'image_1.png')
        infos = serveur.lire_infos(self.images / nom)
        self.assertEqual((infos['prompt'], infos['seed'], infos['largeur']), ('un renard', 7, 32))
        # L'image d'origine est intacte
        self.assertEqual(agrandir.taille_png(self.images / 'image_1.png'), (8, 4))

    def test_refus(self):
        (self.modeles / 'RealESRGAN_x4plus.safetensors').write_bytes(b'x')
        self.assertEqual(self.requete('/api/agrandir', {'nom': '../secret.png'})[0], 404)
        self.assertEqual(self.requete('/api/agrandir', {'nom': 'image_1.png'}, {'X-Prisme-Client': 'mcp'})[0], 403)
        (self.images / 'image_2.png').write_bytes(png(5000, 1))
        self.assertEqual(self.requete('/api/agrandir', {'nom': 'image_2.png'})[0], 400)
        serveur.etat['occupe'] = True
        self.assertEqual(self.requete('/api/agrandir', {'nom': 'image_1.png'})[0], 409)
        self.assertEqual(self.moteurs, [])


if __name__ == '__main__':
    unittest.main()
