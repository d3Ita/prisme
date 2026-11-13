"""Prisme 2 : la fenetre de bureau en Qt Quick (PySide6).

Le serveur de Prisme tourne dans ce meme processus. L'interface QML lui parle par son API locale, comme le telephone
(page web) et Claude (serveur MCP) : une seule logique pour les trois. Qt doit tourner dans le fil principal (macOS).
Seul ce que QML ne sait pas faire passe par Python : lire une image choisie, glissee ou collee."""
import sys
import urllib.request
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, QObject, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QFontDatabase, QGuiApplication, QIcon, QImage
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow

WINDOWS = sys.platform == 'win32'
# Police moderne de Windows 11, plus proche de celle du Mac que Segoe UI (gardee si elle manque, sous Windows 10)
POLICE_WINDOWS = 'Segoe UI Variable'
# Attributs de DwmSetWindowAttribute : barre sombre (19 avant Windows 10 20H1), puis couleurs du bord, de la barre et
# de son texte (Windows 11 ; ignores par Windows 10)
DWM_SOMBRE, DWM_SOMBRE_ANCIEN, DWM_BORD, DWM_BARRE, DWM_TEXTE = 20, 19, 34, 35, 36


def couleur_windows(couleur):
    """'#rrggbb' en COLORREF (0x00BBGGRR), l'ordre des couleurs de l'API de Windows."""
    c = QColor(couleur)
    return c.red() | c.green() << 8 | c.blue() << 16


def image_de_depart(image, nom):
    """Image de depart pour l'API (source_data) : convertie en PNG comme dans la version web, ou None si illisible."""
    if image.isNull():
        return None
    tampon = QBuffer()
    tampon.open(QIODevice.WriteOnly)
    image.save(tampon, 'PNG')
    donnees = 'data:image/png;base64,' + bytes(tampon.data().toBase64()).decode('ascii')
    return {'data': donnees, 'url': donnees, 'nom': nom, 'largeur': image.width(), 'hauteur': image.height()}


def lire_locale(adresse):
    """Une image servie par Prisme sur cet ordinateur (jamais une autre adresse), ou None."""
    if not adresse.startswith(('http://127.0.0.1:', 'http://localhost:')):
        return None
    try:
        with urllib.request.urlopen(adresse, timeout=30) as reponse:
            return reponse.read()
    except OSError:
        return None


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

    @Slot(str, result=bool)
    def copierImage(self, adresse):
        """Copie une image du fil dans le presse-papiers (pour la coller ailleurs)."""
        image = QImage.fromData(lire_locale(adresse) or b'')
        if image.isNull():
            return False
        QGuiApplication.clipboard().setImage(image)
        return True

    @Slot(str, str, result=bool)
    def enregistrerImage(self, adresse, destination):
        """Enregistre une image du fil la ou l'utilisateur l'a choisi."""
        donnees = lire_locale(adresse)
        if not donnees:
            return False
        try:
            Path(QUrl(destination).toLocalFile() or destination).write_bytes(donnees)
        except OSError:
            return False
        return True

    @Slot(str, result=str)
    def qrCode(self, texte):
        """QR code du lien du telephone, en image SVG (segno, sans Internet) ; vide si segno manque."""
        try:
            import segno
        except ImportError:
            return ''
        # Toujours sombre sur clair : les telephones lisent mal un QR code inverse
        return segno.make(texte, error='m').svg_data_uri(scale=6, border=2, dark='#1f2430', light='#ffffff')


class Reseau(QObject):
    """Requetes de l'interface vers le serveur de Prisme. Le XMLHttpRequest de QML rend un statut 0 et une reponse vide
    pour certaines erreurs (409 : « une generation est deja en cours »...) : la fenetre aurait dit « Prisme ne repond pas »."""
    reponse = Signal(int, int, str)  # numero de la requete, statut HTTP (0 sans reponse), texte de la reponse

    def __init__(self, parent=None):
        super().__init__(parent)
        self.acces = QNetworkAccessManager(self)

    @Slot(int, str, str, str)
    def envoyer(self, numero, methode, adresse, corps):
        demande = QNetworkRequest(QUrl(adresse))
        if methode == 'POST':
            demande.setHeader(QNetworkRequest.ContentTypeHeader, 'application/json')
            reponse = self.acces.post(demande, corps.encode('utf-8'))
        else:
            reponse = self.acces.get(demande)
        reponse.finished.connect(lambda: self.finir(numero, reponse))

    def finir(self, numero, reponse):
        statut = reponse.attribute(QNetworkRequest.HttpStatusCodeAttribute) or 0
        texte = bytes(reponse.readAll()).decode('utf-8', 'replace')
        reponse.deleteLater()
        self.reponse.emit(numero, int(statut), texte)


