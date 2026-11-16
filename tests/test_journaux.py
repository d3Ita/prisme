"""Tests des journaux de Prisme : prisme.log, sortie complete du moteur quand une creation echoue, message d'erreur precis.

Lancement : py -3 -m unittest tests.test_journaux -v
"""

import io
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

DOSSIER = tempfile.TemporaryDirectory(prefix='prisme_tests_journaux_', ignore_cleanup_errors=True)
if 'serveur' not in sys.modules:
    os.environ['PRISME_RACINE'] = DOSSIER.name
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'app'))

import serveur  # noqa: E402


def tearDownModule():
    DOSSIER.cleanup()


class OutilsTest(unittest.TestCase):
    def test_code_lisible(self):
        self.assertEqual(serveur.code_lisible(0xC0000409), 'code 3221226505 (0xC0000409 : arrêt interne du moteur : une vérification a échoué)')
        self.assertEqual(serveur.code_lisible(1), 'code 1 (arrêté de force, ou erreur générale)')
        self.assertEqual(serveur.code_lisible(-11), 'code -11 (0xFFFFFFF5 : accès mémoire invalide (plantage))')
        self.assertEqual(serveur.code_lisible(42), 'code 42')
        self.assertEqual(serveur.code_lisible(None), 'code inconnu')

    def test_description_jamais_dans_le_journal(self):
        commande = ['sd-cli', '--diffusion-model', 'd.gguf', '-p', 'mon secret<lora:style:0.8>', '--steps', '8']
        texte = serveur.commande_pour_journal(commande, 'mon secret<lora:style:0.8>')
        self.assertNotIn('secret', texte)
        self.assertIn('<description : 26 caracteres><lora:style:0.8>', texte)
        self.assertEqual(serveur.sans_description('prompt: mon secret ici', 'mon secret'), 'prompt: <description : 10 caracteres> ici')

    def test_message_d_echec(self):
        # Lignes d'erreur du moteur : gardees
        self.assertTrue(serveur.message_echec_moteur(['[I] chargement', '[E] LLM prompt encoding failed'], 1, '')
                        .startswith('[E] LLM prompt encoding failed\nLe moteur sd-cli s\'est arrêté : code 1 ('))
        # Une verification interne qui echoue (GGML_ASSERT) : reconnue, avec le code explique et le journal a envoyer
        message = serveur.message_echec_moteur(['[I] sampling', 'D:/ggml.c:1234: GGML_ASSERT(ne0 > 0) failed'], 0xC0000409,
                                               'moteur-creation-1.log')
        self.assertIn('GGML_ASSERT', message)
        self.assertIn('0xC0000409', message)
        self.assertTrue(message.endswith('Détails : journaux/moteur-creation-1.log'))
        # Rien de parlant : les dernieres lignes utiles, sans les barres d'avancement
        message = serveur.message_echec_moteur(['[I] loading tensors', '  |=====>   | 3/8 - 1.2s/it', '[I] decoding'], 3, '')
        self.assertTrue(message.startswith('[I] loading tensors\n[I] decoding'))
        self.assertNotIn('3/8', message)


class SortieMoteurTest(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.dossier.cleanup)
        patch = mock.patch.object(serveur, 'JOURNAUX', Path(self.dossier.name) / 'journaux')
        patch.start()
        self.addCleanup(patch.stop)

    def test_sortie_gardee_sans_description(self):
        nom = serveur.garder_sortie_moteur('creation', ['sd-cli', '-p', 'mon secret'], 'mon secret', 0xC0000409,
                                           ['[I] prompt: mon secret', 'GGML_ASSERT failed'])
        contenu = (serveur.JOURNAUX / nom).read_text(encoding='utf-8')
        self.assertNotIn('secret', contenu)
        self.assertIn('0xC0000409', contenu)
        self.assertIn('GGML_ASSERT failed', contenu)

    def test_vingt_gardes_au_plus(self):
        serveur.JOURNAUX.mkdir(parents=True)
        for i in range(25):
            vieux = serveur.JOURNAUX / f'moteur-creation-ancien{i:02d}.log'
            vieux.write_text('x')
            os.utime(vieux, (1000 + i, 1000 + i))
        serveur.garder_sortie_moteur('creation', ['sd-cli'], '', 1, [])
        restants = sorted(p.name for p in serveur.JOURNAUX.glob('moteur-*.log'))
        self.assertEqual(len(restants), serveur.JOURNAUX_MOTEUR_GARDES)
        self.assertNotIn('moteur-creation-ancien00.log', restants)

    def test_journal_ecrit(self):
        ancien = (serveur.journal.handlers[:], serveur.journal.level)
        try:
            serveur.ouvrir_journal()
            serveur.journal.info('essai %s', 42)
            for h in serveur.journal.handlers:
                h.flush()
            self.assertIn('INFO essai 42', (serveur.JOURNAUX / 'prisme.log').read_text(encoding='utf-8'))
        finally:
            for h in serveur.journal.handlers[:]:
                if h not in ancien[0]:
                    h.close()
                    serveur.journal.removeHandler(h)
            serveur.journal.setLevel(ancien[1])


