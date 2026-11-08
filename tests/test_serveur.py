"""Tests du serveur de Prisme : validation des reglages, lecture des images et protections d'acces.

Lancement : py -3 -m unittest discover -s tests -v
Le serveur travaille sur un dossier temporaire : tes reglages, images et code d'acces ne sont pas touches.
"""

import http.client
import json
import os
import struct
import sys
import tempfile
import threading
import unittest
import zlib
from pathlib import Path

# Sous Windows, un fichier encore ouvert peut empecher le nettoyage : ce n'est pas un echec des tests
DOSSIER_TEST = tempfile.TemporaryDirectory(prefix='prisme_tests_', ignore_cleanup_errors=True)
os.environ['PRISME_RACINE'] = DOSSIER_TEST.name
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'app'))

import serveur  # noqa: E402  (doit etre importe apres PRISME_RACINE)


def tearDownModule():
    DOSSIER_TEST.cleanup()


BASE = {'modele_diffusion': 'dessin.gguf', 'modele_texte': 'texte.gguf', 'vae': 'vae.safetensors'}


def valider(**changements):
    return serveur.valider_reglages({**BASE, **changements})


class ReglagesTest(unittest.TestCase):
    def test_reglages_valides_acceptes(self):
        r, erreur = valider(etapes=8, sigmas='1,0.9,0.8,0.7,0.6,0.5,0.4,0.3,0',
                            loras=[{'nom': 'style.safetensors', 'force': 0.8, 'actif': True}])
        self.assertIsNone(erreur)
        self.assertEqual(r['etapes'], 8)

    def test_modele_hors_du_dossier_refuse(self):
        for nom in ('../x.gguf', 'C:/x.gguf', '/Windows/x.gguf', 'D:x.gguf', '\\\\serveur\\partage\\x.gguf'):
            with self.subTest(nom=nom):
                self.assertIsNotNone(valider(modele_diffusion=nom)[1])

    def test_lora_invalide_refuse(self):
        for nom in ('../x.safetensors', '/x.safetensors', 'a:b.safetensors', 'a<b.safetensors', 'x.txt'):
            with self.subTest(nom=nom):
                self.assertIsNotNone(valider(loras=[{'nom': nom, 'force': 1}])[1])

    def test_valeurs_hors_limites_refusees(self):
        cas = {'etapes': 0, 'cfg': 31, 'methode': 'inconnue', 'arret_auto_minutes': 0,
               'sigmas': '1,0.5,0', 'ollama_adresse': 'http://exemple.com/chemin'}
        for cle, valeur in cas.items():
            with self.subTest(cle=cle):
                self.assertIsNotNone(valider(**{cle: valeur})[1])
        self.assertIsNotNone(valider(loras=[{'nom': 'x.safetensors', 'force': 3}])[1])

    def test_modeles_obligatoires(self):
        self.assertIsNotNone(valider(vae='')[1])

    def test_acces_reseau_desactive_par_defaut(self):
        self.assertFalse(serveur.REGLAGES_DEFAUT['acces_reseau'])

    def test_fichier_avec_bom_et_cle_inconnue(self):
        serveur.DONNEES.mkdir(exist_ok=True)
        serveur.FICHIER_REGLAGES.write_text(json.dumps({'etapes': 9, 'inconnue': 1}), encoding='utf-8-sig')
        try:
            r = serveur.lire_reglages()
            self.assertEqual(r['etapes'], 9)
            self.assertNotIn('inconnue', r)
        finally:
            serveur.FICHIER_REGLAGES.unlink()


class AmeliorationReglagesTest(unittest.TestCase):
    def test_moteur_inconnu_refuse(self):
        self.assertIsNotNone(valider(amelioration_moteur='autre')[1])

    def test_modele_de_langage_hors_du_dossier_refuse(self):
        self.assertIsNotNone(valider(amelioration_modele_local='../x.gguf')[1])
        self.assertIsNotNone(valider(amelioration_vision_locale='/x.gguf')[1])

    def test_moteur_integre_par_defaut(self):
        self.assertEqual(serveur.REGLAGES_DEFAUT['amelioration_moteur'], 'integre')


def creer_zip(chemin, fichiers):
    import zipfile
    with zipfile.ZipFile(chemin, 'w') as z:
        for nom, contenu in fichiers.items():
            z.writestr(nom, contenu)


