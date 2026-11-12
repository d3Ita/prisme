"""Prisme 2 : la fenetre Qt Quick se charge sans erreur QML (lance seulement si PySide6 est installe).

Sans ecran (CI) : plateforme offscreen et rendu logiciel."""
import os
import time
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')

try:
    from PySide6.QtCore import QEventLoop, QMetaObject, QObject, QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
except ImportError:
    QGuiApplication = None

QML = Path(__file__).resolve().parent.parent / 'app' / 'qml' / 'Prisme.qml'


@unittest.skipIf(QGuiApplication is None, 'PySide6 non installé')
class FenetreQtTest(unittest.TestCase):
    def test_la_fenetre_se_charge_sans_erreur(self):
        application = QGuiApplication.instance() or QGuiApplication([])
        application.setApplicationName('Prisme')
        application.setOrganizationName('Prisme')
        moteur = QQmlApplicationEngine()
        erreurs = []
        moteur.warnings.connect(lambda liste: erreurs.extend(e.toString() for e in liste))
        # Aucun Prisme sur ce port : la fenetre doit s'afficher quand meme, en signalant qu'il ne repond pas
        moteur.setInitialProperties({'adresse': 'http://127.0.0.1:9'})
        moteur.load(QUrl.fromLocalFile(str(QML)))
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


if __name__ == '__main__':
    unittest.main()