class CreationEchoueeTest(unittest.TestCase):
    """generer() avec un faux moteur qui s'arrete sur une verification interne : message precis et sortie gardee."""

    def test_moteur_plante(self):
        dossier = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(dossier.cleanup)
        racine = Path(dossier.name)

        class Moteur:
            pid = 1
            stdout = io.BytesIO(b'[I] loading\r\n  |===>  | 1/8 - 2s/it\r\nD:/ggml.c:12: GGML_ASSERT(x) failed\r\n')

        r = dict(serveur.REGLAGES_DEFAUT, modele_diffusion='d.gguf', modele_texte='t.gguf', vae='v.safetensors')
        self.addCleanup(setattr, serveur, 'annule', serveur.annule)
        serveur.annule = False
        with mock.patch.object(serveur, 'JOURNAUX', racine / 'journaux'), mock.patch.object(serveur, 'IMAGES', racine / 'images'), \
                mock.patch.object(serveur, 'lancer_moteur', return_value=Moteur()), \
                mock.patch.object(serveur, 'attendre_moteur', return_value=(0xC0000409, None)), \
                mock.patch.object(serveur, 'modeles_manquants', return_value=[]), \
                self.assertLogs('prisme', level='INFO') as journaux:
            serveur.etat.update(occupe=True, resultats=[], erreur=None)
            serveur.generer(dict(prompt='mon secret', largeur=1024, hauteur=1024, nombre=1, seed=1, reglages=r, source_nom=None,
                                 source_data=None, claude=False, liste_reglages=None, comparaison=None, projet=None, personnages=[]))
        erreur = serveur.etat['erreur']
        self.assertIn('GGML_ASSERT(x) failed', erreur)
        self.assertIn('0xC0000409', erreur)
        self.assertIn('Détails : journaux/moteur-creation-', erreur)
        self.assertEqual(serveur.etat['phase'], 'erreur')
        fichiers = list((racine / 'journaux').glob('moteur-creation-*.log'))
        self.assertEqual(len(fichiers), 1)
        self.assertIn('GGML_ASSERT', fichiers[0].read_text(encoding='utf-8'))
        # Le journal note la creation, la commande (sans la description) et l'echec
        texte = '\n'.join(journaux.output)
        self.assertIn('creation 1/1 : 1024x1024', texte)
        self.assertIn('creation echouee', texte)
        self.assertNotIn('secret', texte)