class InstallationMoteurTest(unittest.TestCase):
    def setUp(self):
        self.dossier = Path(tempfile.mkdtemp(dir=DOSSIER_TEST.name))
        self.moteurs = dict(serveur.MOTEURS)

    def tearDown(self):
        serveur.MOTEURS.clear()
        serveur.MOTEURS.update(self.moteurs)
        serveur.installations.pop('test', None)

    def test_extraction_refuse_les_chemins_qui_sortent(self):
        for nom in ('../evasion.dll', '/racine.dll', 'C:/lecteur.dll'):
            with self.subTest(nom=nom):
                archive = self.dossier / 'piege.zip'
                creer_zip(archive, {'outil.exe': b'ok', nom: b'piege'})
                with self.assertRaises(RuntimeError):
                    serveur.extraire_archive(archive, self.dossier / 'sortie')

    def test_extraction_retire_le_dossier_racine_commun(self):
        archive = self.dossier / 'paquet.zip'
        creer_zip(archive, {'paquet/outil.exe': b'ok', 'paquet/lib/a.dll': b'a'})
        serveur.extraire_archive(archive, self.dossier / 'sortie')
        self.assertTrue((self.dossier / 'sortie' / 'outil.exe').is_file())
        self.assertTrue((self.dossier / 'sortie' / 'lib' / 'a.dll').is_file())

    def installer(self, empreinte_juste):
        import hashlib
        archive = self.dossier / 'moteur.zip'
        creer_zip(archive, {'outil.exe': b'moteur de test'})
        contenu = archive.read_bytes()
        serveur.MOTEURS['test'] = {
            'nom': 'test', 'version': '1', 'dossier': 'moteur-test', 'executable': 'outil.exe',
            'archives': [{'url': archive.as_uri(), 'taille': len(contenu),
                          'sha256': hashlib.sha256(contenu).hexdigest() if empreinte_juste else '0' * 64}]}
        serveur.installations['test'] = {'phase': 'telechargement', 'fait': 0, 'total': len(contenu), 'erreur': None}
        shutil_dossier = serveur.RACINE / 'moteur-test'
        self.addCleanup(lambda: __import__('shutil').rmtree(shutil_dossier, ignore_errors=True))
        serveur.installer_moteur('test')
        return serveur.installations['test'], shutil_dossier

    def test_installation_complete(self):
        suivi, dossier = self.installer(empreinte_juste=True)
        self.assertEqual(suivi['phase'], 'termine', suivi.get('erreur'))
        self.assertTrue((dossier / 'outil.exe').is_file())
        self.assertTrue(serveur.moteur_installe('test'))

    def test_empreinte_differente_refusee(self):
        suivi, dossier = self.installer(empreinte_juste=False)
        self.assertEqual(suivi['phase'], 'erreur')
        self.assertFalse(dossier.exists())

    def test_versions_officielles_epinglees(self):
        for systeme, moteurs in serveur.MOTEURS_PAR_SYSTEME.items():
            self.assertEqual(set(moteurs), {'image', 'texte'})
            for nom, moteur in moteurs.items():
                for archive in moteur['archives']:
                    with self.subTest(systeme=systeme, moteur=nom, url=archive['url']):
                        self.assertTrue(archive['url'].startswith(('https://github.com/leejet/', 'https://github.com/ggml-org/')))
                        self.assertRegex(archive['sha256'], r'^[0-9a-f]{64}$')

    def test_extraction_tar_avec_liens(self):
        import io
        import tarfile
        archive = self.dossier / 'paquet.tar.gz'
        with tarfile.open(archive, 'w:gz') as t:
            for nom, contenu in (('paquet/outil', b'ok'), ('paquet/libx.so.1', b'lib')):
                info = tarfile.TarInfo(nom)
                info.size, info.mode = len(contenu), 0o755
                t.addfile(info, io.BytesIO(contenu))
            lien = tarfile.TarInfo('paquet/libx.so')
            lien.type, lien.linkname = tarfile.SYMTYPE, 'libx.so.1'
            t.addfile(lien)
        sortie = self.dossier / 'sortie-tar'
        sortie.mkdir()
        serveur.extraire_archive(archive, sortie)
        self.assertTrue((sortie / 'outil').is_file())
        self.assertTrue((sortie / 'libx.so.1').is_file())

    def test_extraction_tar_refuse_un_lien_qui_sort(self):
        import tarfile
        archive = self.dossier / 'piege.tar.gz'
        with tarfile.open(archive, 'w:gz') as t:
            lien = tarfile.TarInfo('paquet/evasion')
            lien.type, lien.linkname = tarfile.SYMTYPE, '../../../ailleurs'
            t.addfile(lien)
        sortie = self.dossier / 'sortie-piege'
        sortie.mkdir()
        with self.assertRaises(Exception):
            serveur.extraire_archive(archive, sortie)


class LiensModelesTest(unittest.TestCase):
    """Les liens vers les modeles restent sur Hugging Face, vers des modeles officiels et tout public."""
    PROJET = Path(__file__).resolve().parent.parent
    INTERDITS = ('uncensored', 'abliterat', 'nsfw', 'heretic', 'unfiltered', 'lewd')

    def test_liens_officiels_et_tout_public(self):
        import re
        for fichier in ('app/index.html', 'README.md', 'README.fr.md'):
            texte = (self.PROJET / fichier).read_text(encoding='utf-8')
            liens = re.findall(r'https://huggingface\.co/[^\s"\')<>]+', texte)
            self.assertTrue(liens, fichier)
            for lien in liens:
                self.assertFalse(any(mot in lien.lower() for mot in self.INTERDITS), lien)
            self.assertFalse(any(mot in texte.lower() for mot in self.INTERDITS), fichier)


