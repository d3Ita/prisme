"""Tests du serveur de Prisme : validation des reglages, lecture des images et protections d'acces.

Lancement : py -3 -m unittest discover -s tests -v
Le serveur travaille sur un dossier temporaire : tes reglages, images et code d'acces ne sont pas touches.
"""

import http.client
import json
import os
import shutil
import struct
import sys
import tempfile
import threading
import time
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


def io_json(donnees):
    import io
    return io.BytesIO(json.dumps(donnees).encode())


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
        catalogue = serveur.CATALOGUE
        ids = [m['id'] for m in catalogue['modeles']]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(serveur.MODELES_PAR_ID), len(serveur.MODELES_CONSEILLES))
        for m in catalogue['modeles']:
            with self.subTest(modele=m['id']):
                for champ in ('id', 'role', 'familles', 'nom', 'quantification', 'detail', 'page', 'url', 'fichier', 'taille',
                              'sha256', 'licence', 'remplit', 'vide', 'reglages', 'edition'):
                    self.assertIn(champ, m)
                self.assertIn(m['role'], serveur.ROLES_MODELES)
                self.assertTrue(m['detail']['fr'] and m['detail']['en'])
                self.assertTrue(m['url'].startswith(m['page'] + '/resolve/main/'), m['url'])
                self.assertTrue(m['page'].startswith('https://huggingface.co/'), m['page'])
                self.assertFalse(any(mot in (m['url'] + m['fichier']).lower() for mot in LiensModelesTest.INTERDITS), m['url'])
                # Le modele d'agrandissement (Real-ESRGAN, 67 Mo) est bien plus petit que les autres
                self.assertGreater(m['taille'], 10_000_000 if m['role'] == 'agrandissement' else 100_000_000)
                if m['sha256'] is not None:
                    self.assertRegex(m['sha256'], r'^[0-9a-f]{64}$')
                self.assertTrue(m['licence']['nom'] and m['licence']['url'].startswith('https://'))
                # Une licence non commerciale est toujours resumee pour l'utilisateur, en francais et en anglais
                if not m['licence']['commercial']:
                    self.assertTrue(m['licence']['resume']['fr'] and m['licence']['resume']['en'])
                self.assertIn(m['edition'], (None, 'reference', 'vision') if m['role'] == 'image' else (None,))
                self.assertTrue(serveur.chemin_relatif_sur(m['fichier']) and '/' not in m['fichier'])
                self.assertTrue(set(m['remplit'] + m['vide']) <= set(serveur.REGLAGES_DEFAUT), m['id'])
                if m['reglages']:
                    self.assertIsNone(serveur.valider_reglages({**BASE, **m['reglages']})[1])
        # Deux fichiers differents ne portent jamais le meme nom dans models/
        fichiers = [m['fichier'] for m in catalogue['modeles']]
        self.assertEqual(len(fichiers), len(set(fichiers)))

    def test_profils(self):
        par_id = {m['id']: m for m in serveur.CATALOGUE['modeles']}
        ids = [p['id'] for p in serveur.PROFILS]
        self.assertEqual(len(ids), len(set(ids)))
        for profil in serveur.PROFILS:
            with self.subTest(profil=profil['id']):
                for champ in ('nom', 'description', 'materiel'):
                    self.assertTrue(profil[champ]['fr'] and profil[champ]['en'], champ)
                self.assertTrue(profil['vitesse']['fr'] and profil['vitesse']['en'])
                self.assertIn(profil['statut'], ('recommande', 'experimental'))
                self.assertIn(profil['categorie'], ('principal', 'option'))
                self.assertIn(profil['cible']['type'], ('pc', 'mac') if profil['categorie'] == 'principal' else ('tous',))
                modeles = [par_id[i] for i in profil['modeles']]
                roles = [m['role'] for m in modeles]
                # Un fichier par role ; la vision (modification d'image) est facultative
                for role in ('image', 'texte', 'vae'):
                    self.assertEqual(roles.count(role), 1, role)
                self.assertLessEqual(roles.count('edition'), 1)
                dessin = next(m for m in modeles if m['role'] == 'image')
                self.assertEqual(profil['edition'], dessin['edition'] == 'reference' or (dessin['edition'] == 'vision' and 'edition' in roles))
                # Les fichiers d'un profil vont ensemble
                self.assertTrue(set.intersection(*(set(m['familles']) for m in modeles)), profil['id'])
                # Les profils principaux n'ont que des licences permissives ; les autres demandent d'accepter la leur
                non_commercial = any(not m['licence']['commercial'] for m in modeles)
                self.assertEqual(profil['licence_a_accepter'], non_commercial)
                if profil['categorie'] == 'principal':
                    self.assertFalse(non_commercial)
                self.assertEqual(profil['taille_totale'], sum(m['taille'] for m in modeles))
                if profil['statut'] == 'recommande':
                    for m in modeles:
                        self.assertTrue(m['url'] and m['sha256'], m['id'])
        # Toujours un profil sans carte graphique, et un profil par taille de Mac
        self.assertTrue(any(p['cible'] == {'type': 'pc', 'video_min': 0, 'memoire_min': 0} for p in serveur.PRINCIPAUX))
        self.assertEqual(len([p for p in serveur.PRINCIPAUX if p['cible']['type'] == 'mac']), 3)
        # Chaque profil principal sait modifier une image
        self.assertTrue(all(p['edition'] for p in serveur.PRINCIPAUX))

    def test_suggestion_selon_la_machine(self):
        go = serveur.GO
        carte = lambda video: {'nom': 'Carte', 'video': video * go}
        cas = [
            ({'mac': False, 'memoire': 8 * go, 'video': 0, 'carte': None}, 'cpu-8go'),
            ({'mac': False, 'memoire': 16 * go, 'video': 0.5 * go, 'carte': carte(0.5)}, 'cpu-8go'),
            ({'mac': False, 'memoire': 16 * go, 'video': 4 * go, 'carte': carte(4)}, 'gpu-4go'),
            ({'mac': False, 'memoire': 16 * go, 'video': 6 * go, 'carte': carte(6)}, 'gpu-4go'),
            ({'mac': False, 'memoire': 32 * go, 'video': 8 * go, 'carte': carte(8)}, 'gpu-8go'),
            ({'mac': False, 'memoire': 16 * go, 'video': 12 * go, 'carte': carte(12)}, 'gpu-8go'),
            ({'mac': False, 'memoire': 32 * go, 'video': 12 * go, 'carte': carte(12)}, 'gpu-12go'),
            ({'mac': False, 'memoire': 64 * go, 'video': 24 * go, 'carte': carte(24)}, 'gpu-16go'),
            ({'mac': False, 'memoire': 0, 'video': 16 * go, 'carte': carte(16)}, 'gpu-16go'),
            # Carte vue mais memoire illisible : l'utilisateur choisit
            ({'mac': False, 'memoire': 32 * go, 'video': 0, 'carte': {'nom': 'Radeon', 'video': 0}}, None),
            ({'mac': False, 'memoire': 8 * go, 'video': 0, 'carte': {'nom': 'Iris', 'video': 0, 'integree': True}}, 'cpu-8go'),
            ({'mac': True, 'memoire': 8 * go, 'video': 8 * go, 'carte': None}, 'mac-8go'),
            ({'mac': True, 'memoire': 18 * go, 'video': 18 * go, 'carte': None}, 'mac-16go'),
            ({'mac': True, 'memoire': 36 * go, 'video': 36 * go, 'carte': None}, 'mac-32go'),
            ({'mac': True, 'memoire': 0, 'video': 0, 'carte': None}, None),
        ]
        principaux = {p['id'] for p in serveur.PRINCIPAUX}
        for machine, attendu in cas:
            with self.subTest(machine=machine):
                suggestion = serveur.suggerer_profil(machine)
                self.assertEqual(suggestion, attendu)
                # Jamais une option a licence non commerciale
                self.assertTrue(suggestion is None or suggestion in principaux)

    def test_profil_deja_telecharge_applique_sans_retelecharger(self):
        from unittest import mock
        serveur.MODELES.mkdir(parents=True, exist_ok=True)
        zimage = [serveur.MODELES_PAR_ID[i] for i in ('klein-q4', 'qwen3-4b-q4', 'klein-vae')]
        serveur.FICHIER_REGLAGES.parent.mkdir(exist_ok=True)
        serveur.FICHIER_REGLAGES.write_text(json.dumps({'modele_vision': 'mmproj.gguf', 'amelioration_vision_locale': 'mmproj.gguf',
                                                        'etapes': 8, 'cfg': 1.0, 'sigmas': serveur.SIGMAS_RAPIDE}), encoding='utf-8')
        fichiers = []
        try:
            for m in zimage:
                chemin = serveur.MODELES / m['fichier']
                with open(chemin, 'wb') as f:
                    f.truncate(m['taille'])
                fichiers.append(chemin)
            with mock.patch.object(serveur, 'telecharger_modele') as telecharger:
                for m in zimage:
                    serveur.demander_modele(m['id'])
                telecharger.assert_not_called()
            r = serveur.lire_reglages()
            self.assertEqual((r['modele_diffusion'], r['modele_texte'], r['vae'], r['amelioration_modele_local']),
                             ('flux-2-klein-4b-Q4_0.gguf', 'Qwen3-4B-Q4_K_M.gguf', 'flux2-vae-small-decoder.safetensors',
                              'Qwen3-4B-Q4_K_M.gguf'))
            # La vision de Qwen3-VL ne va pas avec ce modele de texte, et les sigmas de Qwen-Image non plus
            self.assertEqual((r['modele_vision'], r['amelioration_vision_locale'], r['sigmas'], r['etapes']), ('', '', '', 4))
            # FLUX.2 klein modifie une image sans fichier de vision
            self.assertEqual(serveur.mode_edition(r), 'reference')
            profil = next(p for p in serveur.etat_profils()['profils'] if p['id'] == 'cpu-8go')
            self.assertEqual((profil['taille_restante'], profil['installe'], profil['actif']), (0, True, True))
            self.assertEqual(serveur.telechargements_modeles['klein-q4']['phase'], 'termine')
        finally:
            for chemin in fichiers:
                chemin.unlink(missing_ok=True)
            for m in zimage:
                serveur.telechargements_modeles.pop(m['id'], None)

    def test_arguments_de_modification_selon_le_modele(self):
        sortie, source = Path('sortie.png'), Path('depart.png')
        klein = {**serveur.REGLAGES_DEFAUT, **BASE, 'modele_diffusion': 'flux-2-klein-4b-Q8_0.gguf', 'modele_vision': ''}
        qwen = {**serveur.REGLAGES_DEFAUT, **BASE, 'modele_diffusion': 'Qwen-Image-2.1-Turbo-AD-Q4_K.gguf',
                'modele_vision': 'mmproj-Qwen3VL-8B-Instruct-F16.gguf'}
        zimage = {**serveur.REGLAGES_DEFAUT, **BASE, 'modele_diffusion': 'z_image_turbo-Q4_K.gguf', 'modele_vision': 'mmproj.gguf'}
        self.assertEqual([serveur.mode_edition(x) for x in (klein, qwen, zimage)], ['reference', 'vision', None])
        self.assertEqual(serveur.mode_edition({**qwen, 'modele_vision': ''}), None)
        # Modele personnel : la vision decide
        self.assertEqual(serveur.mode_edition({**klein, 'modele_diffusion': 'mien.gguf', 'modele_vision': 'v.gguf'}), 'vision')
        args = serveur.arguments(klein, 'neige', 512, 512, 1, source, sortie, vision=False)
        self.assertIn('-r', args)
        self.assertNotIn('--llm_vision', args)
        args = serveur.arguments(qwen, 'neige', 512, 512, 1, source, sortie, vision=True)
        self.assertIn('--llm_vision', args)

    def test_modification_sans_vision_message_clair(self):
        import base64
        serveur.etat.clear()
        serveur.etat.update(occupe=True, resultats=[], erreur=None)
        r = {**serveur.REGLAGES_DEFAUT, **BASE, 'modele_vision': ''}
        source = 'data:image/png;base64,' + base64.b64encode(b'\x89PNG').decode()
        serveur.generer({'reglages': r, 'prompt': 'neige', 'largeur': 512, 'hauteur': 512, 'nombre': 1, 'seed': 1,
                         'source_data': source})
        self.assertIn('ne savent pas modifier une image', serveur.etat['erreur'])
        self.assertEqual(serveur.etat['phase'], 'erreur')

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
             'sha256': hashlib.sha256(contenu).hexdigest(), 'remplit': ['modele_diffusion'],
             'reglages': serveur.MODELES_PAR_ID['dessin-q4']['reglages']}
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
            with mock.patch.object(serveur, 'profil_machine', return_value={'profil': profil, 'mac': False, 'suggestion': None}):
                infos = serveur.etat_modeles_conseilles()
            # Chaque role a un modele conseille, sous un nom clair (FLUX.2 klein n'a pas besoin de fichier de vision)
            roles = {m['role'] for m in infos['modeles'] if m['conseille']}
            self.assertEqual(roles, {'Modèle de dessin', 'Modèle de texte', 'VAE'}, profil)
            # Le moteur de texte du bouton Ameliorer est propose dans la meme fenetre
            texte = infos['moteurs']['texte']
            self.assertEqual(texte['nom'], 'llama.cpp')
            self.assertGreater(texte['taille'], 0)
            self.assertIn('installe', texte)


