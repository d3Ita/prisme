"""Prisme 2 : la fenetre Qt Quick se charge sans erreur QML (lance seulement si PySide6 est installe).

Sans ecran (CI) : plateforme offscreen et rendu logiciel."""
import json
import os
import socket
import sys
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')

APP = Path(__file__).resolve().parent.parent / 'app'
sys.path.insert(0, str(APP))
try:
    from PySide6.QtCore import QEventLoop, QMetaObject, QObject, QUrl
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtQml import QQmlExpression
    import fenetre_qt
except ImportError:
    fenetre_qt = None


@unittest.skipIf(fenetre_qt is None, 'PySide6 non installé')
class FenetreQtTest(unittest.TestCase):
    def test_la_fenetre_se_charge_sans_erreur(self):
        application = fenetre_qt.application()
        erreurs = []
        # Aucun Prisme sur ce port (tout juste libere, donc ferme) : la fenetre s'affiche quand meme et signale
        # qu'il ne repond pas
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            port = s.getsockname()[1]
        moteur = fenetre_qt.charger(f'http://127.0.0.1:{port}', APP, erreurs)
        self.assertTrue(moteur.rootObjects(), erreurs)
        racine = moteur.rootObjects()[0]
        # Sous Windows, une connexion refusee met environ 2 s a echouer
        limite = time.monotonic() + 10
        while racine.property('enLigne') and time.monotonic() < limite:
            application.processEvents(QEventLoop.AllEvents, 100)
        self.assertEqual(racine.property('title'), 'Prisme')
        # shortcut: sur la machine Mac de la CI, Qt ne signale pas la connexion refusee en 10 s ; verifie sous Windows
        # et Linux seulement, a revoir si « Prisme ne repond pas » manque sur un vrai Mac
        if sys.platform != 'darwin':
            self.assertFalse(racine.property('enLigne'))
        # Les fenetres Modeles, Reglages, Telephone, Details et Comparer s'ouvrent aussi sans erreur, meme sans reponse du serveur
        for nom in ('modeles', 'reglages', 'telephone', 'details', 'comparateur'):
            fenetre = racine.findChild(QObject, nom)
            self.assertIsNotNone(fenetre, nom)
            QMetaObject.invokeMethod(fenetre, 'open')
            limite = time.monotonic() + 1
            while time.monotonic() < limite:
                application.processEvents(QEventLoop.AllEvents, 50)
            self.assertTrue(fenetre.property('opened'), nom)
            QMetaObject.invokeMethod(fenetre, 'close')
        # Refaire a l'identique : description, variante, taille hors format et reglages de l'image pour la creation
        parametres = '{etapes: 4, cfg: 1, methode: "euler", modele_diffusion: "flux/dessin.gguf"}'
        evaluer = lambda code: QQmlExpression(moteur.contextForObject(racine), racine, code).evaluate()[0]
        evaluer('details.ouvrir({nom: "image_1.png", prompt: "un phare", seed: 7, largeur: 832, hauteur: 1216, loras: [], '
                f'date: "2026-11-13T10:00:00", parametres: {parametres}}}); details.refaire(details.image)')
        self.assertEqual(evaluer('[saisie.text, variante.text, format, tailleVoulue().join("x"), reprise.parametres.etapes].join("|")'),
                         'un phare|7|repris|832x1216|4')
        # Ce que recoit /api/generer : les reglages de l'image, les LoRA choisis et le projet montre
        evaluer('lorasDispo = [{nom: "style.safetensors", force: 0.8, actif: true}, {nom: "autre.safetensors", force: 1, actif: false}]; '
                'basculerLora(lorasDispo[1]); changerForce(lorasDispo[0], "0,5"); projetActif = "Phares"')
        # Une intensite hors de -2 a 2 est refusee et ne change rien
        self.assertFalse(evaluer('changerForce(lorasDispo[1], "7")'))
        self.assertEqual(evaluer('JSON.stringify(corpsCreation())'), json.dumps({
            'prompt': 'un phare', 'largeur': 832, 'hauteur': 1216, 'nombre': 1, 'seed': 7,
            'parametres': {'etapes': 4, 'cfg': 1, 'methode': 'euler', 'modele_diffusion': 'flux/dessin.gguf',
                           'loras': [{'nom': 'autre.safetensors', 'force': 1}, {'nom': 'style.safetensors', 'force': 0.5}]},
            'projet': 'Phares'}, separators=(',', ':')))
        evaluer('oublierReprise()')
        self.assertEqual(evaluer('format + (reprise === null)'), 'carretrue')
        # Le fil ne montre que le projet choisi ; une image de comparaison a sa legende
        evaluer('toutesImages = [{nom: "a.png", prompt: "un phare", projet: "Phares", mesures: {duree: 41.6, comparaison: "FLUX.2 klein 4B Q4_0"}}, '
                '{nom: "b.png", prompt: "un chat", projet: ""}]; afficherImages()')
        self.assertEqual(evaluer('images.count + "|" + images.get(0).legende'), '1|FLUX.2 klein 4B Q4_0 · 42 s')
        evaluer('projetActif = ""; afficherImages()')
        self.assertEqual(evaluer('images.count + "|" + images.get(1).legende'), '2|')
        self.assertEqual(erreurs, [])


    def test_barre_de_titre_windows(self):
        from unittest import mock
        # Windows attend ses couleurs en 0x00BBGGRR
        self.assertEqual(fenetre_qt.couleur_windows('#1b1a18'), 0x181a1b)
        self.assertEqual(fenetre_qt.couleur_windows('#2f5bea'), 0xea5b2f)
        # Hors de Windows, ou sans fenetre, rien n'est demande a Windows
        cadre = fenetre_qt.Cadre()
        cadre.teinter('#1b1a18', '#f1eee8', '#383632', True)
        cadre.fenetre = mock.Mock()
        with mock.patch.object(fenetre_qt, 'WINDOWS', False):
            cadre.teinter('#1b1a18', '#f1eee8', '#383632', True)
        cadre.fenetre.winId.assert_not_called()

    def test_image_de_depart_en_png(self):
        fenetre_qt.application()
        image = QImage(40, 30, QImage.Format_RGB32)
        image.fill(QColor('#2f5bea'))
        with tempfile.TemporaryDirectory() as dossier:
            chemin = os.path.join(dossier, 'photo.jpg')
            image.save(chemin, 'JPG')
            source = fenetre_qt.Fichiers().lireImage(QUrl.fromLocalFile(chemin).toString())
        # Une photo JPEG devient un PNG pour l'API, avec sa taille et son nom
        self.assertEqual((source['nom'], source['largeur'], source['hauteur']), ('photo.jpg', 40, 30))
        self.assertTrue(source['data'].startswith('data:image/png;base64,'))
        self.assertIsNone(fenetre_qt.Fichiers().lireImage('/introuvable/x.png'))


    def test_copier_et_enregistrer_une_image(self):
        import functools
        import http.server
        import threading
        fenetre_qt.application()
        image = QImage(20, 10, QImage.Format_RGB32)
        image.fill(QColor('#f07a5a'))
        with tempfile.TemporaryDirectory() as dossier:
            image.save(os.path.join(dossier, 'image_1.png'), 'PNG')
            gestion = functools.partial(http.server.SimpleHTTPRequestHandler, directory=dossier)
            serveur = http.server.ThreadingHTTPServer(('127.0.0.1', 0), gestion)
            threading.Thread(target=serveur.serve_forever, daemon=True).start()
            self.addCleanup(serveur.shutdown)
            adresse = f'http://127.0.0.1:{serveur.server_address[1]}/image_1.png'
            fichiers = fenetre_qt.Fichiers()
            self.assertTrue(fichiers.copierImage(adresse))
            self.assertEqual(fenetre_qt.QGuiApplication.clipboard().image().width(), 20)
            copie = os.path.join(dossier, 'copie.png')
            self.assertTrue(fichiers.enregistrerImage(adresse, QUrl.fromLocalFile(copie).toString()))
            with open(copie, 'rb') as a, open(os.path.join(dossier, 'image_1.png'), 'rb') as b:
                self.assertEqual(a.read(), b.read())
            # Seulement les images de Prisme sur cet ordinateur
            self.assertFalse(fichiers.copierImage('https://exemple.org/image.png'))


    def test_erreur_409_garde_son_message(self):
        # Le XMLHttpRequest de QML rendait un statut 0 pour un 409 : la fenetre disait « Prisme ne repond pas »
        import http.server
        import json
        import threading

        class Gestion(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                corps = json.dumps({'erreur': 'Une génération est déjà en cours.'}).encode()
                self.send_response(409)
                self.send_header('Content-Length', str(len(corps)))
                self.end_headers()
                self.wfile.write(corps)

            def log_message(self, *args):
                pass

        application = fenetre_qt.application()
        serveur = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Gestion)
        threading.Thread(target=serveur.serve_forever, daemon=True).start()
        self.addCleanup(serveur.shutdown)
        reseau, recu = fenetre_qt.Reseau(), []
        reseau.reponse.connect(lambda *args: recu.append(args))
        reseau.envoyer(7, 'POST', f'http://127.0.0.1:{serveur.server_address[1]}/api/generer', '{"prompt": "un chat"}')
        limite = time.monotonic() + 10
        while not recu and time.monotonic() < limite:
            application.processEvents(QEventLoop.AllEvents, 50)
        self.assertEqual(recu[0][:2], (7, 409))
        self.assertEqual(json.loads(recu[0][2])['erreur'], 'Une génération est déjà en cours.')


if __name__ == '__main__':
    unittest.main()
