"""Tests de la suppression d'un modele depuis la fenetre des modeles (Prisme 2.0).

Lancement : py -3 -m unittest tests.test_supprimer_modele -v
"""

import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

DOSSIER = tempfile.TemporaryDirectory(prefix='prisme_tests_supprimer_', ignore_cleanup_errors=True)
if 'serveur' not in sys.modules:
    os.environ['PRISME_RACINE'] = DOSSIER.name
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'app'))

import serveur  # noqa: E402


def tearDownModule():
    DOSSIER.cleanup()


class SuppressionTest(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        racine = Path(self.dossier.name)
        self.modeles, self.donnees = racine / 'models', racine / 'app'
        (self.modeles / 'loras').mkdir(parents=True)
        self.donnees.mkdir()
        self.reglages = self.donnees / 'reglages.json'
        for patch in (mock.patch.object(serveur, 'MODELES', self.modeles), mock.patch.object(serveur, 'LORAS', self.modeles / 'loras'),
                      mock.patch.object(serveur, 'DONNEES', self.donnees), mock.patch.object(serveur, 'FICHIER_REGLAGES', self.reglages)):
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(self.dossier.cleanup)

    def test_supprime_et_retire_des_reglages(self):
        (self.modeles / 'dessin.gguf').write_bytes(b'x' * 1000)
        (self.modeles / 'dessin.gguf.partiel').write_bytes(b'x' * 10)
        (self.modeles / 'texte.gguf').write_bytes(b'x')
        self.reglages.write_text(json.dumps({'modele_diffusion': 'dessin.gguf', 'modele_texte': 'texte.gguf',
                                             'amelioration_modele_local': 'dessin.gguf'}), encoding='utf-8')
        self.assertEqual(serveur.supprimer_modele('dessin.gguf'), 1010)
        self.assertFalse((self.modeles / 'dessin.gguf').exists() or (self.modeles / 'dessin.gguf.partiel').exists())
        r = serveur.lire_reglages()
        # Les reglages qui choisissaient ce fichier sont vides ; les autres ne bougent pas
        self.assertEqual((r['modele_diffusion'], r['amelioration_modele_local'], r['modele_texte']), ('', '', 'texte.gguf'))

    def test_refuse_ce_qui_n_est_pas_un_modele_du_dossier(self):
        (self.modeles / 'loras' / 'style.safetensors').write_bytes(b'x')
        (self.modeles / 'notes.txt').write_bytes(b'x')
        secret = Path(self.dossier.name) / 'secret.gguf'
        secret.write_bytes(b'x')
        for nom in ('../secret.gguf', str(secret), 'loras/style.safetensors', 'notes.txt', 'absent.gguf', ''):
            with self.subTest(nom=nom):
                with self.assertRaises(ValueError):
                    serveur.supprimer_modele(nom)
        self.assertTrue(secret.exists() and (self.modeles / 'loras' / 'style.safetensors').exists())

    def test_refuse_pendant_son_telechargement(self):
        modele = serveur.MODELES_CONSEILLES[0]
        (self.modeles / modele['fichier']).write_bytes(b'x')
        with mock.patch.dict(serveur.telechargements_modeles, {modele['id']: {'phase': 'telechargement'}}):
            with self.assertRaises(RuntimeError):
                serveur.supprimer_modele(modele['fichier'])
        self.assertTrue((self.modeles / modele['fichier']).exists())

    def test_autres_fichiers_listes(self):
        (self.modeles / 'perso.safetensors').write_bytes(b'x' * 5)
        catalogue = serveur.MODELES_CONSEILLES[0]['fichier']
        (self.modeles / catalogue).write_bytes(b'x')
        autres = serveur.etat_modeles_conseilles()['autres']
        self.assertEqual(autres, [{'nom': 'perso.safetensors', 'taille': 5}])


class RouteSuppressionTest(unittest.TestCase):
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
        self.supprimes = []
        for patch in (mock.patch.object(serveur, 'PORT', self.port),
                      mock.patch.object(serveur, 'supprimer_modele', lambda nom: self.supprimes.append(nom) or 42)):
            patch.start()
            self.addCleanup(patch.stop)
        serveur.etat.clear()
        serveur.etat['occupe'] = False

    def poster(self, corps, entetes=None):
        connexion = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        connexion.request('POST', '/api/supprimer-modele', json.dumps(corps).encode(),
                          {'Host': f'127.0.0.1:{self.port}', 'Content-Type': 'application/json', **(entetes or {})})
        reponse = connexion.getresponse()
        resultat = (reponse.status, json.loads(reponse.read() or b'{}'))
        connexion.close()
        return resultat

    def test_depuis_la_fenetre(self):
        self.assertEqual(self.poster({'nom': 'dessin.gguf'}), (200, {'libere': 42}))
        self.assertEqual(self.supprimes, ['dessin.gguf'])

    def test_jamais_depuis_claude(self):
        self.assertEqual(self.poster({'nom': 'dessin.gguf'}, {'X-Prisme-Client': 'mcp'})[0], 403)
        self.assertEqual(self.supprimes, [])

    def test_pas_pendant_un_calcul(self):
        serveur.etat['occupe'] = True
        self.assertEqual(self.poster({'nom': 'dessin.gguf'})[0], 409)
        self.assertEqual(self.supprimes, [])


if __name__ == '__main__':
    unittest.main()