class ArretDesMoteursTest(unittest.TestCase):
    """Les moteurs ne survivent pas a Prisme, et ceux d'une session precedente sont arretes au lancement suivant."""

    def faux_moteur(self, nom='sd-cli'):
        """Un vrai programme qui attend une minute, copie dans le dossier des moteurs de Prisme."""
        import subprocess
        dossier = serveur.RACINE / 'sd'
        dossier.mkdir(parents=True, exist_ok=True)
        if serveur.WINDOWS:
            programme = dossier / f'{nom}.exe'
            shutil.copy(Path(os.environ['SystemRoot']) / 'System32' / 'PING.EXE', programme)
            commande = [str(programme), '-n', '60', '127.0.0.1']
        else:
            programme = dossier / nom
            shutil.copy(shutil.which('sleep'), programme)
            commande = [str(programme), '60']
        moteur = serveur.lancer_moteur(commande, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: moteur.poll() is None and moteur.kill())
        return moteur

    def attendre_fin(self, pid, limite=10):
        import time
        fin = time.time() + limite
        while time.time() < fin and serveur.chemin_processus(pid):
            time.sleep(0.1)
        return serveur.chemin_processus(pid) is None

    def test_orphelins_arretes_au_lancement(self):
        import subprocess
        moteur = self.faux_moteur()
        self.assertIn(str(moteur.pid), serveur.lire_notes_moteurs())
        # Un autre programme note par erreur (ou un PID reutilise) : jamais arrete
        autre = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        self.addCleanup(autre.wait)
        self.addCleanup(autre.kill)
        serveur.noter_moteur(autre.pid, sys.executable)
        arretes = serveur.arreter_moteurs_orphelins()
        self.assertEqual(arretes, [moteur.pid])
        moteur.wait(timeout=10)
        self.assertIsNone(autre.poll())
        self.assertFalse(serveur.FICHIER_MOTEURS.exists())

    @unittest.skipIf(sys.platform == 'darwin', 'macOS : pas de signal a la mort du parent, les orphelins sont arretes au lancement')
    def test_moteurs_arretes_si_prisme_est_tue(self):
        import subprocess
        # Cause C : un Prisme tue pendant une generation laissait son moteur tourner
        programme = Path(DOSSIER_TEST.name) / 'prisme_tue.py'
        programme.write_text(
            'import os, sys, subprocess, time\n'
            f'sys.path.insert(0, {str(Path(serveur.__file__).parent)!r})\n'
            'import serveur, test_moteur\n', encoding='utf-8')
        aide = Path(DOSSIER_TEST.name) / 'test_moteur.py'
        if serveur.WINDOWS:
            ping = str(Path(os.environ['SystemRoot']) / 'System32' / 'PING.EXE')
            corps = f'p = serveur.lancer_moteur([{ping!r}, "-n", "60", "127.0.0.1"], stdout=subprocess.DEVNULL)\n'
        else:
            corps = f'p = serveur.lancer_moteur([{shutil.which("sleep")!r}, "60"])\n'
        aide.write_text('import subprocess, time, serveur\n' + corps + 'print(p.pid, flush=True)\ntime.sleep(60)\n', encoding='utf-8')
        prisme = subprocess.Popen([sys.executable, str(programme)], stdout=subprocess.PIPE, text=True,
                                  env={**os.environ, 'PRISME_RACINE': DOSSIER_TEST.name, 'PYTHONPATH': DOSSIER_TEST.name})
        self.addCleanup(prisme.stdout.close)
        pid = int(prisme.stdout.readline())
        self.assertIsNotNone(serveur.chemin_processus(pid))
        prisme.kill()
        prisme.wait()
        self.assertTrue(self.attendre_fin(pid), 'le moteur a survecu a Prisme')

    def test_arret_de_tout_l_arbre(self):
        moteurs = [self.faux_moteur('sd-cli'), self.faux_moteur('llama-server')]
        if serveur.WINDOWS:
            # arreter() vide l'objet Job : tous les moteurs et ce qu'ils auraient lance
            serveur._noyau.TerminateJobObject(ctypes_pointeur(serveur._job), 1)
        else:
            for moteur in moteurs:
                serveur.tuer_arbre(moteur)
        for moteur in moteurs:
            moteur.wait(timeout=10)

    def test_chemin_d_un_processus(self):
        moteur = self.faux_moteur()
        self.assertEqual(Path(serveur.chemin_processus(moteur.pid)).resolve(), (serveur.RACINE / 'sd').resolve() /
                         Path(serveur.chemin_processus(moteur.pid)).name)
        self.assertIsNone(serveur.chemin_processus(99999999))