class LoraSurModeleKTest(unittest.TestCase):
    """Fusion d'un LoRA au debut : impossible sur un modele compresse en K ou IQ (le moteur s'arrete)."""

    def setUp(self):
        dossier = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(dossier.cleanup)
        self.racine = Path(dossier.name)
        (self.racine / 'loras').mkdir()
        (self.racine / 'loras' / 'style.safetensors').write_bytes(b'')
        for patch in (mock.patch.object(serveur, 'LORAS', self.racine / 'loras'), mock.patch.object(serveur, 'JOURNAUX', self.racine / 'journaux'),
                      mock.patch.object(serveur, 'IMAGES', self.racine / 'images')):
            patch.start()
            self.addCleanup(patch.stop)
        self.r = dict(serveur.REGLAGES_DEFAUT, modele_diffusion='Qwen-Image-2.1-Turbo-AD-Q4_K.gguf', modele_texte='t.gguf', vae='v.safetensors',
                      loras=[{'nom': 'style.safetensors', 'force': 1.0, 'actif': True}])

    def test_mode_choisi_selon_le_modele(self):
        for nom, attendu in (('Qwen-Image-2.1-Turbo-AD-Q4_K.gguf', 'at_runtime'), ('x-Q5_K_M.gguf', 'at_runtime'), ('m-IQ4_XS.gguf', 'at_runtime'),
                             ('flux-2-klein-4b-Q8_0.gguf', 'immediately'), ('a-Q4_0.gguf', 'immediately'), ('b-BF16.safetensors', 'immediately')):
            with self.subTest(nom=nom):
                self.assertEqual(serveur.mode_lora({**self.r, 'modele_diffusion': nom}), attendu)
                a = serveur.options_loras({**self.r, 'modele_diffusion': nom})
                self.assertEqual(a[a.index('--lora-apply-mode') + 1], attendu)
        # Un choix explicite « a chaque etape » ou « choix du moteur » est garde
        self.assertEqual(serveur.mode_lora({**self.r, 'modele_diffusion': 'a-Q8_0.gguf', 'lora_application': 'at_runtime'}), 'at_runtime')
        self.assertEqual(serveur.mode_lora({**self.r, 'lora_application': 'auto'}), 'auto')

    def test_nouvel_essai_si_la_fusion_echoue(self):
        """Le moteur s'arrete en fusionnant le LoRA : Prisme recommence avec le LoRA a chaque etape, et l'image arrive."""
        commandes = []

        class Moteur:
            def __init__(self, sortie):
                self.pid = 1
                self.stdout = io.BytesIO(sortie)

        def lancer(commande, **_):
            commandes.append(commande)
            if len(commandes) == 1:
                return Moteur(b'[I] loading\nggml-backend.cpp:1099: pre-allocated tensor (x) in a buffer (CUDA0) that cannot run the operation (CPY)\n')
            Path(commande[commande.index('-o') + 1]).write_bytes(b'\x89PNG\r\n\x1a\n')
            return Moteur(b'[I] generate_image completed\n')

        codes = iter([(0xC0000409, None), (0, None)])
        r = {**self.r, 'modele_diffusion': 'modele-Q8_0.gguf'}
        self.addCleanup(setattr, serveur, 'annule', serveur.annule)
        serveur.annule = False
        with mock.patch.object(serveur, 'lancer_moteur', lancer), mock.patch.object(serveur, 'attendre_moteur', lambda p: next(codes)), \
                mock.patch.object(serveur, 'modeles_manquants', return_value=[]), mock.patch.object(serveur, 'noter_dans_png'), \
                self.assertLogs('prisme', level='INFO') as journaux:
            serveur.etat.update(occupe=True, resultats=[], erreur=None)
            serveur.generer(dict(prompt='un phare', largeur=768, hauteur=1376, nombre=1, seed=1, reglages=r, source_nom=None,
                                 source_data=None, claude=False, liste_reglages=None, comparaison=None, projet=None, personnages=[]))
        self.assertEqual(len(commandes), 2)
        self.assertEqual(commandes[0][commandes[0].index('--lora-apply-mode') + 1], 'immediately')
        self.assertEqual(commandes[1][commandes[1].index('--lora-apply-mode') + 1], 'at_runtime')
        self.assertIsNone(serveur.etat['erreur'])
        self.assertEqual(len(serveur.etat['resultats']), 1)
        self.assertIn('nouvel essai, LoRA applique a chaque etape', '\n'.join(journaux.output))

    def test_pas_de_nouvel_essai_pour_une_autre_panne(self):
        commandes = []

        def lancer(commande, **_):
            commandes.append(commande)
            return type('Moteur', (), {'pid': 1, 'stdout': io.BytesIO(b'[E] model metadata validation failed\n')})()

        r = {**self.r, 'modele_diffusion': 'modele-Q8_0.gguf'}
        self.addCleanup(setattr, serveur, 'annule', serveur.annule)
        serveur.annule = False
        with mock.patch.object(serveur, 'lancer_moteur', lancer), mock.patch.object(serveur, 'attendre_moteur', return_value=(1, None)), \
                mock.patch.object(serveur, 'modeles_manquants', return_value=[]):
            serveur.etat.update(occupe=True, resultats=[], erreur=None)
            serveur.generer(dict(prompt='un phare', largeur=768, hauteur=1376, nombre=1, seed=1, reglages=r, source_nom=None,
                                 source_data=None, claude=False, liste_reglages=None, comparaison=None, projet=None, personnages=[]))
        self.assertEqual(len(commandes), 1)
        self.assertIn('model metadata validation failed', serveur.etat['erreur'])


if __name__ == '__main__':
    unittest.main()
