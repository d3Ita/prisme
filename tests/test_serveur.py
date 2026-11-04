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
                    serveur.extraire_zip(archive, self.dossier / 'sortie')

    def test_extraction_retire_le_dossier_racine_commun(self):
        archive = self.dossier / 'paquet.zip'
        creer_zip(archive, {'paquet/outil.exe': b'ok', 'paquet/lib/a.dll': b'a'})
        serveur.extraire_zip(archive, self.dossier / 'sortie')
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
        for nom, moteur in self.moteurs.items():
            for archive in moteur['archives']:
                with self.subTest(moteur=nom, url=archive['url']):
                    self.assertTrue(archive['url'].startswith('https://github.com/'))
                    self.assertRegex(archive['sha256'], r'^[0-9a-f]{64}$')


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
        etat = json.loads(self.requete('GET', '/api/etat')[2])
        self.assertEqual(set(etat['moteurs']), {'image', 'texte'})

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