def ctypes_pointeur(valeur):
    import ctypes
    return ctypes.c_void_p(valeur)


class InstanceUniqueTest(unittest.TestCase):
    """Un seul Prisme par dossier ; un second lancement ne cree jamais de deuxieme serveur ni de fenetre en trop."""

    def tearDown(self):
        serveur.liberer_instance()

    def test_verrou_pris_une_seule_fois(self):
        self.assertTrue(serveur.prendre_instance())
        # Le meme dossier vu par un autre lancement : refuse (le mutex ou le verrou existe deja)
        poignee = serveur._instance
        serveur._instance = None
        try:
            self.assertFalse(serveur.prendre_instance())
        finally:
            serveur._instance = poignee
        serveur.liberer_instance()
        self.assertTrue(serveur.prendre_instance())

    def test_nom_propre_au_dossier_et_au_port(self):
        from unittest import mock
        nom = serveur.nom_instance()
        with mock.patch.object(serveur, 'PORT', serveur.PORT + 1):
            self.assertNotEqual(serveur.nom_instance(), nom)

    def lancer_main(self, argv, deja_pris=False, port_pris=False):
        from unittest import mock
        with mock.patch.object(serveur.sys, 'argv', ['serveur.py', *argv]), \
                mock.patch.object(serveur, 'prendre_instance', return_value=not deja_pris), \
                mock.patch.object(serveur, 'Serveur', side_effect=OSError if port_pris else AssertionError('serveur lance')), \
                mock.patch.object(serveur, 'ouvrir_fenetre') as fenetre, mock.patch.object(serveur, 'fermer_demarrage'):
            serveur.main()
        return fenetre.called

    def test_second_lancement(self):
        # Avec --sans-fenetre (redemarrage d'une mise a jour) : jamais de fenetre ; sinon, celle du Prisme deja ouvert
        self.assertFalse(self.lancer_main(['--sans-fenetre'], deja_pris=True))
        self.assertTrue(self.lancer_main([], deja_pris=True))

    def test_port_deja_pris(self):
        # Cause B : avant 1.9.4, une fenetre s'ouvrait meme avec --sans-fenetre
        self.assertFalse(self.lancer_main(['--sans-fenetre'], port_pris=True))
        self.assertTrue(self.lancer_main([], port_pris=True))


