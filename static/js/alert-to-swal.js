/**
 * Remplace les alert() natifs par SweetAlert2 (Swal) pour un affichage plus moderne.
 * Inclure ce script APRÈS sweetalert2.
 */
(function() {
    if (typeof Swal === 'undefined') return;
    var _alert = window.alert;
    window.alert = function(msg) {
        if (msg === null || msg === undefined) msg = '';
        var text = String(msg);
        var isSuccess = /succès|enregistré|ajouté|modifié|effectué|créé|mise à jour/i.test(text);
        var isError = /erreur|échec|insuffisant|invalide|obligatoire|veuillez/i.test(text);
        var icon = isSuccess ? 'success' : (isError ? 'error' : 'info');
        Swal.fire({
            icon: icon,
            title: icon === 'success' ? 'Succès' : (icon === 'error' ? 'Attention' : 'Information'),
            text: text,
            confirmButtonColor: '#3454d1'
        });
    };
})();
