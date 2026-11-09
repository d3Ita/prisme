"""Tests du serveur MCP integre (app/mcp_prisme.py) contre un faux Prisme : sans carte graphique, sans modele, sans paquet.

Lancement : py -3 -m unittest discover -s tests -v
"""

import base64
import json
import socket
import struct
import tempfile
import threading
import unittest
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'app'))

import mcp_prisme as prisme_client  # noqa: E402
from mcp_prisme import Prisme, PrismeErreur  # noqa: E402


def png(largeur=8, hauteur=8):
    """Petit PNG valide."""
    def bloc(genre, donnees):
        return struct.pack('>I', len(donnees)) + genre + donnees + struct.pack('>I', zlib.crc32(genre + donnees))
    lignes = b''.join(b'\x00' + b'\x80' * largeur * 3 for _ in range(hauteur))
    return (b'\x89PNG\r\n\x1a\n' + bloc(b'IHDR', struct.pack('>IIBBBBB', largeur, hauteur, 8, 2, 0, 0, 0))
            + bloc(b'IDAT', zlib.compress(lignes)) + bloc(b'IEND', b''))


def jpeg_en_tete(largeur, hauteur):
    """Debut de JPEG avec un segment SOF0, suffisant pour lire les dimensions."""
    app0 = b'\xff\xe0' + struct.pack('>H', 16) + b'JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00'
    sof = b'\xff\xc0' + struct.pack('>HBHHB', 11, 8, hauteur, largeur, 1) + b'\x01\x11\x00'
    return b'\xff\xd8' + app0 + sof + b'\xff\xd9'


def png_filtre(largeur, hauteur, pixels):
    """PNG RVB dont chaque ligne utilise un filtre different (0 a 4), comme ceux des encodeurs reels."""
    def bloc(genre, donnees):
        return struct.pack('>I', len(donnees)) + genre + donnees + struct.pack('>I', zlib.crc32(genre + donnees))
    pas, bpp, brut, precedente = largeur * 3, 3, b'', bytes(largeur * 3)
    for y in range(hauteur):
        ligne, filtre = pixels[y * pas:(y + 1) * pas], y % 5
        sortie = bytearray(pas)
        for x in range(pas):
            a = ligne[x - bpp] if x >= bpp else 0
            b = precedente[x]
            c = precedente[x - bpp] if x >= bpp else 0
            p = a + b - c
            paeth = a if abs(p - a) <= abs(p - b) and abs(p - a) <= abs(p - c) else b if abs(p - b) <= abs(p - c) else c
            prediction = (0, a, b, (a + b) >> 1, paeth)[filtre]
            sortie[x] = (ligne[x] - prediction) & 255
        brut += bytes([filtre]) + bytes(sortie)
        precedente = ligne
    return (b'\x89PNG\r\n\x1a\n' + bloc(b'IHDR', struct.pack('>IIBBBBB', largeur, hauteur, 8, 2, 0, 0, 0))
            + bloc(b'IDAT', zlib.compress(brut)) + bloc(b'IEND', b''))


