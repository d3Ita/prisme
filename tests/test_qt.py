"""Prisme 2 : la fenetre Qt Quick se charge sans erreur QML (lance seulement si PySide6 est installe).

Sans ecran (CI) : plateforme offscreen et rendu logiciel."""
import os
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')

try:
    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
except ImportError:
    QGuiApplication = None

QML = Path(__file__).resolve().parent.parent / 'app' / 'qml' / 'Prisme.qml'


@unittest.skipIf(QGuiApplication is None, 'PySide6 non installé')
class FenetreQtTest(unittest.TestCase):
    def test_la_fenetre_se_charge_sans_erreur(self):
        application = QGuiApplication.instance() or QGuiApplication([])
        moteur = QQmlApplicationEngine()
        erreurs = []
        moteur.warnings.connect(lambda liste: erreurs.extend(e.toString() for e in liste))
        # Aucun Prisme sur ce port : la fenetre doit s'afficher quand meme, en signalant qu'il ne repond pas
        moteur.setInitialProperties({'adresse': 'http://127.0.0.1:9'})
        moteur.load(QUrl.fromLocalFile(str(QML)))
        QTimer.singleShot(1500, application.quit)
        application.exec()
        self.assertTrue(moteur.rootObjects(), erreurs)
        racine = moteur.rootObjects()[0]
        self.assertEqual(racine.property('title'), 'Prisme')
        self.assertFalse(racine.property('enLigne'))
        self.assertEqual(erreurs, [])


if __name__ == '__main__':
    unittest.main()
