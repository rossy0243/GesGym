/*!
 * Corrige l'empilement des modals Bootstrap.
 *
 * theme.min.css applique `filter: blur(3px)` sur .nxl-container, .nxl-header,
 * .nxl-navigation et .page-header tant que <body> porte la classe .modal-open,
 * afin de flouter la page derriere le modal.
 *
 * Or un ancetre porteur d'un `filter` different de `none` cree un contexte
 * d'empilement et devient le bloc conteneur de ses descendants position:fixed.
 * Les modals etant declares dans {% block content %}, donc a l'interieur de
 * .nxl-container, ils heritaient du flou et passaient sous le .modal-backdrop
 * (ajoute sur <body>, z-index 1040) : modal illisible et inutilisable.
 *
 * On rattache donc chaque modal au <body> juste avant son ouverture. Verifie :
 * aucun des 48 modals du projet n'est imbrique dans un <form>, le deplacement
 * ne casse donc aucune soumission.
 */
(function () {
    "use strict";

    document.addEventListener("show.bs.modal", function (event) {
        var modal = event.target;

        if (!modal || !modal.classList || !modal.classList.contains("modal")) {
            return;
        }

        if (modal.parentElement === document.body) {
            return;
        }

        document.body.appendChild(modal);
    });
})();