class FauxPrisme:
    """Imite l'API de Prisme : une creation dure `etapes` lectures de /api/etat."""

    def __init__(self):
        self.etat = {'occupe': False, 'phase': None, 'problemes': [], 'version': '1.8.5', 'modele': 'dessin.gguf',
                     'moteurs': {'image': {'installe': True, 'nom': 'stable-diffusion.cpp', 'version': 'm1', 'taille': 10},
                                 'texte': {'installe': False, 'nom': 'llama.cpp', 'version': 'b1', 'taille': 290_000_000,
                                           'requiert': 'image', 'installation': None}},
                     'telechargements': [], 'consentements': []}
        # Reponses successives de /api/consentement, et requetes POST recues (chemin, corps, en-tete X-Prisme-Client)
        self.accords, self.posts = ['attente', 'acceptee'], []
        self.reglages = {'modele_diffusion': 'dessin.gguf', 'modele_texte': 'texte.gguf', 'modele_vision': 'vision.gguf',
                         'vae': 'vae.safetensors'}
        self.fichiers = ['dessin.gguf', 'texte.gguf', 'vision.gguf', 'vae.safetensors', 'autre.gguf']
        self.etapes, self.lectures, self.recu, self.erreur, self.edition = 2, 0, [], None, True
        self.image = png(16, 16)
        faux = self

        class Gestionnaire(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def envoyer(self, code, corps, genre='application/json'):
                donnees = corps if isinstance(corps, bytes) else json.dumps(corps).encode()
                self.send_response(code)
                self.send_header('Content-Type', genre)
                self.send_header('Content-Length', str(len(donnees)))
                self.end_headers()
                self.wfile.write(donnees)

            def do_GET(self):
                if self.path == '/api/etat':
                    if faux.etat['occupe']:
                        faux.lectures += 1
                        faux.etat['etape'] = faux.lectures
                        if faux.lectures >= faux.etapes:
                            faux.etat.update(occupe=False, phase='erreur' if faux.erreur else 'termine', erreur=faux.erreur,
                                             resultats=[] if faux.erreur else ['image_20261108_120000.png'])
                    return self.envoyer(200, faux.etat)
                if self.path == '/api/reglages':
                    return self.envoyer(200, {'reglages': faux.reglages, 'edition_possible': faux.edition,
                                              'modeles': faux.fichiers, 'dossier': '/prisme/models',
                                              'loras': [{'nom': 'style.safetensors', 'taille': 1}]})
                if self.path == '/api/profils':
                    profil = {'id': 'gpu-8go', 'nom': {'fr': 'Carte de 8 Go', 'en': '8 GB card'},
                              'materiel': {'fr': '8 Go', 'en': '8 GB'}, 'taille_totale': 10657278128,
                              'taille_restante': 10657278128, 'statut': 'recommande', 'edition': True, 'installe': False,
                              'actif': False, 'vitesse': {'fr': 'Non mesurée', 'en': 'Not measured', 'mesuree': False},
                              'categorie': 'principal', 'licence_a_accepter': False,
                              'modeles': [{'id': 'klein-q8', 'fichier': 'flux-2-klein-4b-Q8_0.gguf'},
                                          {'id': 'klein-vae', 'fichier': 'flux2-vae.safetensors'}]}
                    qwen = {**profil, 'id': 'qwen-12go', 'nom': {'fr': 'Qwen-Image · 12 Go', 'en': 'Qwen-Image · 12 GB'},
                            'categorie': 'option', 'licence_a_accepter': True, 'modeles': [{'id': 'dessin-q4', 'fichier': 'q.gguf'}]}
                    return self.envoyer(200, {'profils': [profil, qwen], 'suggestion': 'gpu-8go', 'conseille': 'gpu-8go',
                                              'libre': 50 * 10 ** 9, 'machine': {}})
                if self.path.startswith('/api/consentement?id='):
                    return self.envoyer(200, {'etat': faux.accords.pop(0) if len(faux.accords) > 1 else faux.accords[0],
                                              'telechargements': []})
                if self.path == '/images/image_20261108_120000.png':
                    return self.envoyer(200, faux.image, 'image/png')
                self.envoyer(404, {'erreur': 'Introuvable'})

            def do_POST(self):
                corps = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                faux.posts.append((self.path, corps, self.headers.get('X-Prisme-Client')))
                if self.path in ('/api/telecharger-modele', '/api/installer-moteur'):
                    return self.envoyer(200, {})
                if self.path == '/api/demander-telechargement':
                    if corps.get('profil'):
                        details = {'profil': corps['profil'], 'nom': {'fr': 'Qwen', 'en': 'Qwen'}, 'taille': 10 ** 9,
                                   'licence': {'nom': 'Qwen Research License', 'url': 'https://x', 'resume': {'fr': 'r', 'en': 'r'}}}
                    else:
                        details = {'url': corps['url'], 'hote': 'huggingface.co', 'fichier': 'mien.gguf', 'taille': 2 * 10 ** 9,
                                   'sha256': None, 'role': corps.get('role')}
                    return self.envoyer(200, {'id': 'demande-1', 'details': details, 'expire': 600})
                if self.path != '/api/generer':
                    return self.envoyer(404, {'erreur': 'Introuvable'})
                if faux.etat['occupe']:
                    return self.envoyer(409, {'erreur': 'Une génération est déjà en cours.'})
                faux.recu.append(corps)
                faux.lectures = 0
                faux.etat.update(occupe=True, phase='chargement', etape=0, total=8, debut=1762600000.5, seed_base=corps.get('seed') or 7,
                                 largeur=corps['largeur'], hauteur=corps['hauteur'], prompt=corps['prompt'], resultats=[], erreur=None)
                self.envoyer(200, {'seed': faux.etat['seed_base']})

        self.serveur = ThreadingHTTPServer(('127.0.0.1', 0), Gestionnaire)
        self.url = f'http://127.0.0.1:{self.serveur.server_address[1]}'
        threading.Thread(target=self.serveur.serve_forever, daemon=True).start()

    def fermer(self):
        self.serveur.shutdown()
        self.serveur.server_close()


class OutilsMcpTest(unittest.TestCase):
    def setUp(self):
        self.faux = FauxPrisme()
        self.addCleanup(self.faux.fermer)
        dossier = tempfile.TemporaryDirectory(prefix='prisme_mcp_', ignore_cleanup_errors=True)
        self.addCleanup(dossier.cleanup)
        self.dossier = Path(dossier.name)
        self.prisme = Prisme(self.faux.url, delai=10, dossier=self.dossier, pause=0.01)

    def test_creation_enregistre_l_image(self):
        resultat = self.prisme.generer('un renard dans la neige', 512, 768, seed=42)
        self.assertEqual(resultat['status'], 'done')
        self.assertEqual((resultat['seed'], resultat['width'], resultat['height']), (42, 512, 768))
        chemin = Path(resultat['images'][0]['path'])
        self.assertEqual(chemin.parent, self.dossier)
        self.assertEqual(chemin.read_bytes(), self.faux.image)
        self.assertEqual(self.faux.recu[0], {'prompt': 'un renard dans la neige', 'largeur': 512, 'hauteur': 768,
                                             'nombre': 1, 'seed': 42})
        texte = json.loads(prisme_client.resume(resultat))
        self.assertEqual(texte['files'], [str(chemin)])

    def test_modele_choisi_pour_une_creation(self):
        self.prisme.generer('un chat', model='autre.gguf')
        self.assertEqual(self.faux.recu[0]['modele'], 'autre.gguf')
        with self.assertRaisesRegex(PrismeErreur, 'not in Prisme\'s models folder'):
            self.prisme.generer('un chat', model='inconnu.gguf')

    def test_entrees_verifiees(self):
        for arguments, motif in (({'prompt': '  '}, 'empty'), ({'prompt': 'x' * 5000}, 'too long'),
                                 ({'prompt': 'chat', 'width': 1000}, 'multiple of 16'),
                                 ({'prompt': 'chat', 'height': 4096}, 'between 256 and 2048'),
                                 ({'prompt': 'chat', 'width': '512'}, 'whole number'),
                                 ({'prompt': 'chat', 'seed': -1}, 'seed')):
            with self.subTest(arguments=arguments), self.assertRaisesRegex(PrismeErreur, motif):
                self.prisme.generer(**arguments)
        self.assertEqual(self.faux.recu, [])

    def test_trop_long_rend_un_identifiant_de_tache(self):
        self.faux.etapes = 10 ** 6
        self.prisme.delai = 0.05
        en_cours = self.prisme.generer('un phare')
        self.assertEqual(en_cours['status'], 'running')
        self.assertEqual(en_cours['task_id'], '1762600000500')
        self.assertIn('get_status', en_cours['message'])
        self.assertEqual(self.prisme.suivre(en_cours['task_id'])['status'], 'running')
        self.faux.etapes = 0
        fini = self.prisme.suivre(en_cours['task_id'])
        self.assertEqual(fini['status'], 'done')
        self.assertTrue(Path(fini['images'][0]['path']).is_file())
        with self.assertRaisesRegex(PrismeErreur, 'not Prisme\'s latest'):
            self.prisme.suivre('123')

    def test_prisme_occupe(self):
        self.faux.etat.update(occupe=True, debut=1.0)
        self.faux.etapes = 10 ** 6
        with self.assertRaisesRegex(PrismeErreur, 'busy'):
            self.prisme.generer('un chat')

    def test_erreur_de_creation(self):
        self.faux.erreur = 'out of memory'
        with self.assertRaisesRegex(PrismeErreur, 'could not create the image: out of memory'):
            self.prisme.generer('un chat')

    def test_aucun_modele_installe_indique_le_profil(self):
        self.faux.etat['problemes'] = ['Modèle de dessin : aucun fichier choisi dans les Réglages']
        with self.assertRaises(PrismeErreur) as erreur:
            self.prisme.generer('un chat')
        message = str(erreur.exception)
        self.assertIn('not ready', message)
        self.assertIn('8 GB card', message)
        self.assertIn('Download this profile', message)
        self.assertNotIn('Traceback', message)

    def test_prisme_arrete(self):
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            port = s.getsockname()[1]
        with self.assertRaisesRegex(PrismeErreur, 'not running'):
            Prisme(f'http://127.0.0.1:{port}', dossier=self.dossier).statut()

    def test_modification_dans_le_dossier_autorise(self):
        source = self.dossier / 'depart.png'
        source.write_bytes(png(1600, 900))
        resultat = self.prisme.modifier('depart.png', 'ajoute de la neige')
        self.assertEqual(resultat['status'], 'done')
        envoye = self.faux.recu[0]
        self.assertEqual((envoye['largeur'], envoye['hauteur'], envoye['prompt']), (1024, 576, 'ajoute de la neige'))
        self.assertEqual(base64.b64decode(envoye['source_data'].split(',', 1)[1]), source.read_bytes())

    def test_modification_hors_du_dossier_refusee(self):
        dehors = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        dehors.write(png())
        dehors.close()
        self.addCleanup(Path(dehors.name).unlink)
        for chemin in (dehors.name, '../' + Path(dehors.name).name, str(self.dossier / '..' / 'x.png')):
            with self.subTest(chemin=chemin), self.assertRaisesRegex(PrismeErreur, 'only images inside'):
                self.prisme.modifier(chemin, 'neige')
        (self.dossier / 'note.txt').write_text('pas une image')
        with self.assertRaisesRegex(PrismeErreur, 'Only PNG and JPEG'):
            self.prisme.modifier('note.txt', 'neige')
        self.assertEqual(self.faux.recu, [])

    def test_modification_sans_vision(self):
        self.faux.reglages['modele_vision'] = ''
        self.faux.edition = False
        (self.dossier / 'depart.png').write_bytes(png())
        with self.assertRaisesRegex(PrismeErreur, 'cannot edit images'):
            self.prisme.modifier('depart.png', 'neige')

    def test_listes_et_statut(self):
        modeles = self.prisme.modeles()
        self.assertEqual(modeles['selected']['drawing_model'], 'dessin.gguf')
        self.assertTrue(modeles['can_edit_images'])
        self.assertEqual(modeles['loras'], ['style.safetensors'])
        profils = self.prisme.liste_profils()
        self.assertEqual(profils['suggested_profile'], 'gpu-8go')
        self.assertEqual(profils['profiles'][0]['download_size_gb'], 10.7)
        statut = self.prisme.statut()
        self.assertEqual((statut['version'], statut['busy'], statut['problems']), ('1.8.5', False, []))

    def test_configuration(self):
        c = prisme_client.configuration({'PRISME_TIMEOUT': '30', 'PRISME_OUTPUT_DIR': str(self.dossier)})
        self.assertEqual((c['url'], c['delai'], c['dossier']), ('http://127.0.0.1:7861', 30.0, self.dossier))
        # Par défaut, répondre avant les 60 s après lesquelles Claude abandonne
        self.assertLess(prisme_client.configuration({})['delai'], 60)
        for environ, motif in (({'PRISME_URL': 'http://exemple.com:7861'}, 'this computer'),
                               ({'PRISME_URL': 'ftp://127.0.0.1'}, 'not a valid'),
                               ({'PRISME_TIMEOUT': 'longtemps'}, 'number'), ({'PRISME_TIMEOUT': '0'}, 'between')):
            with self.subTest(environ=environ), self.assertRaisesRegex(PrismeErreur, motif):
                prisme_client.configuration(environ)

    def test_dimensions_et_proportions(self):
        self.assertEqual(prisme_client.dimensions_image(png(300, 200)), (300, 200))
        self.assertEqual(prisme_client.dimensions_image(jpeg_en_tete(640, 480)), (640, 480))
        self.assertEqual(prisme_client.dimensions_image(b'pas une image'), (0, 0))
        self.assertEqual(prisme_client.taille_de_sortie(640, 480), (1024, 768))
        self.assertEqual(prisme_client.taille_de_sortie(4000, 100), (1024, 256))
        self.assertEqual(prisme_client.taille_de_sortie(0, 0), (1024, 1024))

    def test_installation_du_moteur_et_d_un_profil(self):
        self.assertEqual(self.prisme.installer_moteur('image')['status'], 'installed')
        self.assertEqual(self.prisme.installer_moteur('text')['status'], 'installing')
        with self.assertRaisesRegex(PrismeErreur, 'image" or "text'):
            self.prisme.installer_moteur('video')
        self.faux.posts.clear()
        resultat = self.prisme.telecharger_profil('gpu-8go')
        self.assertEqual(resultat['status'], 'downloading')
        # Licence permissive : les fichiers partent directement, et le moteur de texte manquant aussi
        self.assertEqual([(c, b) for c, b, _ in self.faux.posts],
                         [('/api/telecharger-modele', {'id': 'klein-q8'}), ('/api/telecharger-modele', {'id': 'klein-vae'}),
                          ('/api/installer-moteur', {'moteur': 'texte'})])
        self.assertTrue(all(client == 'mcp' for _, _, client in self.faux.posts))
        with self.assertRaisesRegex(PrismeErreur, 'Unknown profile'):
            self.prisme.telecharger_profil('inconnu')

    def test_licence_non_commerciale_acceptee_dans_la_fenetre(self):
        resultat = self.prisme.telecharger_profil('qwen-12go')
        self.assertEqual((resultat['status'], resultat['approved_by_user']), ('downloading', True))
        # Claude demande seulement : aucun telechargement direct, et jamais de reponse a la place de l'utilisateur
        chemins = [c for c, _, _ in self.faux.posts]
        self.assertEqual(chemins, ['/api/demander-telechargement'])

    def test_licence_refusee_ou_sans_reponse(self):
        self.faux.accords = ['refusee']
        with self.assertRaisesRegex(PrismeErreur, 'refused'):
            self.prisme.telecharger_profil('qwen-12go')
        self.faux.accords = ['attente']
        self.prisme.delai = 0.05
        resultat = self.prisme.telecharger_profil('qwen-12go')
        self.assertEqual((resultat['status'], resultat['request_id']), ('waiting_for_user_approval', 'demande-1'))
        self.assertIn('Prisme', resultat['message'])

    def test_modele_hors_catalogue_avec_avertissement(self):
        resultat = self.prisme.telecharger_externe('https://huggingface.co/a/b/resolve/main/mien.gguf', 'text')
        self.assertEqual(resultat['status'], 'downloading')
        self.assertIn('not checked by Prisme', resultat['message'])
        self.assertEqual(self.faux.posts[0][1], {'url': 'https://huggingface.co/a/b/resolve/main/mien.gguf', 'role': 'texte'})
        with self.assertRaisesRegex(PrismeErreur, 'use_as'):
            self.prisme.telecharger_externe('https://x/y.gguf', 'musique')

    def test_statut_avec_moteurs_et_telechargements(self):
        self.faux.etat['telechargements'] = [{'fichier': 'a.gguf', 'phase': 'telechargement', 'fait': 10 ** 9,
                                              'total': 4 * 10 ** 9, 'erreur': None}]
        self.faux.etat['consentements'] = [{'id': 'x'}]
        statut = self.prisme.statut()
        self.assertEqual(statut['engines'], {'image': 'installed', 'text': 'not installed'})
        self.assertEqual(statut['downloads'][0], {'file': 'a.gguf', 'status': 'telechargement', 'done_gb': 1.0, 'total_gb': 4.0})
        self.assertEqual(statut['waiting_for_user_approval'], 1)

    def test_prisme_lance_s_il_n_est_pas_ouvert(self):
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            port = s.getsockname()[1]
        lance = []
        prisme = Prisme(f'http://127.0.0.1:{port}', dossier=self.dossier, demarrage=['prisme'])
        with mock.patch.object(Prisme, 'demarrer_prisme', lambda soi: lance.append(True) or False):
            with self.assertRaisesRegex(PrismeErreur, 'not running'):
                prisme.statut()
        self.assertEqual(lance, [True])

    def test_apercu_sans_pillow(self):
        import os
        # Image bruitee qui ne se compresse pas : il faut la reduire
        largeur, hauteur = 1024, 768
        grand = prisme_client.ecrire_png(largeur, hauteur, bytearray(os.urandom(largeur * hauteur * 3)))
        self.assertGreater(len(grand), prisme_client.APERCU_MAX)
        with mock.patch.dict(sys.modules, {'PIL': None}):
            donnees, genre = prisme_client.apercu(grand)
        self.assertEqual(genre, 'png')
        self.assertLessEqual(len(donnees), prisme_client.APERCU_MAX)
        largeur_apercu, hauteur_apercu, _, pixels = prisme_client.lire_png(donnees)
        self.assertEqual((largeur_apercu, hauteur_apercu), (512, 384))
        # Lecture des cinq filtres PNG : comparaison avec un PNG filtre ligne par ligne
        source = bytearray(os.urandom(6 * 5 * 3))
        self.assertEqual(prisme_client.lire_png(png_filtre(6, 5, source))[3], source)

    def test_protocole_json_rpc(self):
        import io
        messages = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18', 'capabilities': {},
                                                                          'clientInfo': {'name': 'essai', 'version': '1'}}},
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
            {'jsonrpc': '2.0', 'id': 3, 'method': 'ping'},
            {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {'name': 'get_status', 'arguments': {}}},
            {'jsonrpc': '2.0', 'id': 5, 'method': 'tools/call', 'params': {'name': 'generate_image', 'arguments': {'prompt': ''}}},
            {'jsonrpc': '2.0', 'id': 6, 'method': 'tools/call', 'params': {'name': 'inconnu'}},
            {'jsonrpc': '2.0', 'id': 7, 'method': 'sampling/inconnu'},
            # Claude Desktop les demande a chaque serveur
            {'jsonrpc': '2.0', 'id': 8, 'method': 'prompts/list'},
            {'jsonrpc': '2.0', 'id': 9, 'method': 'resources/list'},
            {'jsonrpc': '2.0', 'id': 10, 'method': 'resources/templates/list'},
        ]
        entree = io.BytesIO(b''.join(json.dumps(m).encode() + b'\n' for m in messages) + b'pas du json\n')
        sortie = io.BytesIO()
        serveur = prisme_client.ServeurMcp(self.prisme, '9.9', entree, sortie)
        serveur.boucle()
        # Les outils tournent a part : on attend leurs reponses
        import time
        limite = time.time() + 10
        while time.time() < limite and sortie.getvalue().count(b'\n') < 11:
            time.sleep(0.05)
        reponses = {m.get('id'): m for m in map(json.loads, sortie.getvalue().decode().splitlines())}
        self.assertEqual(reponses[1]['result']['protocolVersion'], '2025-06-18')
        self.assertEqual(reponses[1]['result']['serverInfo']['version'], '9.9')
        self.assertIn('tools', reponses[1]['result']['capabilities'])
        noms = {o['name'] for o in reponses[2]['result']['tools']}
        self.assertEqual(noms, {'generate_image', 'edit_image', 'list_models', 'list_profiles', 'get_status',
                                'install_engine', 'download_profile', 'download_model'})
        self.assertTrue(all(o['inputSchema']['type'] == 'object' and o['description'] for o in reponses[2]['result']['tools']))
        self.assertEqual(reponses[3]['result'], {})
        self.assertFalse(reponses[4]['result']['isError'])
        self.assertEqual(json.loads(reponses[4]['result']['content'][0]['text'])['version'], '1.8.5')
        self.assertTrue(reponses[5]['result']['isError'])
        self.assertIn('empty', reponses[5]['result']['content'][0]['text'])
        self.assertEqual(reponses[6]['error']['code'], -32602)
        self.assertEqual(reponses[7]['error']['code'], -32601)
        self.assertEqual((reponses[8]['result'], reponses[9]['result'], reponses[10]['result']),
                         ({'prompts': []}, {'resources': []}, {'resourceTemplates': []}))
        self.assertEqual(reponses[None]['error']['code'], -32700)

    def test_apercu_jpeg_pour_une_grande_image(self):
        try:
            from PIL import Image as ImagePil
        except ImportError:
            self.skipTest('Pillow absent')
        import io
        import os
        # Bruit : un PNG qui ne se compresse pas, comme une vraie photo
        tampon = io.BytesIO()
        ImagePil.frombytes('RGB', (1024, 768), os.urandom(1024 * 768 * 3)).save(tampon, 'PNG')
        grand = tampon.getvalue()
        self.assertGreater(len(grand), prisme_client.APERCU_MAX)
        donnees, genre = prisme_client.apercu(grand)
        self.assertEqual(genre, 'jpeg')
        self.assertLessEqual(len(donnees), prisme_client.APERCU_MAX)
        self.assertTrue(donnees.startswith(b'\xff\xd8'))

    def test_apercu_limite(self):
        petit = png()
        self.assertEqual(prisme_client.apercu(petit), (petit, 'png'))
        with mock.patch.dict(sys.modules, {'PIL': None}):
            self.assertEqual(prisme_client.apercu(b'x' * 100, maximum=10), (None, None))


if __name__ == '__main__':
    unittest.main()
