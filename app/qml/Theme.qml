// Ce que partagent tous les ecrans de Prisme 2 : couleurs (celles de la version web), langue et appels a l'API locale
pragma Singleton
import QtQuick

QtObject {
    // Adresse du serveur de Prisme, donnee par la fenetre principale
    property string adresse: ""
    property bool enLigne: true
    // "auto" (celle du systeme), "clair" ou "sombre"
    property string apparence: "auto"
    readonly property bool sombre: apparence === "sombre" || (apparence === "auto" && Qt.styleHints.colorScheme === Qt.ColorScheme.Dark)
    readonly property bool francais: Qt.locale().name.startsWith("fr")

    readonly property color fond: sombre ? "#1b1a18" : "#f6f4ef"
    readonly property color surface: sombre ? "#242320" : "#ffffff"
    readonly property color surface2: sombre ? "#2a2926" : "#fbfaf7"
    readonly property color surface3: sombre ? "#34322e" : "#efece5"
    readonly property color bordure: sombre ? "#383632" : "#e7e3da"
    readonly property color bordureForte: sombre ? "#4a4742" : "#d5cfc3"
    readonly property color texte: sombre ? "#f1eee8" : "#1f2430"
    readonly property color texte2: sombre ? "#bdb8ae" : "#575d6b"
    readonly property color texte3: sombre ? "#8d887f" : "#858a95"
    readonly property color accent: sombre ? "#f07a5a" : "#2f5bea"
    readonly property color accentDoux: sombre ? Qt.rgba(240 / 255, 122 / 255, 90 / 255, 0.13) : Qt.rgba(47 / 255, 91 / 255, 234 / 255, 0.09)
    readonly property color surAccent: sombre ? "#2a140d" : "#ffffff"
    readonly property color bulle: sombre ? "#3a2d27" : "#e8edfb"
    readonly property color succes: sombre ? "#4cc38a" : "#1f9d63"
    readonly property color danger: sombre ? "#f26b6b" : "#d64545"
    readonly property color fondImage: sombre ? "#1f1e1b" : "#ebe8e1"
    readonly property color voile: sombre ? Qt.rgba(0, 0, 0, 0.55) : Qt.rgba(31 / 255, 36 / 255, 48 / 255, 0.38)

    // Message court a afficher par la fenetre principale
    signal message(string texte, bool erreur)

    function tx(fr, en) { return francais ? fr : en }
    function enLangue(o) { return o ? (francais ? o.fr : o.en) : "" }
    function note(texte, erreur) { message(texte, !!erreur) }

    function taille(octets) {
        const go = octets >= 1e9
        const valeur = go ? (octets / 1e9).toFixed(1) : String(Math.round(octets / 1e6))
        return francais ? valeur.replace(".", ",") + (go ? " Go" : " Mo") : valeur + (go ? " GB" : " MB")
    }

    // Appel a l'API de Prisme ; echec(message) recoit le message d'erreur du serveur
    function api(chemin, corps, reussite, echec) {
        const requete = new XMLHttpRequest()
        requete.onreadystatechange = function () {
            if (requete.readyState !== XMLHttpRequest.DONE)
                return
            let donnees = {}
            try { donnees = JSON.parse(requete.responseText || "{}") } catch (e) {}
            if (requete.status >= 200 && requete.status < 300) {
                enLigne = true
                if (reussite) reussite(donnees)
                return
            }
            if (!requete.status) enLigne = false
            const texte = donnees.erreur || (requete.status ? tx("Erreur ", "Error ") + requete.status
                                                             : tx("Prisme ne répond pas.", "Prisme is not responding."))
            if (echec) echec(texte)
            else note(texte, true)
        }
        requete.open(corps === undefined ? "GET" : "POST", adresse + chemin)
        if (corps === undefined) {
            requete.send()
        } else {
            requete.setRequestHeader("Content-Type", "application/json")
            requete.send(JSON.stringify(corps))
        }
    }
}