class ConnexionClaudeTest(unittest.TestCase):
    """Branchement de Prisme dans Claude Desktop, sur une configuration temporaire."""

    def setUp(self):
        self.dossier = Path(tempfile.mkdtemp(dir=DOSSIER_TEST.name)) / 'Claude'
        self.dossier.mkdir()
        self.fichier = self.dossier / 'claude_desktop_config.json'

    def test_ajout_garde_le_reste_et_une_copie(self):
        from unittest import mock
        origine = {'mcpServers': {'autre': {'command': 'x'}}, 'preferences': {'theme': 'dark'}}
        self.fichier.write_text('\ufeff' + json.dumps(origine), encoding='utf-8')
        serveur.connecter_claude_desktop(self.dossier)
        apres = json.loads(self.fichier.read_text(encoding='utf-8'))
        self.assertEqual(apres['mcpServers']['autre'], {'command': 'x'})
        self.assertEqual(apres['preferences'], {'theme': 'dark'})
        self.assertEqual(apres['mcpServers']['prisme'], serveur.commande_mcp())
        self.assertIn('--mcp', apres['mcpServers']['prisme']['args'])
        sauvegarde = self.dossier / 'claude_desktop_config.avant-prisme.json'
        self.assertEqual(json.loads(sauvegarde.read_text(encoding='utf-8-sig')), origine)
        with mock.patch.object(serveur, 'dossiers_claude_desktop', return_value=[self.dossier]), \
                mock.patch.object(serveur.shutil, 'which', return_value=None), \
                mock.patch.object(serveur.Path, 'home', return_value=self.dossier):
            etat = serveur.etat_claude()
        self.assertEqual((etat['desktop'], etat['desktop_connecte'], etat['code']), (True, True, False))
        serveur.connecter_claude_desktop(self.dossier, retirer=True)
        self.assertNotIn('prisme', json.loads(self.fichier.read_text(encoding='utf-8'))['mcpServers'])

    def test_configuration_absente_puis_illisible(self):
        serveur.connecter_claude_desktop(self.dossier)
        self.assertIn('prisme', json.loads(self.fichier.read_text(encoding='utf-8'))['mcpServers'])
        self.fichier.write_text('{pas du json', encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'illisible'):
            serveur.connecter_claude_desktop(self.dossier)
        self.assertEqual(self.fichier.read_text(encoding='utf-8'), '{pas du json')

    def test_configuration_de_claude_recent_sous_windows(self):
        from unittest import mock
        base = self.dossier.parent
        roaming, local = base / 'Roaming', base / 'Local'
        (roaming / 'Claude').mkdir(parents=True)
        env = {'APPDATA': str(roaming), 'LOCALAPPDATA': str(local)}
        with mock.patch.object(serveur, 'WINDOWS', True), mock.patch.object(serveur, 'MAC', False), \
                mock.patch.dict(os.environ, env):
            # Ancienne version : AppData\\Roaming\\Claude
            self.assertEqual(serveur.dossiers_claude_desktop(), [roaming / 'Claude'])
            # Version recente : sa configuration est dans Claude-Data\\claude_<paquet>, l'ancien dossier n'est plus lu
            recent = local / 'Claude-Data' / 'claude_pzs8sxrjxfjjc'
            recent.mkdir(parents=True)
            (recent / 'claude_desktop_config.json').write_text(json.dumps({'preferences': {'x': 1}}), encoding='utf-8')
            self.assertEqual(serveur.dossiers_claude_desktop(), [recent])
            serveur.connecter_claude_desktop(recent)
        apres = json.loads((recent / 'claude_desktop_config.json').read_text(encoding='utf-8'))
        self.assertEqual(apres['preferences'], {'x': 1})
        self.assertIn('prisme', apres['mcpServers'])

    def test_programme_deplace(self):
        from unittest import mock
        self.fichier.write_text(json.dumps({'mcpServers': {'prisme': {'command': 'C:/ancien/Prisme.exe', 'args': ['--mcp']}}}),
                                encoding='utf-8')
        with mock.patch.object(serveur, 'dossiers_claude_desktop', return_value=[self.dossier]), \
                mock.patch.object(serveur.shutil, 'which', return_value=None):
            etat = serveur.etat_claude()
        self.assertEqual((etat['desktop_connecte'], etat['desktop_a_mettre_a_jour']), (False, True))


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


