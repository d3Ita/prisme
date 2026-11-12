"""Prisme 2 : la fenetre de bureau en Qt Quick (PySide6).

Le serveur de Prisme tourne dans ce meme processus. L'interface QML lui parle par son API locale, comme le telephone
(page web) et Claude (serveur MCP) : une seule logique pour les trois. Qt doit tourner dans le fil principal (macOS).
Seul ce que QML ne sait pas faire passe par Python : lire une image choisie, glissee ou collee."""
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, QObject, QUrl, Slot
from PySide6.QtGui import QGuiApplication, QIcon, QImage
from PySide6.QtQml import QQmlApplicationEngine


def image_de_depart(image, nom):
    """Image de depart pour l'API (source_data) : convertie en PNG comme dans la version web, ou None si illisible."""
    if image.isNull():
        return None
    tampon = QBuffer()
    tampon.open(QIODevice.WriteOnly)
    image.save(tampon, 'PNG')
    donnees = 'data:image/png;base64,' + bytes(tampon.data().toBase64()).decode('ascii')
    return {'data': donnees, 'url': donnees, 'nom': nom, 'largeur': image.width(), 'hauteur': image.height()}


class Fichiers(QObject):
    """Lecture d'une image de depart : fichier choisi ou glisse, ou image du presse-papiers."""

    @Slot(str, result='QVariant')
    def lireImage(self, adresse):
        chemin = QUrl(adresse).toLocalFile() or adresse
        return image_de_depart(QImage(chemin), Path(chemin).name)

    @Slot(result='QVariant')
    def collerImage(self):
        return image_de_depart(QGuiApplication.clipboard().image(), 'Image collée')

    @Slot(str)
    def copier(self, texte):
        QGuiApplication.clipboard().setText(texte)

    @Slot(str, result=str)
    def qrCode(self, texte):
        """QR code du lien du telephone, en image SVG (segno, sans Internet) ; vide si segno manque."""
        try:
            import segno
        except ImportError:
            return ''
        # Toujours sombre sur clair : les telephones lisent mal un QR code inverse
        return segno.make(texte, error='m').svg_data_uri(scale=6, border=2, dark='#1f2430', light='#ffffff')


def application():
    """L'application Qt ; son nom range l'apparence choisie (Settings) a part des autres programmes."""
    appli = QGuiApplication.instance() or QGuiApplication(sys.argv)
    appli.setApplicationName('Prisme')
    appli.setOrganizationName('Prisme')
    return appli


def charger(adresse, ressources, erreurs=None, **proprietes):
    """Charge la fenetre. erreurs (liste) recoit les erreurs QML, pour les tests et les captures."""
    moteur = QQmlApplicationEngine()
    if erreurs is not None:
        moteur.warnings.connect(lambda liste: erreurs.extend(e.toString() for e in liste))
    moteur.rootContext().setContextProperty('fichiers', Fichiers(moteur))
    moteur.setInitialProperties({'adresse': adresse, **proprietes})
    moteur.load(QUrl.fromLocalFile(str(Path(ressources) / 'qml' / 'Prisme.qml')))
    return moteur


def lancer(adresse, ressources):
    """Ouvre la fenetre et rend la main quand elle se ferme. Renvoie le code de sortie de Qt."""
    appli = application()
    appli.setWindowIcon(QIcon(str(Path(ressources) / 'logo.png')))
    moteur = charger(adresse, ressources)
    if not moteur.rootObjects():
        return 1
    return appli.exec()
