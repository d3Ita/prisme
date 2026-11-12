"""Prisme 2 : la fenetre Qt Quick se charge sans erreur QML (lance seulement si PySide6 est installe).

Sans ecran (CI) : plateforme offscreen et rendu logiciel."""
import os
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
    import fenetre_qt
except ImportError:
    fenetre_qt = None


@unittest.skipIf(fenetre_qt is None, 'PySide6 non installé')
class FenetreQtTest(unittest.TestCase):
    def test_la_fenetre_se_charge_sans_erreur(self):
        application = fenetre_qt.application()
        erreurs = []
        # Aucun Prisme sur ce port : la fenetre doit s'afficher quand meme, en signalant qu'il ne repond pas
        moteur = fenetre_qt.charger('http://127.0.0.1:9', APP, erreurs)
        self.assertTrue(moteur.rootObjects(), erreurs)
        racine = moteur.rootObjects()[0]
        # Sous Windows, une connexion refusee met environ 2 s a echouer
        limite = time.monotonic() + 10
        while racine.property('enLigne') and time.monotonic() < limite:
            application.processEvents(QEventLoop.AllEvents, 100)
        self.assertEqual(racine.property('title'), 'Prisme')
        self.assertFalse(racine.property('enLigne'))
        # Les fenetres Modeles et Reglages s'ouvrent aussi sans erreur, meme sans reponse du serveur
        for nom in ('modeles', 'reglages'):
            fenetre = racine.findChild(QObject, nom)
            self.assertIsNotNone(fenetre, nom)
            QMetaObject.invokeMethod(fenetre, 'open')
            limite = time.monotonic() + 1
            while time.monotonic() < limite:
                application.processEvents(QEventLoop.AllEvents, 50)
            self.assertTrue(fenetre.property('opened'), nom)
            QMetaObject.invokeMethod(fenetre, 'close')
        self.assertEqual(erreurs, [])


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


if __name__ == '__main__':
    unittest.main()