class MemoireEcranTest(unittest.TestCase):
    """Les moteurs laissent de la memoire de carte graphique a l'affichage : sinon l'ecran du PC gele."""

    def reglages(self, **changements):
        return dict(serveur.REGLAGES_DEFAUT, modele_diffusion='d.gguf', modele_texte='t.gguf', vae='v.safetensors',
                    amelioration_modele_local='texte.gguf', **changements)

    def test_reserve_pour_les_images(self):
        from unittest import mock
        self.assertTrue(serveur.REGLAGES_DEFAUT['memoire_ecran'])
        with mock.patch.object(serveur, 'MAC', False):
            args = serveur.arguments(self.reglages(), 'neige', 512, 512, 1, None, Path('s.png'))
            self.assertEqual(args[args.index('--max-vram') + 1], '-1.5')
            sans = serveur.arguments(self.reglages(memoire_ecran=False), 'neige', 512, 512, 1, None, Path('s.png'))
            self.assertNotIn('--max-vram', sans)
        # Sur Mac, la memoire est partagee : rien a reserver
        with mock.patch.object(serveur, 'MAC', True):
            self.assertNotIn('--max-vram', serveur.arguments(self.reglages(), 'neige', 512, 512, 1, None, Path('s.png')))

    def test_moteur_de_texte_garde_une_marge(self):
        from unittest import mock
        commandes = []

        class Arrete:
            def poll(self):
                return 1

        def lancer(commande, **_options):
            commandes.append(commande)
            return Arrete()

        with tempfile.TemporaryDirectory() as d:
            moteur, modele = Path(d) / 'llama-server.exe', Path(d) / 'texte.gguf'
            moteur.write_bytes(b''), modele.write_bytes(b'')
            with mock.patch.object(serveur, 'LLAMA_SERVEUR', moteur), mock.patch.object(serveur, 'MODELES', Path(d)), \
                    mock.patch.object(serveur, 'lancer_moteur', lancer), mock.patch.object(serveur, 'MAC', False):
                for memoire_ecran in (True, False):
                    with self.assertRaises(RuntimeError):
                        with serveur.MoteurTexte(self.reglages(memoire_ecran=memoire_ecran)):
                            pass
        avec, sans = commandes
        # llama.cpp choisit les couches qui tiennent en gardant 1,5 Go ; -ngl 99 annulerait ce calcul
        self.assertNotIn('-ngl', avec)
        self.assertEqual(avec[avec.index('--fit-target') + 1], '1536')
        self.assertEqual(sans[sans.index('-ngl') + 1], '99')


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
        # Une version future est toujours plus recente que celle-ci
        self.assertGreater(serveur.numero_version('99.0'), serveur.numero_version(serveur.VERSION))

    def test_pre_versions(self):
        v = serveur.numero_version
        self.assertEqual(v('2.0'), v('2.0.0'))
        # Une pre-version passe avant la version finale, et apres la version precedente
        self.assertLess(v('v2.0.0-beta.1'), v('2.0.0'))
        self.assertLess(v('2.0.0-beta.1'), v('2.0.0-beta.2'))
        self.assertLess(v('2.0.0-beta.9'), v('2.0.0-beta.10'))
        self.assertGreater(v('2.0.0-beta.1'), v('1.9.4'))
        self.assertLess(v('2.0.0-rc'), v('2.0.0'))
        self.assertEqual(v('pas une version'), (0, 0, 0, 0, 0))

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
        from unittest import mock
        nouveau, cible = Path(DOSSIER_TEST.name) / 'nouveau', Path(DOSSIER_TEST.name) / 'Prisme'
        for windows, mac in ((True, False), (False, True), (False, False)):
            with self.subTest(windows=windows, mac=mac), mock.patch.object(serveur, 'WINDOWS', windows), \
                    mock.patch.object(serveur, 'MAC', mac):
                script = serveur.script_remplacement(nouveau, cible, [4242, 4343], [nouveau], [Path('moteurs') / 'sd'])
                for pid in ('4242', '4343'):
                    self.assertIn(pid, script)
                self.assertIn('--sans-fenetre', script)
                # L'application Qt se relance avec sa fenetre
                with mock.patch.object(serveur, 'OPTION_RELANCE', '--qt'):
                    self.assertIn('--qt', serveur.script_remplacement(nouveau, cible, [4242], [nouveau], []))
                # Cause A : plus jamais de retour silencieux a l'ancienne version apres les essais
                self.assertNotIn('goto lancer', script)
                self.assertIn(str(serveur.FICHIER_ECHEC_MAJ), script)
                self.assertIn(str(serveur.FICHIER_JOURNAL_MAJ), script)
                self.assertIn('sd', script)

    def executer_script(self, verrouiller=False, delai=2):
        """Lance pour de vrai le script de remplacement sur des fichiers temporaires ; la relance ecrit un temoin."""
        import subprocess
        dossier = Path(tempfile.mkdtemp(dir=DOSSIER_TEST.name))
        # Le programme dans son propre dossier : sous Linux et Mac, c'est ce dossier qu'on met en lecture seule
        programme = dossier / 'programme'
        programme.mkdir()
        cible, nouveau, temoin = programme / 'Prisme.exe', dossier / '.prisme-maj-Prisme.exe', dossier / 'relance.txt'
        cible.write_bytes(b'ancien')
        nouveau.write_bytes(b'nouveau')
        serveur.FICHIER_ECHEC_MAJ.unlink(missing_ok=True)
        if serveur.WINDOWS:
            relance = f"Set-Content -LiteralPath '{temoin}' -Value 'relance'"
            script = dossier / 'maj.ps1'
            commande = ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script)]
            encodage = 'utf-8-sig'
        else:
            relance = f"echo relance > '{temoin}'"
            script, commande, encodage = dossier / 'maj.sh', ['/bin/sh', str(dossier / 'maj.sh')], 'utf-8'
        texte = serveur.script_remplacement(nouveau, cible, [99999999], [nouveau], [dossier / 'sd'], essais=2, relance=relance)
        script.write_text(texte, encoding=encodage, newline='')
        verrou = None
        if verrouiller:
            if serveur.WINDOWS:
                verrou = open(cible, 'rb')  # ouvert sans partage de suppression : ni renommage ni remplacement
            else:
                programme.chmod(0o555)  # dossier du programme en lecture seule : mv echoue
        try:
            subprocess.run(commande, capture_output=True, timeout=120)
        finally:
            if verrou:
                verrou.close()
            programme.chmod(0o755)
        return cible, nouveau, temoin, script

    def test_remplacement_reel(self):
        cible, nouveau, temoin, script = self.executer_script()
        self.assertEqual(cible.read_bytes(), b'nouveau')
        self.assertFalse(nouveau.exists())
        self.assertTrue(temoin.exists())
        self.assertFalse(serveur.FICHIER_ECHEC_MAJ.exists())
        self.assertFalse(script.exists())
        self.assertFalse(list(cible.parent.glob('Prisme.exe.ancien*')))
        self.assertFalse(list(cible.parent.parent.glob('Prisme.exe.ancien*')))

    @unittest.skipIf(hasattr(os, 'geteuid') and os.geteuid() == 0, 'root ignore les droits du dossier')
    def test_remplacement_impossible_signale(self):
        cible, nouveau, temoin, script = self.executer_script(verrouiller=True)
        # L'ancienne version reste, est relancee, et le message d'echec attend le lancement suivant
        self.assertEqual(cible.read_bytes(), b'ancien')
        self.assertTrue(temoin.exists())
        self.assertIn('pas pu remplacer', serveur.FICHIER_ECHEC_MAJ.read_text(encoding='utf-8-sig'))
        self.assertIn('echec', serveur.FICHIER_JOURNAL_MAJ.read_text(encoding='utf-8-sig'))
        self.assertFalse(nouveau.exists())

    def test_echec_montre_au_lancement_suivant(self):
        from unittest import mock
        serveur.DONNEES.mkdir(exist_ok=True)
        serveur.FICHIER_ECHEC_MAJ.write_text('Le nouveau programme n\'a pas pu remplacer l\'ancien.', encoding='utf-8')
        self.addCleanup(setattr, serveur, 'echec_maj', None)
        dossier = Path(tempfile.mkdtemp(dir=DOSSIER_TEST.name))
        programme = dossier / 'Prisme.exe'
        programme.write_bytes(b'')
        restes = [dossier / '.prisme-maj-Prisme.exe', dossier / 'Prisme.exe.ancien-20261110']
        for reste in restes:
            reste.write_bytes(b'')
        with mock.patch.object(serveur, 'EXE', True), mock.patch.object(serveur, 'programme_actuel', return_value=programme):
            serveur.reprendre_apres_maj()
        self.assertIn('pas pu remplacer', serveur.echec_maj['message'])
        self.assertEqual(serveur.echec_maj['url'], serveur.PAGE_VERSIONS)
        self.assertFalse(serveur.FICHIER_ECHEC_MAJ.exists())
        self.assertFalse(any(r.exists() for r in restes))
        self.assertTrue(programme.exists())

    def test_mac_depuis_une_copie_temporaire(self):
        from unittest import mock
        serveur.mise_a_jour.clear()
        self.addCleanup(serveur.mise_a_jour.clear)
        reponse = mock.MagicMock()
        reponse.__enter__.return_value = io_json({'tag_name': 'v99.0.0', 'assets': [self.release()['assets'][0]]})
        with mock.patch.object(serveur, 'EXE', True), mock.patch.object(serveur, 'TRANSLOQUE', True), \
                mock.patch.object(serveur.urllib.request, 'urlopen', return_value=reponse):
            serveur.verifier_mise_a_jour()
        etat = serveur.etat_mise_a_jour()
        # Pas de bouton qui echouerait : la raison est donnee tout de suite
        self.assertEqual((etat['auto'], etat['raison']), (False, serveur.DEPLACER_MAC))

    def test_etat_sans_details_internes(self):
        serveur.mise_a_jour.clear()
        self.addCleanup(serveur.mise_a_jour.clear)
        self.assertIsNone(serveur.etat_mise_a_jour())
        version, fichier = serveur.lire_release(self.release())
        serveur.mise_a_jour.update(version=version, url=serveur.PAGE_VERSIONS, fichier=fichier, auto=True)
        self.assertEqual(serveur.etat_mise_a_jour(), {'version': '9.9.9', 'url': serveur.PAGE_VERSIONS, 'auto': True, 'raison': None, 'installation': None})