class ModelesConseillesTest(unittest.TestCase):
    """Catalogue des modeles telechargeables : officiels, tout public, verifies ; reprise et choix automatique."""

    def setUp(self):
        self.dossier = Path(DOSSIER_TEST.name)
        serveur.FICHIER_REGLAGES.unlink(missing_ok=True)
        for f in serveur.MODELES.glob('essai*'):
            f.unlink()

    def test_catalogue(self):
        import re
        self.assertEqual(len(serveur.MODELES_PAR_ID), len(serveur.MODELES_CONSEILLES))
        for m in serveur.MODELES_CONSEILLES:
            self.assertTrue(m['url'].startswith('https://huggingface.co/'), m['url'])
            self.assertFalse(any(mot in (m['url'] + m['fichier']).lower() for mot in LiensModelesTest.INTERDITS), m['url'])
            self.assertRegex(m['sha256'], r'^[0-9a-f]{64}$')
            self.assertGreater(m['taille'], 100_000_000)
            self.assertTrue(serveur.chemin_relatif_sur(m['fichier']) and '/' not in m['fichier'])
            self.assertTrue(set(m['remplit']) <= set(serveur.REGLAGES_DEFAUT), m['id'])
        # Pour chaque ensemble (complet, leger), un seul modele conseille par role
        for profil in ('complet', 'leger'):
            for role in ('modele_diffusion', 'modele_texte', 'modele_vision', 'vae'):
                conseilles = [m['id'] for m in serveur.MODELES_CONSEILLES if role in m['remplit'] and profil in m['pour']]
                self.assertEqual(len(conseilles), 1, (profil, role, conseilles))
        # L'ensemble leger tient dans environ 11 Go
        leger = sum(m['taille'] for m in serveur.MODELES_CONSEILLES if 'leger' in m['pour'])
        self.assertLess(leger, 11 * 1024 ** 3)

    def servir(self, contenu):
        """Petit serveur HTTP local qui sait reprendre un telechargement (en-tete Range)."""
        import http.server

        class Fichier(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                debut = 0
                plage = self.headers.get('Range')
                if plage:
                    debut = int(plage.split('=')[1].split('-')[0])
                    self.send_response(206)
                else:
                    self.send_response(200)
                self.send_header('Content-Length', str(len(contenu) - debut))
                self.end_headers()
                self.wfile.write(contenu[debut:])

        hote = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Fichier)
        threading.Thread(target=hote.serve_forever, daemon=True).start()
        self.addCleanup(hote.server_close)
        self.addCleanup(hote.shutdown)
        return f'http://127.0.0.1:{hote.server_address[1]}/modele'

    def modele(self, contenu, **autres):
        import hashlib
        m = {'id': 'essai', 'fichier': 'essai-dessin.gguf', 'url': self.servir(contenu), 'taille': len(contenu),
             'sha256': hashlib.sha256(contenu).hexdigest(), 'remplit': ['modele_diffusion'], 'profil_rapide': True}
        m.update(autres)
        serveur.telechargements_modeles[m['id']] = {'phase': 'telechargement', 'fait': 0, 'total': m['taille'], 'erreur': None}
        return m

    def test_telechargement_repris_puis_choisi(self):
        contenu = os.urandom(300_000)
        m = self.modele(contenu)
        serveur.MODELES.mkdir(parents=True, exist_ok=True)
        (serveur.MODELES / 'essai-dessin.gguf.partiel').write_bytes(contenu[:120_000])
        serveur.telecharger_modele(m)
        self.assertEqual(serveur.telechargements_modeles['essai']['phase'], 'termine')
        self.assertEqual((serveur.MODELES / 'essai-dessin.gguf').read_bytes(), contenu)
        self.assertFalse((serveur.MODELES / 'essai-dessin.gguf.partiel').exists())
        r = serveur.lire_reglages()
        self.assertEqual(r['modele_diffusion'], 'essai-dessin.gguf')
        self.assertEqual((r['etapes'], r['cfg'], r['sigmas']), (8, 1.0, serveur.SIGMAS_RAPIDE))

    def test_fichier_different_refuse(self):
        m = self.modele(os.urandom(50_000), sha256='0' * 64)
        serveur.telecharger_modele(m)
        self.assertEqual(serveur.telechargements_modeles['essai']['phase'], 'erreur')
        self.assertFalse((serveur.MODELES / 'essai-dessin.gguf').exists())
        self.assertFalse((serveur.MODELES / 'essai-dessin.gguf.partiel').exists())
        self.assertEqual(serveur.lire_reglages()['modele_diffusion'], '')

    def test_modele_telecharge_remplace_mais_garde_les_etapes_reglees(self):
        serveur.MODELES.mkdir(parents=True, exist_ok=True)
        (serveur.MODELES / 'essai-mien.gguf').write_bytes(b'x')
        serveur.FICHIER_REGLAGES.parent.mkdir(exist_ok=True)
        serveur.FICHIER_REGLAGES.write_text(json.dumps({'modele_diffusion': 'essai-mien.gguf', 'etapes': 12}), encoding='utf-8')
        serveur.telecharger_modele(self.modele(os.urandom(20_000)))
        r = serveur.lire_reglages()
        self.assertEqual((r['modele_diffusion'], r['etapes']), ('essai-dessin.gguf', 12))

    def test_profil_selon_la_memoire(self):
        from unittest import mock
        cas = [(False, 32, 12, 'complet'), (False, 32, 8, 'leger'), (False, 16, 0, 'leger'), (False, 32, 0, 'complet'),
               (True, 18, 18, 'leger'), (True, 36, 36, 'complet')]
        for mac, vive, video, attendu in cas:
            serveur._machine = None
            with mock.patch.object(serveur, 'MAC', mac),                     mock.patch.object(serveur, 'memoire_systeme', return_value=vive * serveur.GO),                     mock.patch.object(serveur, 'memoire_video', return_value=video * serveur.GO):
                self.assertEqual(serveur.profil_machine()['profil'], attendu, (mac, vive, video))
        serveur._machine = None

    def test_fenetre_propose_le_modele_et_le_moteur_de_texte(self):
        from unittest import mock
        for profil in ('complet', 'leger'):
            with mock.patch.object(serveur, 'profil_machine', return_value={'profil': profil}):
                infos = serveur.etat_modeles_conseilles()
            # Chaque role a un modele conseille, sous un nom clair
            roles = {m['role'] for m in infos['modeles'] if m['conseille']}
            self.assertEqual(roles, {'Modèle de dessin', 'Modèle de texte', 'Vision', 'VAE'}, profil)
            # Le moteur de texte du bouton Ameliorer est propose dans la meme fenetre
            texte = infos['moteurs']['texte']
            self.assertEqual(texte['nom'], 'llama.cpp')
            self.assertGreater(texte['taille'], 0)
            self.assertIn('installe', texte)