class Cadre(QObject):
    """Barre de titre de Windows aux couleurs de Prisme : sombre avec le theme sombre (Windows 10 et 11), et sous
    Windows 11 de la couleur exacte du fond, comme sur Mac ou elle se fond deja dans la fenetre. Sans effet ailleurs."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.fenetre = None

    @Slot(str, str, str, bool)
    def teinter(self, fond, texte, bord, sombre):
        if not WINDOWS or self.fenetre is None:
            return
        import ctypes
        fenetre = ctypes.c_void_p(int(self.fenetre.winId()))

        def regler(attribut, valeur):
            v = ctypes.c_int(valeur)
            return ctypes.windll.dwmapi.DwmSetWindowAttribute(fenetre, attribut, ctypes.byref(v), ctypes.sizeof(v)) == 0

        if not regler(DWM_SOMBRE, int(sombre)):
            regler(DWM_SOMBRE_ANCIEN, int(sombre))
        regler(DWM_BARRE, couleur_windows(fond))
        regler(DWM_TEXTE, couleur_windows(texte))
        regler(DWM_BORD, couleur_windows(bord))


def application():
    """L'application Qt ; son nom range l'apparence choisie (Settings) a part des autres programmes."""
    if WINDOWS and not QGuiApplication.instance():
        # Texte dessine par Windows (aligne sur les pixels) : celui de Qt Quick y est plus flou que sur Mac
        QQuickWindow.setTextRenderType(QQuickWindow.TextRenderType.NativeTextRendering)
    appli = QGuiApplication.instance() or QGuiApplication(sys.argv)
    appli.setApplicationName('Prisme')
    appli.setOrganizationName('Prisme')
    if WINDOWS and POLICE_WINDOWS in QFontDatabase.families():
        police = appli.font()
        police.setFamily(POLICE_WINDOWS)
        appli.setFont(police)
    return appli


def charger(adresse, ressources, erreurs=None, **proprietes):
    """Charge la fenetre. erreurs (liste) recoit les erreurs QML, pour les tests et les captures."""
    moteur = QQmlApplicationEngine()
    if erreurs is not None:
        moteur.warnings.connect(lambda liste: erreurs.extend(e.toString() for e in liste))
    moteur.rootContext().setContextProperty('fichiers', Fichiers(moteur))
    moteur.rootContext().setContextProperty('requetes', Reseau(moteur))
    cadre = Cadre(moteur)
    moteur.rootContext().setContextProperty('cadre', cadre)
    moteur.setInitialProperties({'adresse': adresse, **proprietes})
    moteur.load(QUrl.fromLocalFile(str(Path(ressources) / 'qml' / 'Prisme.qml')))
    if moteur.rootObjects():
        # La fenetre la teinte des qu'elle est prete, puis a chaque changement de theme
        cadre.fenetre = moteur.rootObjects()[0]
    return moteur


class Pont(QObject):
    """Fait reapparaitre la fenetre depuis un autre fil (serveur) : le signal est livre dans le fil de Qt."""
    montrer = Signal()


def lancer(adresse, ressources, quand_prete=None, visible=True):
    """Ouvre la fenetre ; rend la main quand l'utilisateur quitte Prisme (0), ou tout de suite si elle ne se charge pas (1).
    quand_prete(montrer) recoit une fonction, appelable depuis n'importe quel fil, qui fait reapparaitre la fenetre."""
    appli = application()
    appli.setWindowIcon(QIcon(str(Path(ressources) / 'logo.png')))
    # Fermer la fenetre la cache seulement : Prisme continue pour le telephone, Claude ou un telechargement, puis
    # s'arrete selon ses reglages, comme avec la fenetre web
    appli.setQuitOnLastWindowClosed(False)
    # Cachee au depart apres une mise a jour (--sans-fenetre) : elle apparait quand la page web lui passe la main
    moteur = charger(adresse, ressources, visible=visible)
    if not moteur.rootObjects():
        return 1
    fenetre = moteur.rootObjects()[0]

    def montrer():
        fenetre.show()
        fenetre.raise_()
        fenetre.requestActivate()

    pont = Pont()
    pont.montrer.connect(montrer, Qt.QueuedConnection)
    # Sur Mac, un clic sur l'icone du Dock rend Prisme actif : sa fenetre cachee reapparait
    appli.applicationStateChanged.connect(lambda etat: etat == Qt.ApplicationActive and not fenetre.isVisible() and montrer())
    if quand_prete:
        quand_prete(pont.montrer.emit)
    return appli.exec()
