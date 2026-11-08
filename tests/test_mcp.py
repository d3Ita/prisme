"""Tests du serveur MCP (mcp/prisme_client.py) contre un faux Prisme : sans carte graphique, sans modele, sans le SDK MCP.

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
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'mcp'))

import prisme_client  # noqa: E402
from prisme_client import Prisme, PrismeErreur  # noqa: E402


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


class FauxPrisme:
    """Imite l'API de Prisme : une creation dure `etapes` lectures de /api/etat."""

    def __init__(self):
        self.etat = {'occupe': False, 'phase': None, 'problemes': [], 'version': '1.8.5', 'modele': 'dessin.gguf'}
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
                              'modeles': [{'fichier': 'Qwen-Image-2.1-Turbo-AD-Q4_K.gguf'}]}
                    return self.envoyer(200, {'profils': [profil], 'suggestion': 'gpu-8go', 'conseille': 'gpu-8go',
                                              'libre': 50 * 10 ** 9, 'machine': {}})
                if self.path == '/images/image_20261108_120000.png':
                    return self.envoyer(200, faux.image, 'image/png')
                self.envoyer(404, {'erreur': 'Introuvable'})

            def do_POST(self):
                corps = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
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