class ChoixMoteursTest(unittest.TestCase):
    def test_windows_sans_nvidia_passe_par_vulkan(self):
        from unittest import mock
        with mock.patch.object(serveur, 'WINDOWS', True), mock.patch.dict(os.environ, {'PRISME_ACCELERATION': ''}):
            with mock.patch.object(serveur, 'carte_nvidia', return_value=False):
                self.assertEqual(serveur.choisir_moteurs(), 'windows-vulkan')
            with mock.patch.object(serveur, 'carte_nvidia', return_value=True):
                self.assertEqual(serveur.choisir_moteurs(), 'windows')
                os.environ['PRISME_ACCELERATION'] = 'vulkan'
                self.assertEqual(serveur.choisir_moteurs(), 'windows-vulkan')
        self.assertEqual(set(serveur.MOTEURS_PAR_SYSTEME['windows-vulkan']), {'image', 'texte'})
        self.assertNotIn('requiert', serveur.MOTEURS_PAR_SYSTEME['windows-vulkan']['texte'])


class TelechargementsTest(unittest.TestCase):
    """Erreurs passageres des serveurs de telechargement : nouveaux essais, reprise, message clair."""

    def setUp(self):
        from unittest import mock
        patch = mock.patch.object(serveur, 'PAUSE_ESSAI', 0)
        patch.start()
        self.addCleanup(patch.stop)
        self.dossier = Path(tempfile.mkdtemp(dir=DOSSIER_TEST.name))

    def servir(self, contenu, echecs=0, coupures=0):
        """Serveur local : renvoie 504 les premieres fois, puis coupe la connexion en cours de route, puis sert le fichier."""
        import http.server
        compteur = {'echecs': echecs, 'coupures': coupures, 'requetes': 0}

        class Fichier(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                compteur['requetes'] += 1
                if compteur['echecs']:
                    compteur['echecs'] -= 1
                    self.send_response(504)
                    self.end_headers()
                    return
                debut = 0
                if self.headers.get('Range'):
                    debut = int(self.headers['Range'].split('=')[1].split('-')[0])
                    self.send_response(206)
                else:
                    self.send_response(200)
                self.send_header('Content-Length', str(len(contenu) - debut))
                self.end_headers()
                if compteur['coupures']:
                    compteur['coupures'] -= 1
                    self.wfile.write(contenu[debut:debut + (len(contenu) - debut) // 2])
                    self.wfile.flush()
                    self.connection.close()
                    return
                self.wfile.write(contenu[debut:])

        hote = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Fichier)
        threading.Thread(target=hote.serve_forever, daemon=True).start()
        self.addCleanup(hote.server_close)
        self.addCleanup(hote.shutdown)
        return f'http://127.0.0.1:{hote.server_address[1]}/fichier', compteur

    def test_moteur_apres_erreurs_504(self):
        import hashlib
        contenu = os.urandom(200_000)
        url, compteur = self.servir(contenu, echecs=2)
        total = []
        serveur.telecharger({'url': url, 'taille': len(contenu), 'sha256': hashlib.sha256(contenu).hexdigest()},
                            self.dossier / 'moteur.zip', total.append)
        self.assertEqual((self.dossier / 'moteur.zip').read_bytes(), contenu)
        self.assertEqual(sum(total), len(contenu))
        self.assertEqual(compteur['requetes'], 3)

    def test_moteur_coupe_en_route_puis_complet(self):
        import hashlib
        contenu = os.urandom(300_000)
        url, _ = self.servir(contenu, coupures=1)
        total = []
        serveur.telecharger({'url': url, 'taille': len(contenu), 'sha256': hashlib.sha256(contenu).hexdigest()},
                            self.dossier / 'moteur.zip', total.append)
        self.assertEqual(sum(total), len(contenu))

    def test_message_clair_si_le_serveur_ne_repond_jamais(self):
        from unittest import mock
        url, compteur = self.servir(b'x', echecs=99)
        with mock.patch.object(serveur, 'ESSAIS', 3), self.assertRaises(RuntimeError) as erreur:
            serveur.telecharger({'url': url, 'taille': 1, 'sha256': '0' * 64}, self.dossier / 'moteur.zip', lambda n: None)
        self.assertIn('ne répond pas (erreur 504)', str(erreur.exception))
        self.assertEqual(compteur['requetes'], 3)

    def test_modele_repris_apres_coupure(self):
        import hashlib
        contenu = os.urandom(400_000)
        url, compteur = self.servir(contenu, echecs=1, coupures=1)
        m = {'id': 'essai-reprise', 'fichier': 'essai-reprise.gguf', 'url': url, 'taille': len(contenu),
             'sha256': hashlib.sha256(contenu).hexdigest(), 'remplit': ['modele_diffusion']}
        serveur.telechargements_modeles[m['id']] = {'phase': 'telechargement', 'fait': 0, 'total': m['taille'], 'erreur': None}
        self.addCleanup(lambda: (serveur.MODELES / m['fichier']).unlink(missing_ok=True))
        serveur.telecharger_modele(m)
        self.assertEqual(serveur.telechargements_modeles[m['id']]['phase'], 'termine')
        self.assertEqual((serveur.MODELES / m['fichier']).read_bytes(), contenu)
        self.assertEqual(compteur['requetes'], 3)

    def test_chaque_moteur_a_son_lien_de_secours(self):
        import re
        for systeme, moteurs in serveur.MOTEURS_PAR_SYSTEME.items():
            for moteur in moteurs.values():
                for archive in moteur['archives']:
                    self.assertRegex(archive['secours'] or '',
                                     r'^https://api\.github\.com/repos/(leejet/stable-diffusion\.cpp|ggml-org/llama\.cpp)/releases/assets/\d+$',
                                     (systeme, archive['url']))

    def test_lien_de_secours_utilise_apres_deux_echecs(self):
        import hashlib
        contenu = os.urandom(150_000)
        direct, compteur_direct = self.servir(b'', echecs=99)
        secours, compteur_secours = self.servir(contenu)
        total = []
        serveur.telecharger({'url': direct, 'secours': secours, 'taille': len(contenu),
                             'sha256': hashlib.sha256(contenu).hexdigest()}, self.dossier / 'moteur.zip', total.append)
        self.assertEqual((compteur_direct['requetes'], compteur_secours['requetes']), (2, 1))
        self.assertEqual(sum(total), len(contenu))

    def test_jeton_github_seulement_pour_l_api(self):
        from unittest import mock
        with mock.patch.dict(os.environ, {'GITHUB_TOKEN': 'jeton-essai'}):
            api = serveur.requete_github('https://api.github.com/repos/d3Ita/prisme/releases/latest')
            autre = serveur.requete_github('https://github.com/d3Ita/prisme/releases/download/v1/Prisme.exe')
        # Le jeton n'est pas transmis lors d'une redirection (vers le stockage des fichiers)
        self.assertEqual(api.unredirected_hdrs.get('Authorization'), 'Bearer jeton-essai')
        self.assertNotIn('Authorization', api.headers)
        self.assertNotIn('Authorization', autre.unredirected_hdrs)
        self.assertNotIn('Authorization', autre.headers)

    def test_lien_de_secours_github(self):
        import io
        from unittest import mock
        reponse = io.BytesIO(json.dumps({'assets': [
            {'name': 'moteur.zip', 'url': 'https://api.github.com/repos/projet/moteur/releases/assets/42'},
            {'name': 'autre.zip', 'url': 'https://api.github.com/repos/projet/moteur/releases/assets/43'}]}).encode())
        with mock.patch.object(serveur.urllib.request, 'urlopen', return_value=reponse):
            self.assertEqual(serveur.lien_api_github('https://github.com/projet/moteur/releases/download/v1/moteur.zip'),
                             'https://api.github.com/repos/projet/moteur/releases/assets/42')
        self.assertIsNone(serveur.lien_api_github('https://huggingface.co/projet/modele/resolve/main/modele.gguf'))

class CertificatsTest(unittest.TestCase):
    """Telechargements en https : si le Python embarque ne trouve aucun certificat (exe Mac), ceux du systeme sont charges."""

    def setUp(self):
        serveur._contexte_ssl = None
        self.addCleanup(setattr, serveur, '_contexte_ssl', None)

    def test_certificats_trouves(self):
        self.assertGreater(serveur.contexte_ssl().cert_store_stats()['x509_ca'], 0)

    def test_certificats_du_systeme_si_aucun(self):
        import ssl
        from unittest import mock
        # Fichier de certificats « du systeme », fait a partir de ceux de cette machine
        pem = ''.join(ssl.DER_cert_to_PEM_cert(c) for c in ssl.create_default_context().get_ca_certs(binary_form=True))
        fichier = Path(DOSSIER_TEST.name) / 'cert.pem'
        fichier.write_text(pem, encoding='ascii')
        vide = lambda: ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        with mock.patch.object(serveur.ssl, 'create_default_context', vide),                 mock.patch.object(serveur, 'FICHIERS_CERTIFICATS', ['/nexiste/pas.pem', str(fichier)]):
            self.assertGreater(serveur.contexte_ssl().cert_store_stats()['x509_ca'], 0)

class VersionTest(unittest.TestCase):
    def test_comparaison(self):
        self.assertGreater(serveur.numero_version('v1.10.0'), serveur.numero_version('1.9.2'))
        self.assertEqual(serveur.numero_version('v1.7.0'), serveur.numero_version('1.7.0'))
        self.assertGreater(serveur.numero_version('2.0'), serveur.numero_version(serveur.VERSION))

    def release(self, **fichier):
        a = {'name': serveur.FICHIER_MAJ, 'size': 123, 'digest': 'sha256:' + 'a' * 64,
             'browser_download_url': f'https://github.com/d3Ita/prisme/releases/download/v9.9.9/{serveur.FICHIER_MAJ}'}
        a.update(fichier)
        return {'tag_name': 'v9.9.9', 'assets': [a, {'name': 'autre.zip', 'size': 1, 'digest': 'sha256:' + 'b' * 64,
                                                       'browser_download_url': 'https://github.com/d3Ita/prisme/releases/download/v9.9.9/autre.zip'}]}

    def test_fichier_de_mise_a_jour(self):
        version, fichier = serveur.lire_release(self.release())
        self.assertEqual(version, '9.9.9')
        self.assertEqual(fichier, {'url': f'https://github.com/d3Ita/prisme/releases/download/v9.9.9/{serveur.FICHIER_MAJ}',
                                   'taille': 123, 'sha256': 'a' * 64})
        # Refuse un fichier venu d'ailleurs ou sans empreinte
        self.assertIsNone(serveur.lire_release(self.release(browser_download_url='https://exemple.org/Prisme.exe'))[1])
        self.assertIsNone(serveur.lire_release(self.release(browser_download_url='https://github.com/autre/prisme/releases/download/v9/x'))[1])
        self.assertIsNone(serveur.lire_release(self.release(digest=None))[1])
        self.assertIsNone(serveur.lire_release(self.release(digest='md5:1234'))[1])

    def test_script_de_remplacement(self):
        nouveau, cible = Path(DOSSIER_TEST.name) / 'nouveau', Path(DOSSIER_TEST.name) / 'Prisme'
        script = serveur.script_remplacement(nouveau, cible, [4242, 4343])
        for pid in ('4242', '4343'):
            self.assertIn(pid, script)
        self.assertIn('--sans-fenetre', script)
        self.assertIn(str(cible), script)
        if serveur.WINDOWS:
            self.assertIn(f'move /y "{nouveau}" "{cible}"', script)
        else:
            self.assertIn('kill -0 4242', script)

    def test_etat_sans_details_internes(self):
        serveur.mise_a_jour.clear()
        self.addCleanup(serveur.mise_a_jour.clear)
        self.assertIsNone(serveur.etat_mise_a_jour())
        version, fichier = serveur.lire_release(self.release())
        serveur.mise_a_jour.update(version=version, url=serveur.PAGE_VERSIONS, fichier=fichier, auto=True)
        self.assertEqual(serveur.etat_mise_a_jour(), {'version': '9.9.9', 'url': serveur.PAGE_VERSIONS, 'auto': True, 'installation': None})

class ArretAutomatiqueTest(unittest.TestCase):
    def setUp(self):
        self.reglages = {**serveur.REGLAGES_DEFAUT, 'arret_auto_minutes': 30, 'arret_fermeture': True}
        self.sauvegarde = (serveur.dernier_contact, serveur.dernier_contact_local, serveur.fermeture_demandee,
                           dict(serveur.etat))

    def tearDown(self):
        serveur.dernier_contact, serveur.dernier_contact_local, serveur.fermeture_demandee, etat = self.sauvegarde
        serveur.etat.clear()
        serveur.etat.update(etat)

    def situation(self, fermeture_il_y_a=None, contact_local_il_y_a=60, contact_il_y_a=1, occupe=False):
        maintenant = 10_000.0
        serveur.dernier_contact = maintenant - contact_il_y_a
        serveur.dernier_contact_local = maintenant - contact_local_il_y_a
        serveur.fermeture_demandee = None if fermeture_il_y_a is None else maintenant - fermeture_il_y_a
        serveur.etat['occupe'] = occupe
        return serveur.doit_s_arreter(maintenant, self.reglages)

    def test_fenetre_fermee_puis_delai_ecoule(self):
        self.assertTrue(self.situation(fermeture_il_y_a=serveur.DELAI_FERMETURE + 1))

    def test_attend_le_delai_avant_de_s_arreter(self):
        self.assertFalse(self.situation(fermeture_il_y_a=1))

    def test_fenetre_rouverte_apres_la_fermeture(self):
        self.assertFalse(self.situation(fermeture_il_y_a=serveur.DELAI_FERMETURE + 5, contact_local_il_y_a=2))

    def test_reglage_desactive(self):
        self.reglages['arret_fermeture'] = False
        self.assertFalse(self.situation(fermeture_il_y_a=60))

    def test_generation_en_cours_jamais_interrompue(self):
        self.assertFalse(self.situation(fermeture_il_y_a=60, occupe=True))
        self.assertFalse(self.situation(contact_il_y_a=10_000, occupe=True))

    def test_inactivite_trop_longue(self):
        self.assertTrue(self.situation(contact_il_y_a=31 * 60))
        self.assertFalse(self.situation(contact_il_y_a=29 * 60))

    def test_arret_a_la_fermeture_par_defaut(self):
        self.assertTrue(serveur.REGLAGES_DEFAUT['arret_fermeture'])


class CodeAccesTest(unittest.TestCase):
    def test_code_de_128_bits(self):
        self.assertGreaterEqual(len(serveur.CODE), 20)

    def test_ancien_code_court_remplace(self):
        serveur.FICHIER_CODE.write_text('abcd1234', encoding='utf-8')
        try:
            nouveau = serveur.code_acces()
            self.assertNotEqual(nouveau, 'abcd1234')
            self.assertGreaterEqual(len(nouveau), 20)
        finally:
            serveur.FICHIER_CODE.write_text(serveur.CODE, encoding='utf-8')


def png(texte, largeur=640, hauteur=480):
    def bloc(genre, donnees):
        return struct.pack('>I', len(donnees)) + genre + donnees + struct.pack('>I', zlib.crc32(genre + donnees))
    return (b'\x89PNG\r\n\x1a\n'
            + bloc(b'IHDR', struct.pack('>IIBBBBB', largeur, hauteur, 8, 6, 0, 0, 0))
            + bloc(b'tEXt', b'parameters\x00' + texte.encode('utf-8'))
            + bloc(b'IDAT', zlib.compress(b'\x00'))
            + bloc(b'IEND', b''))


class MetadonneesTest(unittest.TestCase):
    def test_lecture_prompt_seed_et_lora(self):
        serveur.IMAGES.mkdir(exist_ok=True)
        chemin = serveur.IMAGES / 'image_test_meta.png'
        chemin.write_bytes(png('une forêt la nuit<lora:style:0.8>\nSteps: 8, Seed: 42, Size: 640x480'))
        try:
            infos = serveur.lire_infos(chemin)
            self.assertEqual(infos['prompt'], 'une forêt la nuit')
            self.assertEqual(infos['seed'], 42)
            self.assertEqual(infos['loras'], ['style (0.8)'])
            self.assertEqual((infos['largeur'], infos['hauteur']), (640, 480))
        finally:
            chemin.unlink()


class GestionnaireTest(serveur.Gestionnaire):
    """L'en-tete X-Test-Distant fait passer la requete pour celle d'un autre appareil du reseau."""

    def est_local(self):
        return self.headers.get('X-Test-Distant') != '1' and super().est_local()


class SecuriteHttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.serveur = serveur.Serveur(('127.0.0.1', 0), GestionnaireTest)
        cls.port = cls.serveur.server_address[1]
        serveur.PORT = cls.port
        threading.Thread(target=cls.serveur.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.serveur.shutdown()
        cls.serveur.server_close()

    def setUp(self):
        serveur.echecs.clear()
        serveur.demandes.clear()

    def requete(self, methode, chemin, corps=None, entetes=None, hote=None):
        connexion = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        connexion.putrequest(methode, chemin, skip_host=True)
        connexion.putheader('Host', hote or f'127.0.0.1:{self.port}')
        for cle, valeur in (entetes or {}).items():
            connexion.putheader(cle, valeur)
        donnees = corps.encode() if isinstance(corps, str) else (corps or b'')
        if methode == 'POST' and 'Content-Length' not in (entetes or {}):
            connexion.putheader('Content-Length', str(len(donnees)))
        connexion.endheaders(donnees or None)
        reponse = connexion.getresponse()
        resultat = (reponse.status, reponse.getheader('Set-Cookie'), reponse.read())
        connexion.close()
        return resultat

    def poster(self, chemin, corps='{}', entetes=None):
        return self.requete('POST', chemin, corps, {'Content-Type': 'application/json', **(entetes or {})})

    def distant(self, chemin, code=None, methode='GET'):
        entetes = {'X-Test-Distant': '1'}
        if code is not None:
            entetes['Cookie'] = f'prisme_acces={code}'
        if methode == 'POST':
            entetes['Content-Type'] = 'application/json'
            return self.requete('POST', chemin, '{}', entetes)
        return self.requete('GET', chemin, entetes=entetes)

    # --- DNS rebinding
    def test_nom_d_hote_etranger_refuse(self):
        self.assertEqual(self.requete('GET', '/api/etat', hote=f'attaquant.example:{self.port}')[0], 403)

    def test_mauvais_port_refuse(self):
        self.assertEqual(self.requete('GET', '/api/etat', hote='127.0.0.1:1')[0], 403)

    def test_logo_servi(self):
        statut, _, corps = self.requete('GET', '/logo.png')
        self.assertEqual(statut, 200)
        self.assertTrue(corps.startswith(b'\x89PNG'))

    def test_logo_et_manifeste_publics_mais_rien_d_autre(self):
        self.assertEqual(self.distant('/logo.png')[0], 200)
        statut, _, corps = self.distant('/manifest.webmanifest')
        self.assertEqual(statut, 200)
        self.assertEqual(json.loads(corps)['icons'][0]['src'], '/logo.png')
        self.assertEqual(self.distant('/api/images')[0], 401)
        # Le controle du nom d'hote s'applique aussi aux fichiers publics
        self.assertEqual(self.requete('GET', '/logo.png', hote=f'attaquant.example:{self.port}')[0], 403)

    def test_localhost_et_ip_acceptes(self):
        self.assertEqual(self.requete('GET', '/api/etat', hote=f'localhost:{self.port}')[0], 200)
        self.assertEqual(self.requete('GET', '/api/etat')[0], 200)

    # --- requetes envoyees par d'autres sites
    def test_post_non_json_refuse(self):
        for type_contenu in ('text/plain', 'application/x-www-form-urlencoded', 'multipart/form-data'):
            with self.subTest(type_contenu=type_contenu):
                self.assertEqual(self.requete('POST', '/api/annuler', '{}', {'Content-Type': type_contenu})[0], 415)

    def test_origine_etrangere_refusee(self):
        self.assertEqual(self.poster('/api/annuler', entetes={'Origin': 'https://site-malveillant.example'})[0], 403)

    def test_meme_origine_acceptee(self):
        self.assertEqual(self.poster('/api/annuler', entetes={'Origin': f'http://127.0.0.1:{self.port}'})[0], 200)

    # --- donnees invalides
    def test_json_invalide(self):
        self.assertEqual(self.poster('/api/supprimer', '{pas du json')[0], 400)

    def test_requete_trop_grande(self):
        entetes = {'Content-Type': 'application/json', 'Content-Length': str(serveur.TAILLE_MAX_REQUETE + 1)}
        self.assertEqual(self.requete('POST', '/api/supprimer', '{}', entetes)[0], 400)

    def test_fichier_hors_du_dossier_images(self):
        self.assertEqual(self.requete('GET', '/images/..%2Fapp%2Fcode-acces.txt')[0], 404)
        self.assertEqual(self.poster('/api/supprimer', json.dumps({'nom': '../app/code-acces.txt'}))[0], 404)
        self.assertTrue(serveur.FICHIER_CODE.exists())

    # --- autres appareils du reseau
    def test_appareil_sans_code_refuse(self):
        self.assertEqual(self.distant('/api/etat')[0], 401)
        self.assertEqual(self.distant('/')[0], 401)
        # La page de connexion suit la langue du telephone
        francaise = self.requete('GET', '/', entetes={'X-Test-Distant': '1', 'Accept-Language': 'fr-FR,fr;q=0.9'})[2]
        anglaise = self.requete('GET', '/', entetes={'X-Test-Distant': '1', 'Accept-Language': 'en-US,en;q=0.9'})[2]
        self.assertIn('Connexion à Prisme', francaise.decode('utf-8'))
        self.assertIn('Connect to Prisme', anglaise.decode('utf-8'))
        self.assertNotIn('Connexion à Prisme', anglaise.decode('utf-8'))

    def test_appareil_avec_bon_code_accepte(self):
        self.assertEqual(self.distant('/api/etat', serveur.CODE)[0], 200)
        self.assertEqual(self.distant('/api/annuler', serveur.CODE, 'POST')[0], 200)

    def test_lien_du_qr_code_depose_le_cookie(self):
        statut, cookie, _ = self.requete('GET', f'/?code={serveur.CODE}', entetes={'X-Test-Distant': '1'})
        self.assertEqual(statut, 302)
        self.assertIn(f'prisme_acces={serveur.CODE}', cookie)
        self.assertIn('HttpOnly', cookie)
        self.assertEqual(self.requete('GET', '/?code=faux', entetes={'X-Test-Distant': '1'})[0], 401)

    def test_installation_de_moteur(self):
        self.assertEqual(self.poster('/api/installer-moteur', json.dumps({'moteur': 'inconnu'}))[0], 400)
        self.assertEqual(self.distant('/api/installer-moteur', serveur.CODE, 'POST')[0], 403)
        # La mise a jour ne se lance que depuis le PC, et seulement quand une version automatique existe
        self.assertEqual(self.distant('/api/mettre-a-jour', serveur.CODE, 'POST')[0], 403)
        serveur.mise_a_jour.clear()
        self.assertEqual(self.poster('/api/mettre-a-jour')[0], 400)
        etat = json.loads(self.requete('GET', '/api/etat')[2])
        self.assertEqual(set(etat['moteurs']), {'image', 'texte'})

    # --- connexion en tapant seulement l'adresse : demande acceptee sur le PC
    def demander(self):
        statut, _, corps = self.requete('POST', '/acces/demander', '{}',
                                        {'Content-Type': 'application/json', 'X-Test-Distant': '1', 'User-Agent': 'Mozilla (Linux; Android 15)'})
        return statut, json.loads(corps)

    def suivre_demande(self, ident):
        statut, cookie, corps = self.requete('GET', f'/acces/etat?id={ident}', entetes={'X-Test-Distant': '1'})
        return json.loads(corps)['etat'], cookie

    def repondre(self, ident, accepter, distant=False):
        entetes = {'Content-Type': 'application/json'}
        if distant:
            entetes.update({'X-Test-Distant': '1', 'Cookie': f'prisme_acces={serveur.CODE}'})
        return self.requete('POST', '/api/repondre-demande', json.dumps({'id': ident, 'accepter': accepter}), entetes)[0]

    def test_page_de_connexion_pour_un_nouvel_appareil(self):
        statut, _, corps = self.distant('/')
        self.assertEqual(statut, 401)
        self.assertIn('Connexion à Prisme', corps.decode('utf-8'))

    def test_demande_acceptee_sur_le_pc(self):
        statut, demande = self.demander()
        self.assertEqual(statut, 200)
        self.assertRegex(demande['code'], r'^\d{4}$')
        self.assertEqual(self.suivre_demande(demande['id']), ('attente', None))
        visibles = json.loads(self.requete('GET', '/api/etat')[2])['demandes']
        self.assertEqual([(d['id'], d['code'], d['appareil']) for d in visibles], [(demande['id'], demande['code'], 'Android')])
        self.assertEqual(self.repondre(demande['id'], True), 200)
        etat, cookie = self.suivre_demande(demande['id'])
        self.assertEqual(etat, 'acceptee')
        self.assertIn(f'prisme_acces={serveur.CODE}', cookie)
        # Le cookie n'est remis qu'une seule fois
        self.assertEqual(self.suivre_demande(demande['id']), ('expiree', None))

    def test_demande_refusee(self):
        _, demande = self.demander()
        self.assertEqual(self.repondre(demande['id'], False), 200)
        self.assertEqual(self.suivre_demande(demande['id']), ('refusee', None))
        self.assertEqual(len(serveur.echecs.get('127.0.0.1', [])), 1)

    def test_seul_le_pc_peut_autoriser(self):
        _, demande = self.demander()
        self.assertEqual(self.repondre(demande['id'], True, distant=True), 403)
        self.assertEqual(self.suivre_demande(demande['id'])[0], 'attente')
        self.assertNotIn('demandes', json.loads(self.distant('/api/etat', serveur.CODE)[2]))

    def test_demande_inconnue_ou_trop_nombreuses(self):
        self.assertEqual(self.suivre_demande('inconnue'), ('expiree', None))
        statuts = [self.demander()[0] for _ in range(serveur.DEMANDES_MAX_PAR_APPAREIL + 1)]
        self.assertEqual(statuts[-1], 429)
        self.assertEqual(set(statuts[:-1]), {200})

    # --- arret du serveur
    def test_quitter_et_fermeture_reserves_au_pc(self):
        for chemin in ('/api/quitter', '/api/fermeture'):
            with self.subTest(chemin=chemin):
                self.assertEqual(self.distant(chemin, serveur.CODE, 'POST')[0], 403)

    def test_quitter_arrete_le_serveur(self):
        arrete = threading.Event()
        original = serveur.arreter
        serveur.arreter = arrete.set
        try:
            self.assertEqual(self.poster('/api/quitter')[0], 200)
            self.assertTrue(arrete.wait(3))
        finally:
            serveur.arreter = original

    def test_fermeture_annulee_si_la_fenetre_revient(self):
        self.assertEqual(self.poster('/api/fermeture')[0], 200)
        self.assertIsNotNone(serveur.fermeture_demandee)
        # Un rechargement de la page relance des requetes : la fermeture est oubliee
        self.requete('GET', '/api/etat')
        self.assertIsNone(serveur.fermeture_demandee)

    def test_reglages_reserves_au_pc(self):
        self.assertEqual(self.distant('/api/reglages', serveur.CODE)[0], 403)
        self.assertEqual(self.distant('/api/reglages', serveur.CODE, 'POST')[0], 403)
        self.assertEqual(self.distant('/api/acces', serveur.CODE)[0], 403)

    def test_blocage_apres_trop_de_codes_faux(self):
        statuts = [self.distant('/api/etat', f'faux{i}')[0] for i in range(serveur.ESSAIS_MAX)]
        self.assertEqual(set(statuts), {401})
        self.assertEqual(self.distant('/api/etat', 'encore-faux')[0], 429)
        self.assertEqual(self.distant('/api/etat', serveur.CODE)[0], 429)
        # Le PC lui-meme n'est jamais bloque
        self.assertEqual(self.requete('GET', '/api/etat')[0], 200)


if __name__ == '__main__':
    unittest.main()
