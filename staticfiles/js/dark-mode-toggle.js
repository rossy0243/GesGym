/**
 * Gestion du mode sombre / clair (HAUT-SHOP)
 * Applique le thème au chargement et au clic sur les boutons lune/soleil.
 */
(function() {
    var STORAGE_KEY = 'app-skin-dark';

    function applyDarkMode(isDark) {
        var html = document.documentElement;
        var darkBtn = document.querySelector('.dark-light-theme .dark-button');
        var lightBtn = document.querySelector('.dark-light-theme .light-button');
        if (isDark) {
            html.classList.add('app-skin-dark');
            if (darkBtn) { darkBtn.style.display = 'none'; }
            if (lightBtn) { lightBtn.style.display = ''; }
        } else {
            html.classList.remove('app-skin-dark');
            if (darkBtn) { darkBtn.style.display = ''; }
            if (lightBtn) { lightBtn.style.display = 'none'; }
        }
    }

    function init() {
        try {
            var saved = localStorage.getItem(STORAGE_KEY);
            var isDark = (saved === 'app-skin-dark');
            applyDarkMode(isDark);
        } catch (e) {}
    }

    function bindClicks() {
        document.addEventListener('click', function(e) {
            var target = e.target.closest('.dark-light-theme');
            if (!target) return;
            var darkBtn = target.querySelector('.dark-button');
            var lightBtn = target.querySelector('.light-button');
            if (e.target.closest('.dark-button')) {
                e.preventDefault();
                try { localStorage.setItem(STORAGE_KEY, 'app-skin-dark'); } catch (err) {}
                applyDarkMode(true);
            } else if (e.target.closest('.light-button')) {
                e.preventDefault();
                try { localStorage.setItem(STORAGE_KEY, 'app-skin-light'); } catch (err) {}
                applyDarkMode(false);
            }
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() {
            init();
            bindClicks();
        });
    } else {
        init();
        bindClicks();
    }
})();
