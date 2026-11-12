// Utiliser Prisme sur le telephone : adresse a taper, QR code (lien avec le code d'acces) et lien a copier
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Panneau {
    id: fenetre
    titre: Theme.tx("Utiliser sur ton téléphone", "Use on your phone")
    width: Math.min(parent ? parent.width - 48 : 520, 520)
    height: Math.min(parent ? parent.height - 48 : 640, 640)
    property var acces: null
    property string qr: ""

    onOpened: Theme.api("/api/acces", undefined, function (a) {
        acces = a
        qr = a.reseau && typeof fichiers !== "undefined" ? fichiers.qrCode(a.lien) : ""
    })

    component Paragraphe: Text {
        color: Theme.texte2
        font.pixelSize: 13
        wrapMode: Text.WordWrap
        Layout.fillWidth: true
    }

    Paragraphe {
        visible: !!fenetre.acces && !fenetre.acces.reseau
        color: Theme.texte
        text: Theme.tx("L'accès depuis le téléphone est désactivé. Active-le dans les Réglages, puis relance Prisme.",
                       "Phone access is turned off. Turn it on in the Settings, then restart Prisme.")
    }
    ColumnLayout {
        visible: !!fenetre.acces && fenetre.acces.reseau
        Layout.fillWidth: true
        spacing: 12
        Paragraphe { text: Theme.tx("Tape cette adresse dans le navigateur du téléphone, puis autorise-le ici :", "Type this address in the phone's browser, then approve it here:") }
        Text {
            text: fenetre.acces ? fenetre.acces.adresse.replace("http://", "") : ""
            color: Theme.texte
            font.pixelSize: 24
            font.weight: Font.DemiBold
            Layout.alignment: Qt.AlignHCenter
        }
        Paragraphe { text: Theme.tx("Ou scanne ce code pour te connecter directement :", "Or scan this code to connect directly:") }
        Rectangle {
            Layout.alignment: Qt.AlignHCenter
            implicitWidth: 212
            implicitHeight: 212
            radius: 14
            color: "#ffffff"
            border.color: Theme.bordure
            Image {
                anchors.centerIn: parent
                width: 192
                height: 192
                source: fenetre.qr
                visible: fenetre.qr !== ""
                smooth: false
            }
            Text {
                anchors.fill: parent
                anchors.margins: 14
                visible: fenetre.qr === ""
                text: Theme.tx("QR code indisponible : ouvre le lien ci-dessous sur le téléphone.", "QR code unavailable: open the link below on the phone.")
                color: "#575d6b"
                font.pixelSize: 12
                wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Champ {
                Layout.fillWidth: true
                readOnly: true
                text: fenetre.acces ? fenetre.acces.lien : ""
            }
            BoutonPrincipal {
                secondaire: true
                text: Theme.tx("Copier", "Copy")
                onClicked: {
                    if (typeof fichiers !== "undefined") fichiers.copier(fenetre.acces.lien)
                    Theme.note(Theme.tx("Lien copié", "Link copied"))
                }
            }
        }
        Paragraphe {
            text: "1. " + Theme.tx("Le téléphone doit être sur le même réseau (Wi-Fi de la maison) que ce PC.", "The phone must be on the same network (home Wi-Fi) as this computer.")
                  + "\n2. " + Theme.tx("Le PC doit rester allumé avec Prisme lancé.", "The computer must stay on with Prisme running.")
                  + "\n3. " + Theme.tx("Le lien du QR code contient ton code d'accès : ne le partage pas.", "The QR code link contains your access code: don't share it.")
        }
    }
}