class ArretAutomatiqueTest(unittest.TestCase):
    def setUp(self):
        self.reglages = {**serveur.REGLAGES_DEFAUT, 'arret_auto_minutes': 30, 'arret_fermeture': True}
        self.sauvegarde = (serveur.dernier_contact, serveur.dernier_contact_local, serveur.fermeture_demandee,
                           dict(serveur.etat))

    def tearDown(self):
        serveur.dernier_contact, serveur.dernier_contact_local, serveur.fermeture_demandee, etat = self.sauvegarde
        serveur.etat.clear()
        serveur.etat.update(etat)

    def situation(self, fermeture_il_y_a=None, contact_local_il_y_a=60, contact_il_y_a=1, occupe=False, fenetre_il_y_a=None):
        maintenant = 10_000.0
        serveur.dernier_contact = maintenant - contact_il_y_a
        serveur.dernier_contact_local = maintenant - contact_local_il_y_a
        serveur.fermeture_demandee = None if fermeture_il_y_a is None else maintenant - fermeture_il_y_a
        serveur.dernier_contact_fenetre = 0.0 if fenetre_il_y_a is None else maintenant - fenetre_il_y_a
        serveur.etat['occupe'] = occupe
        self.addCleanup(setattr, serveur, 'dernier_contact_fenetre', 0.0)
        return serveur.doit_s_arreter(maintenant, self.reglages)

    def test_fenetre_fermee_sans_prevenir(self):
        # Cause D : la page n'a pas pu envoyer /api/fermeture (navigateur ferme d'un coup, plantage)
        self.assertTrue(self.situation(fenetre_il_y_a=serveur.SILENCE_FENETRE + 1))
        # Fenetre reduite : le navigateur ralentit la page, mais elle donne encore des nouvelles chaque minute
        self.assertFalse(self.situation(fenetre_il_y_a=70))
        # Jamais de fenetre (lance par Claude) : seule l'inactivite compte
        self.assertFalse(self.situation())

    def test_fenetre_fermee_puis_delai_ecoule(self):
        self.assertTrue(self.situation(fermeture_il_y_a=serveur.DELAI_FERMETURE + 1))

    def test_attend_le_delai_avant_de_s_arreter(self):
        self.assertFalse(self.situation(fermeture_il_y_a=1))

    def test_fenetre_rouverte_apres_la_fermeture(self):
        self.assertFalse(self.situation(fermeture_il_y_a=serveur.DELAI_FERMETURE + 5, contact_local_il_y_a=2))

    def test_claude_garde_prisme_ouvert(self):
        from unittest import mock
        with mock.patch.object(serveur, 'dernier_contact_mcp', 10_000 - 30):
            self.assertFalse(self.situation(fermeture_il_y_a=serveur.DELAI_FERMETURE + 1))
        with mock.patch.object(serveur, 'dernier_contact_mcp', 10_000 - serveur.DELAI_MCP - 1):
            self.assertTrue(self.situation(fermeture_il_y_a=serveur.DELAI_FERMETURE + 1))

    def test_reglage_desactive(self):
        self.reglages['arret_fermeture'] = False
        self.assertFalse(self.situation(fermeture_il_y_a=60))

    def test_generation_en_cours_jamais_interrompue(self):
        self.assertFalse(self.situation(fermeture_il_y_a=60, occupe=True))
        self.assertFalse(self.situation(contact_il_y_a=10_000, occupe=True))

    def test_telechargement_en_cours_jamais_interrompu(self):
        # Fenetre fermee pendant le telechargement d'un profil, d'un moteur ou d'une mise a jour : Prisme reste ouvert
        for suivi, cle in ((serveur.telechargements_modeles, 'essai'), (serveur.installations, 'image')):
            with self.subTest(suivi=cle):
                suivi[cle] = {'phase': 'telechargement'}
                self.assertFalse(self.situation(fermeture_il_y_a=60))
                self.assertFalse(self.situation(contact_il_y_a=10_000))
                suivi[cle] = {'phase': 'termine'}
                self.assertTrue(self.situation(fermeture_il_y_a=60))
                del suivi[cle]
        serveur.mise_a_jour['installation'] = {'phase': 'telechargement'}
        self.addCleanup(serveur.mise_a_jour.pop, 'installation', None)
        self.assertFalse(self.situation(fermeture_il_y_a=60))

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

    def test_images_de_claude_a_part(self):
        mcp = {'X-Prisme-Client': 'mcp'}
        for dossier in (serveur.IMAGES, serveur.IMAGES_CLAUDE):
            dossier.mkdir(exist_ok=True)
            (dossier / 'image_20990101_000000.png').write_bytes(b'png')
            self.addCleanup((dossier / 'image_20990101_000000.png').unlink)
        nom = '/image_20990101_000000.png'
        # Claude ne lit que son dossier ; la fenetre de Prisme que le sien
        self.assertEqual(self.requete('GET', '/images' + nom, entetes=mcp)[0], 403)
        self.assertEqual(self.requete('GET', '/images-claude' + nom, entetes=mcp)[0], 200)
        self.assertEqual(self.requete('GET', '/images-claude' + nom)[0], 403)
        self.assertEqual(self.requete('GET', '/images' + nom)[0], 200)
        sauvegarde = dict(serveur.etat)
        self.addCleanup(lambda: (serveur.etat.clear(), serveur.etat.update(sauvegarde)))
        for claude, voit_mcp, voit_fenetre in ((False, [], ['a.png']), (True, ['a.png'], [])):
            serveur.etat.update(occupe=False, resultats=['a.png'], prompt='secret', claude=claude)
            pour_mcp = json.loads(self.requete('GET', '/api/etat', entetes=mcp)[2])
            pour_fenetre = json.loads(self.requete('GET', '/api/etat')[2])
            self.assertEqual((pour_mcp['resultats'], pour_fenetre['resultats']), (voit_mcp, voit_fenetre))
            self.assertEqual('prompt' in pour_mcp, claude)

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

    def test_demande_de_claude_acceptee_dans_la_fenetre(self):
        from unittest import mock
        mcp = {'X-Prisme-Client': 'mcp'}
        with mock.patch.object(serveur, 'ouvrir_fenetre'), mock.patch.object(serveur, 'demander_modele') as demander:
            statut, _, corps = self.poster('/api/demander-telechargement', json.dumps({'profil': 'qwen-12go'}), mcp)
            self.assertEqual(statut, 200)
            demande = json.loads(corps)
            self.assertEqual(demande['details']['licence']['nom'], 'Qwen Research License')
            # Un profil sous licence permissive n'a rien a accepter
            self.assertEqual(self.poster('/api/demander-telechargement', json.dumps({'profil': 'gpu-8go'}), mcp)[0], 400)
            # La fenetre voit la demande ; le serveur MCP ne peut pas y repondre lui-meme
            etat = json.loads(self.requete('GET', '/api/etat')[2])
            self.assertEqual([c['id'] for c in etat['consentements']], [demande['id']])
            corps_reponse = json.dumps({'id': demande['id'], 'accepter': True})
            self.assertEqual(self.poster('/api/repondre-consentement', corps_reponse, mcp)[0], 403)
            demander.assert_not_called()
            self.assertEqual(json.loads(self.requete('GET', f'/api/consentement?id={demande["id"]}', entetes=mcp)[2])['etat'], 'attente')
            self.assertEqual(self.poster('/api/repondre-consentement', corps_reponse)[0], 200)
            self.assertEqual(json.loads(self.requete('GET', f'/api/consentement?id={demande["id"]}')[2])['etat'], 'acceptee')
            self.assertEqual([c.args[0] for c in demander.call_args_list], ['dessin-q4', 'texte-q8', 'vision-f16', 'vae'])
            # Deja traitee, et rien depuis un autre appareil
            self.assertEqual(self.poster('/api/repondre-consentement', corps_reponse)[0], 404)
            self.assertEqual(self.distant('/api/consentement?id=x', serveur.CODE)[0], 403)

    def test_modele_hors_catalogue(self):
        from unittest import mock
        url = 'https://huggingface.co/organisation/modele/resolve/main/mien-Q4.gguf'
        with mock.patch.object(serveur, 'ouvrir_fenetre'), mock.patch.object(serveur, 'demander_modele') as demander, \
                mock.patch.object(serveur, 'infos_fichier_distant', return_value=(3 * 10 ** 9, 'a' * 64)):
            for mauvais, motif in (({'url': 'http://exemple.com/x.gguf'}, 'https'), ({'url': 'https://exemple.com/x.exe'}, '.gguf'),
                                   ({'url': url, 'role': 'musique'}, 'Rôle')):
                statut, _, corps = self.poster('/api/demander-telechargement', json.dumps(mauvais))
                self.assertEqual(statut, 400, mauvais)
                self.assertIn(motif, json.loads(corps)['erreur'])
            statut, _, corps = self.poster('/api/demander-telechargement', json.dumps({'url': url, 'role': 'texte'}))
            self.assertEqual(statut, 200)
            demande = json.loads(corps)
            self.assertEqual(demande['details'], {'url': url, 'hote': 'huggingface.co', 'fichier': 'mien-Q4.gguf',
                                                  'taille': 3 * 10 ** 9, 'sha256': 'a' * 64, 'role': 'texte'})
            self.assertEqual(self.poster('/api/repondre-consentement', json.dumps({'id': demande['id'], 'accepter': True}))[0], 200)
            ident = demander.call_args.args[0]
            modele = serveur.trouver_modele(ident)
            self.assertEqual((modele['fichier'], modele['remplit'], modele['sha256']), ('mien-Q4.gguf', ['modele_texte'], 'a' * 64))
            # Un LoRA va dans models/loras
            statut, _, corps = self.poster('/api/demander-telechargement', json.dumps({'url': url.replace('mien-Q4.gguf', 'style.safetensors'), 'role': 'lora'}))
            self.assertEqual(json.loads(corps)['details']['fichier'], 'loras/style.safetensors')
            # Refus : rien n'est telecharge
            demander.reset_mock()
            self.assertEqual(self.poster('/api/repondre-consentement', json.dumps({'id': json.loads(corps)['id'], 'accepter': False}))[0], 200)
            demander.assert_not_called()

    def test_connexion_a_claude_seulement_depuis_la_fenetre(self):
        from unittest import mock
        self.assertEqual(self.poster('/api/connecter-claude', '{}', {'X-Prisme-Client': 'mcp'})[0], 403)
        # Mac, app lancee depuis Telechargements : pas de chemin temporaire dans la configuration de Claude
        from unittest import mock
        with mock.patch.object(serveur, 'TRANSLOQUE', True):
            statut, _, corps = self.poster('/api/connecter-claude', '{}')
        self.assertEqual((statut, json.loads(corps)['erreur']), (409, serveur.DEPLACER_MAC))
        self.assertEqual(self.distant('/api/claude', serveur.CODE)[0], 403)
        with mock.patch.object(serveur, 'dossiers_claude_desktop', return_value=[]), mock.patch.object(serveur.shutil, 'which', return_value=None):
            self.assertEqual(self.poster('/api/connecter-claude', '{}')[0], 404)
            statut, _, corps = self.requete('GET', '/api/claude')
        self.assertEqual(statut, 200)
        self.assertEqual(json.loads(corps)['desktop'], False)

    def test_licence_non_commerciale_a_accepter(self):
        from unittest import mock
        with mock.patch.object(serveur, 'demander_modele') as demander:
            statut, _, corps = self.poster('/api/telecharger-modele', json.dumps({'id': 'dessin-q4'}))
            self.assertEqual(statut, 400)
            self.assertIn('Accepte d\'abord la licence', json.loads(corps)['erreur'])
            self.assertEqual(self.poster('/api/telecharger-modele', json.dumps({'id': 'dessin-q4', 'licence_acceptee': 'oui'}))[0], 400)
            demander.assert_not_called()
            self.assertEqual(self.poster('/api/telecharger-modele', json.dumps({'id': 'dessin-q4', 'licence_acceptee': True}))[0], 200)
            # Licence permissive : rien a accepter
            self.assertEqual(self.poster('/api/telecharger-modele', json.dumps({'id': 'klein-q4'}))[0], 200)
            self.assertEqual([c.args[0] for c in demander.call_args_list], ['dessin-q4', 'klein-q4'])

    def test_modele_d_une_seule_creation_verifie(self):
        for modele in ('../app/code-acces.txt', 'C:/x.gguf', 'absent.gguf'):
            with self.subTest(modele=modele):
                corps = json.dumps({'prompt': 'un chat', 'modele': modele})
                statut, _, reponse = self.poster('/api/generer', corps)
                self.assertEqual(statut, 400)
                self.assertIn('Modèle introuvable', json.loads(reponse)['erreur'])

    def test_profils_en_lecture_seule_sur_le_pc(self):
        statut, _, corps = self.requete('GET', '/api/profils')
        self.assertEqual(statut, 200)
        infos = json.loads(corps)
        self.assertEqual({p['id'] for p in infos['profils']}, {p['id'] for p in serveur.PROFILS})
        self.assertIn('suggestion', infos)
        self.assertIn(infos['conseille'], {p['id'] for p in serveur.PROFILS})
        self.assertGreater(infos['libre'], 0)
        premier = infos['profils'][0]['modeles'][0]
        self.assertTrue(premier['url'].startswith('https://huggingface.co/') and 'present' in premier)
        # La configuration de la machine ne sort pas du PC
        self.assertEqual(self.distant('/api/profils', serveur.CODE)[0], 403)
        self.assertEqual(self.poster('/api/profils')[0], 404)

    def test_installation_de_moteur(self):
        self.assertEqual(self.poster('/api/installer-moteur', json.dumps({'moteur': 'inconnu'}))[0], 400)
        self.assertEqual(self.distant('/api/installer-moteur', serveur.CODE, 'POST')[0], 403)
        # La mise a jour ne se lance que depuis le PC, et seulement quand une version automatique existe
        self.assertEqual(self.distant('/api/mettre-a-jour', serveur.CODE, 'POST')[0], 403)
        self.assertEqual(self.distant('/api/verifier-mise-a-jour', serveur.CODE, 'POST')[0], 403)
        serveur.mise_a_jour.clear()
        self.assertEqual(self.poster('/api/mettre-a-jour')[0], 400)
        etat = json.loads(self.requete('GET', '/api/etat')[2])
        self.assertEqual(set(etat['moteurs']), {'image', 'texte'})

    def test_verifier_mise_a_jour_a_la_demande(self):
        from unittest import mock
        import io
        serveur.mise_a_jour.clear()
        self.addCleanup(serveur.mise_a_jour.clear)
        # GitHub ne repond pas : une erreur claire au lieu du silence du lancement
        with mock.patch.object(serveur.urllib.request, 'urlopen', side_effect=OSError('hors ligne')):
            code, _, corps = self.poster('/api/verifier-mise-a-jour')
        self.assertEqual(code, 502)
        self.assertIn('GitHub', json.loads(corps)['erreur'])
        # Deja a jour, puis nouvelle version
        for tag, attendu in ((f'v{serveur.VERSION}', None), ('v99.0.0', '99.0.0')):
            reponse = io.BytesIO(json.dumps({'tag_name': tag, 'assets': []}).encode())
            with mock.patch.object(serveur.urllib.request, 'urlopen', return_value=reponse):
                code, _, corps = self.poster('/api/verifier-mise-a-jour')
            self.assertEqual(code, 200)
            r = json.loads(corps)
            self.assertEqual((r['version'], (r['mise_a_jour'] or {}).get('version')), (serveur.VERSION, attendu))

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

    def test_prisme_relance_montre_sa_fenetre(self):
        from unittest import mock
        montrees = []
        # Fenetre Qt chargee : elle reapparait ; Claude et le telephone ne peuvent pas la faire apparaitre
        with mock.patch.object(serveur, 'MONTRER_FENETRE', lambda: montrees.append(1)):
            self.assertEqual(self.poster('/api/montrer-fenetre')[0], 200)
            self.assertEqual(self.poster('/api/montrer-fenetre', '{}', {'X-Prisme-Client': 'mcp'})[0], 403)
            self.assertEqual(self.distant('/api/montrer-fenetre', serveur.CODE, 'POST')[0], 403)
        self.assertEqual(montrees, [1])
        # Fenetre Qt encore en chargement (relance apres une mise a jour) : elle apparaitra des qu'elle sera prete
        with mock.patch.object(serveur, 'FENETRE', 'qt-chargement'), mock.patch.object(serveur, 'MONTRER_A_LA_FIN', False), \
                mock.patch.object(serveur, 'ouvrir_fenetre') as ouvrir, mock.patch.object(serveur, 'MONTRER_FENETRE', None), \
                mock.patch.object(serveur, 'OPTION_RELANCE', '--sans-fenetre'):
            self.assertEqual(self.poster('/api/montrer-fenetre')[0], 200)
            ouvrir.assert_not_called()
            serveur.quand_prete(lambda: montrees.append(2))
            self.assertEqual((serveur.FENETRE, montrees[-1]), ('qt', 2))
        # Sans fenetre Qt, une fenetre web s'ouvre
        with mock.patch.object(serveur, 'ouvrir_fenetre') as ouvrir:
            self.assertEqual(self.poster('/api/montrer-fenetre')[0], 200)
        ouvrir.assert_called_once()

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

    def test_reglages_changes_pendant_la_fenetre(self):
        serveur.ecrire_reglages({**serveur.REGLAGES_DEFAUT, **BASE})
        self.addCleanup(serveur.FICHIER_REGLAGES.unlink, missing_ok=True)
        version = json.loads(self.requete('GET', '/api/reglages')[2])['version']
        # Un telechargement choisit un autre modele pendant que la fenetre Reglages est ouverte
        time.sleep(0.01)
        serveur.ecrire_reglages({**serveur.REGLAGES_DEFAUT, **BASE, 'modele_diffusion': 'nouveau.gguf'})
        code, _, corps = self.poster('/api/reglages', json.dumps({**BASE, 'version': version}))
        self.assertEqual(code, 409)
        self.assertEqual(serveur.lire_reglages()['modele_diffusion'], 'nouveau.gguf')
        # Rouverte, elle enregistre normalement ; l'ecriture ne laisse pas de fichier provisoire
        version = json.loads(self.requete('GET', '/api/reglages')[2])['version']
        self.assertEqual(self.poster('/api/reglages', json.dumps({**BASE, 'etapes': 9, 'version': version}))[0], 200)
        self.assertEqual(serveur.lire_reglages()['etapes'], 9)
        self.assertEqual(list(serveur.DONNEES.glob('*.provisoire')), [])

    def test_erreur_imprevue_recoit_une_reponse(self):
        from unittest import mock
        # Une image supprimee dans le Finder pendant que Prisme liste la galerie
        with mock.patch.object(serveur, 'lister_images', side_effect=FileNotFoundError('image disparue')):
            code, _, corps = self.requete('GET', '/api/images')
        self.assertEqual(code, 500)
        self.assertIn('image disparue', json.loads(corps)['erreur'])

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
