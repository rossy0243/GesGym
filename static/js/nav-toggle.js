/**
 * Toggle navigation latérale (mode réduit = logo S-C).
 * Utilisé sur toutes les pages via le header ; le style logo est géré par CSS (app-pages.css).
 */
(function() {
    var STORAGE_KEY = 'smartclub-nav-mini';

    function getNav() { return document.getElementById('mainNav'); }
    function getMiniBtn() { return document.getElementById('menu-mini-button'); }
    function getExpendBtn() { return document.getElementById('menu-expend-button'); }

    function toggleNavigation() {
        var nav = getNav();
        if (!nav) return;
        nav.classList.toggle('mini-nav');
        var isMini = nav.classList.contains('mini-nav');
        var miniBtn = getMiniBtn();
        var expendBtn = getExpendBtn();
        if (miniBtn) miniBtn.style.display = isMini ? 'none' : 'block';
        if (expendBtn) expendBtn.style.display = isMini ? 'block' : 'none';
        try { localStorage.setItem(STORAGE_KEY, isMini ? '1' : '0'); } catch (e) {}
    }

    function initNavState() {
        var nav = getNav();
        if (!nav) return;
        try {
            var saved = localStorage.getItem(STORAGE_KEY);
            if (saved === '1' && !nav.classList.contains('mini-nav')) {
                nav.classList.add('mini-nav');
                var miniBtn = getMiniBtn();
                var expendBtn = getExpendBtn();
                if (miniBtn) miniBtn.style.display = 'none';
                if (expendBtn) expendBtn.style.display = 'block';
            } else if (saved !== '1' && nav.classList.contains('mini-nav')) {
                nav.classList.remove('mini-nav');
                var miniBtn = getMiniBtn();
                var expendBtn = getExpendBtn();
                if (miniBtn) miniBtn.style.display = 'block';
                if (expendBtn) expendBtn.style.display = 'none';
            }
        } catch (e) {}
        /* S'assurer que logo-sm est caché si nav étendue (au cas où une page aurait modifié le DOM) */
        if (!nav.classList.contains('mini-nav')) {
            var logoSm = document.querySelector('.b-brand .logo-sm');
            if (logoSm) logoSm.style.display = 'none';
        }
    }

    window.toggleNavigation = toggleNavigation;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initNavState);
    } else {
        initNavState();
    }
})();
