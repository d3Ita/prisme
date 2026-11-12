"""Prisme 2 : la fenetre de bureau en Qt Quick (PySide6).

Le serveur de Prisme tourne dans ce meme processus. L'interface QML lui parle par son API locale, comme le telephone
(page web) et Claude (serveur MCP) : une seule logique pour les trois. Qt doit tourner dans le fil principal (macOS)."""
import sys
from pathlib import Path


def lancer(adresse, ressources):
    """Ouvre la fenetre et rend la main quand elle se ferme. Renvoie le code de sortie de Qt."""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QGuiApplication, QIcon
    from PySide6.QtQml import QQmlApplicationEngine

    application = QGuiApplication.instance() or QGuiApplication(sys.argv)
    application.setApplicationName('Prisme')
    application.setOrganizationName('Prisme')
    application.setWindowIcon(QIcon(str(Path(ressources) / 'logo.png')))
    moteur = QQmlApplicationEngine()
    moteur.setInitialProperties({'adresse': adresse})
    moteur.load(QUrl.fromLocalFile(str(Path(ressources) / 'qml' / 'Prisme.qml')))
    if not moteur.rootObjects():
        return 1
    return application.exec()
