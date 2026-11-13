"""Tests du choix libre des modeles dans la fenetre des modeles : un fichier du dossier models pour chaque role,
avec ou sans profil (Prisme 2.1.3).

Lancement : py -3 -m unittest tests.test_choix_modeles -v
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

DOSSIER = tempfile.TemporaryDirectory(prefix='prisme_tests_choix_', ignore_cleanup_errors=True)
if 'serveur' not in sys.modules:
    os.environ['PRISME_RACINE'] = DOSSIER.name
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'app'))

import serveur  # noqa: E402


def tearDownModule():
    DOSSIER.cleanup()


class ChoixTest(unittest.TestCase):
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

    def test_fichier_ajoute_a_la_main_pour_chaque_role(self):
        for nom in ('perso-dessin.gguf', 'perso-texte.gguf', 'mmproj-perso.gguf', 'perso-vae.safetensors'):
            (self.modeles / nom).write_bytes(b'x')
        for role, nom in (('image', 'perso-dessin.gguf'), ('texte', 'perso-texte.gguf'), ('edition', 'mmproj-perso.gguf'),
                          ('vae', 'perso-vae.safetensors')):
            serveur.utiliser_fichier(nom, role)
        r = serveur.lire_reglages()
        self.assertEqual((r['modele_diffusion'], r['modele_texte'], r['modele_vision'], r['vae']),
                         ('perso-dessin.gguf', 'perso-texte.gguf', 'mmproj-perso.gguf', 'perso-vae.safetensors'))
        # La configuration est visible dans la fenetre, et personnalisee : aucun profil ne correspond
        etat = serveur.etat_modeles_conseilles()
        self.assertEqual(etat['configuration'], {'image': 'perso-dessin.gguf', 'texte': 'perso-texte.gguf',
                                                 'edition': 'mmproj-perso.gguf', 'vae': 'perso-vae.safetensors'})
        self.assertIsNone(etat['profil_actif'])
        roles = {m['nom']: m['roles'] for m in etat['autres']}
        self.assertEqual(roles['perso-dessin.gguf'], ['image'])
        self.assertEqual(roles['mmproj-perso.gguf'], ['edition'])

    def test_vision_retiree(self):
        (self.modeles / 'mmproj-perso.gguf').write_bytes(b'x')
        serveur.utiliser_fichier('mmproj-perso.gguf', 'edition')
        serveur.utiliser_fichier('', 'edition')
        self.assertEqual(serveur.lire_reglages()['modele_vision'], '')

    def test_fichier_du_catalogue_garde_ses_regles(self):
        modele = next(m for m in serveur.MODELES_CONSEILLES if m['role_id'] == 'image')
        (self.modeles / modele['fichier']).write_bytes(b'x')
        with mock.patch.object(serveur, 'utiliser_modele') as utiliser:
            serveur.utiliser_fichier(modele['fichier'], 'image')
        utiliser.assert_called_once_with(modele)
        serveur.utiliser_fichier(modele['fichier'], 'image')
        etat = serveur.etat_modeles_conseilles()
        self.assertTrue(next(m for m in etat['modeles'] if m['id'] == modele['id'])['utilise'])
        self.assertEqual(etat['configuration']['image'], modele['fichier'])

    def test_profil_complet_reconnu(self):
        profil = next(p for p in serveur.PROFILS if p['categorie'] == 'principal')
        for i in profil['modeles']:
            (self.modeles / serveur.MODELES_PAR_ID[i]['fichier']).write_bytes(b'x')
            serveur.utiliser_modele(serveur.MODELES_PAR_ID[i])
        self.assertEqual(serveur.etat_modeles_conseilles()['profil_actif'], profil['id'])

    def test_refuse_ce_qui_n_est_pas_un_modele_du_dossier(self):
        (self.modeles / 'loras' / 'style.safetensors').write_bytes(b'x')
        (self.modeles / 'notes.txt').write_bytes(b'x')
        (self.modeles / 'perso.gguf').write_bytes(b'x')
        secret = Path(self.dossier.name) / 'secret.gguf'
        secret.write_bytes(b'x')
        for nom, role in (('../secret.gguf', 'image'), (str(secret), 'image'), ('loras/style.safetensors', 'image'),
                          ('notes.txt', 'image'), ('absent.gguf', 'texte'), ('', 'image'), ('perso.gguf', 'inconnu')):
            with self.subTest(nom=nom, role=role):
                with self.assertRaises(ValueError):
                    serveur.utiliser_fichier(nom, role)
        self.assertFalse(self.reglages.exists() and serveur.lire_reglages()['modele_diffusion'] in ('../secret.gguf', 'perso.gguf'))


class RouteChoixTest(unittest.TestCase):
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
        self.choix = []

        def utiliser(nom, role):
            if nom == 'absent.gguf':
                raise ValueError('Modèle introuvable dans le dossier models.')
            self.choix.append((nom, role))

        for patch in (mock.patch.object(serveur, 'PORT', self.port), mock.patch.object(serveur, 'dernier_contact_mcp', 0.0),
                      mock.patch.object(serveur, 'utiliser_fichier', utiliser)):
            patch.start()
            self.addCleanup(patch.stop)

    def poster(self, corps, entetes=None):
        connexion = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        connexion.request('POST', '/api/utiliser-modele', json.dumps(corps).encode(),
                          {'Host': f'127.0.0.1:{self.port}', 'Content-Type': 'application/json', **(entetes or {})})
        reponse = connexion.getresponse()
        resultat = (reponse.status, json.loads(reponse.read() or b'{}'))
        connexion.close()
        return resultat

    def test_depuis_la_fenetre(self):
        self.assertEqual(self.poster({'nom': 'perso.gguf', 'role': 'image'}), (200, {}))
        self.assertEqual(self.choix, [('perso.gguf', 'image')])

    def test_fichier_absent(self):
        code, reponse = self.poster({'nom': 'absent.gguf', 'role': 'image'})
        self.assertEqual(code, 400)
        self.assertIn('introuvable', reponse['erreur'])

    def test_jamais_depuis_claude(self):
        self.assertEqual(self.poster({'nom': 'perso.gguf', 'role': 'image'}, {'X-Prisme-Client': 'mcp'})[0], 403)
        self.assertEqual(self.choix, [])


if __name__ == '__main__':
    unittest.main()
