/**
 * Les articles offerts avec une formule.
 *
 * Un seul rendu pour l'ecran de scan et pour la fiche du membre : les deux
 * montrent le meme etat - le solde de chaque article et les remises du jour -
 * et offrent les memes gestes. Les ecrire deux fois, c'etait s'assurer qu'ils
 * divergent un jour.
 *
 * Le serveur decide de tout : ce qui est remettable, ce qui est annulable. Ce
 * fichier ne fait qu'afficher l'etat qu'il renvoie, et le redessiner apres
 * chaque geste avec l'etat mis a jour.
 */
(function () {
    "use strict";

    function echapper(valeur) {
        return String(valeur === null || valeur === undefined ? "" : valeur)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function jeton() {
        var champ = document.querySelector("[name=csrfmiddlewaretoken]");
        if (champ) { return champ.value; }
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute("content") : "";
    }

    function aQuelqueChose(etat) {
        return Boolean(etat && ((etat.soldes || []).length || (etat.remises_du_jour || []).length));
    }

    function rendre(etat) {
        if (!aQuelqueChose(etat)) {
            return '<p class="text-muted small mb-0">Aucun article offert en attente.</p>';
        }

        var html = '<div class="fw-semibold mb-2 d-flex align-items-center gap-1">'
            + '<span class="material-icons" style="font-size:18px;">redeem</span>Articles offerts</div>';

        if (!etat.abonnement_actif && etat.soldes.length) {
            html += '<div class="alert alert-warning py-2 small mb-2">'
                + "Pas d'abonnement actif : le solde est conserve et redeviendra utilisable au prochain paiement."
                + '</div>';
        }

        etat.soldes.forEach(function (ligne) {
            var action;
            if (ligne.remettable) {
                action = '<input type="number" min="1" max="' + ligne.solde + '" value="1"'
                    + ' class="form-control form-control-sm" style="width:80px;"'
                    + ' data-avantage-quantite="' + ligne.product_id + '" aria-label="Quantite a remettre">'
                    + '<button type="button" class="btn btn-sm btn-outline-success"'
                    + ' data-avantage-remettre="' + ligne.product_id + '">Remettre</button>';
            } else {
                action = '<span class="badge bg-light text-muted border">'
                    + (etat.abonnement_actif ? "Rupture de stock" : "Indisponible") + '</span>';
            }
            html += '<div class="d-flex flex-wrap align-items-center justify-content-between gap-2 py-2 border-bottom">'
                + '<span><strong>' + echapper(ligne.nom) + '</strong>'
                + ' <span class="text-muted small">solde ' + ligne.solde + '</span></span>'
                + '<span class="d-flex align-items-center gap-2">' + action + '</span>'
                + '</div>';
        });

        if (etat.remises_du_jour.length) {
            html += '<div class="small text-muted mt-3 mb-1">Remis aujourd\'hui</div>';
            etat.remises_du_jour.forEach(function (remise) {
                var fin = remise.annulee
                    ? '<span class="badge bg-light text-muted border">annulee</span>'
                    : '<button type="button" class="btn btn-sm btn-link text-danger p-0"'
                        + ' data-avantage-annuler="' + echapper(remise.url_annuler) + '">Annuler</button>';
                html += '<div class="d-flex flex-wrap align-items-center justify-content-between gap-2 small py-1">'
                    + '<span>' + remise.quantite + ' ' + echapper(remise.nom)
                    + ' a ' + echapper(remise.heure)
                    + (remise.par ? ' par ' + echapper(remise.par) : '') + '</span>'
                    + fin + '</div>';
            });
        }

        html += '<div class="small mt-2" data-avantage-message></div>';
        return html;
    }

    function afficherMessage(conteneur, reussite, texte) {
        var zone = conteneur.querySelector("[data-avantage-message]");
        if (!zone) { return; }
        zone.className = "small mt-2 " + (reussite ? "text-success" : "text-danger");
        zone.textContent = texte || "";
    }

    function envoyer(url, donnees, conteneur) {
        var corps = new FormData();
        Object.keys(donnees).forEach(function (cle) { corps.append(cle, donnees[cle]); });

        return fetch(url, {
            method: "POST",
            headers: { "X-CSRFToken": jeton(), "X-Requested-With": "XMLHttpRequest" },
            body: corps
        })
            .then(function (reponse) { return reponse.json(); })
            .then(function (reponse) {
                if (reponse.avantages) { dessiner(conteneur, reponse.avantages); }
                afficherMessage(conteneur, reponse.success, reponse.success ? reponse.message : reponse.error);
            })
            .catch(function () {
                dessiner(conteneur, conteneur._etatAvantages);
                afficherMessage(conteneur, false, "La demande n'a pas pu aboutir. Reessayez.");
            });
    }

    function dessiner(conteneur, etat) {
        conteneur._etatAvantages = etat;
        conteneur.innerHTML = rendre(etat);
    }

    function brancher(conteneur, etat) {
        if (!conteneur) { return; }
        dessiner(conteneur, etat);

        // Un seul ecouteur par conteneur : la fiche se rouvre sur un autre
        // membre sans empiler les gestes.
        if (conteneur._avantagesBranche) { return; }
        conteneur._avantagesBranche = true;

        conteneur.addEventListener("click", function (evenement) {
            var remettre = evenement.target.closest("[data-avantage-remettre]");
            var annuler = evenement.target.closest("[data-avantage-annuler]");
            var courant = conteneur._etatAvantages;

            if (remettre && courant) {
                var id = remettre.getAttribute("data-avantage-remettre");
                var champ = conteneur.querySelector('[data-avantage-quantite="' + id + '"]');
                remettre.disabled = true;
                envoyer(courant.url_remettre, { product_id: id, quantite: champ ? champ.value : 1 }, conteneur);
                return;
            }

            if (annuler) {
                var motif = window.prompt("Motif de l'annulation (erreur de saisie) :");
                if (!motif || !motif.trim()) { return; }
                annuler.disabled = true;
                envoyer(annuler.getAttribute("data-avantage-annuler"), { motif: motif.trim() }, conteneur);
            }
        });
    }

    window.Avantages = { rendre: rendre, brancher: brancher, aQuelqueChose: aQuelqueChose };
})();
