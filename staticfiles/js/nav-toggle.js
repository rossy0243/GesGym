(function () {
    if (window.smartclubNavMounted) {
        return;
    }
    window.smartclubNavMounted = true;

    var STORAGE_KEY = 'smartclub-shell-state';
    var LEGACY_MINI_KEY = 'smartclub-nav-mini';
    var LEGACY_THEME_KEY = 'nexel-classic-dashboard-menu-mini-theme';
    var DESKTOP_BREAKPOINT = 1024;
    var resizeFrame = 0;
    var syncTimer = 0;

    function getNav() {
        return document.getElementById('mainNav');
    }

    function getMiniButton() {
        return document.getElementById('menu-mini-button');
    }

    function getExpandButton() {
        return document.getElementById('menu-expend-button');
    }

    function isDesktopViewport() {
        return window.innerWidth > DESKTOP_BREAKPOINT;
    }

    function removeNode(node) {
        if (node && node.parentNode) {
            node.parentNode.removeChild(node);
        }
    }

    function readShellState() {
        var desktopMini = false;

        try {
            var rawState = localStorage.getItem(STORAGE_KEY);

            if (rawState) {
                var parsedState = JSON.parse(rawState);
                desktopMini = Boolean(parsedState && parsedState.desktopMini);
            } else if (localStorage.getItem(LEGACY_MINI_KEY) === '1') {
                desktopMini = true;
            } else if (localStorage.getItem(LEGACY_THEME_KEY) === 'menu-mini-theme') {
                desktopMini = true;
            }
        } catch (error) {}

        return {
            desktopMini: desktopMini
        };
    }

    function persistShellState(desktopMini) {
        var nextDesktopMini = Boolean(desktopMini);

        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify({
                desktopMini: nextDesktopMini
            }));
            localStorage.setItem(LEGACY_MINI_KEY, nextDesktopMini ? '1' : '0');
            localStorage.setItem(LEGACY_THEME_KEY, nextDesktopMini ? 'menu-mini-theme' : 'menu-expend-theme');
        } catch (error) {}
    }

    function updateToggleButtons(isMini) {
        var miniButton = getMiniButton();
        var expandButton = getExpandButton();
        var miniButtonDisplay = isMini ? 'none' : 'inline-flex';
        var expandButtonDisplay = isMini ? 'inline-flex' : 'none';

        if (miniButton) {
            miniButton.style.display = miniButtonDisplay;
            miniButton.setAttribute('aria-pressed', (!isMini).toString());
        }

        if (expandButton) {
            expandButton.style.display = expandButtonDisplay;
            expandButton.setAttribute('aria-pressed', isMini.toString());
        }
    }

    function findDirectSubmenu(item) {
        if (!item) {
            return null;
        }

        for (var index = 0; index < item.children.length; index += 1) {
            var child = item.children[index];

            if (child.classList && child.classList.contains('nxl-submenu')) {
                return child;
            }
        }

        return null;
    }

    function rememberExpandedMenus() {
        var nav = getNav();

        if (!nav) {
            return;
        }

        var items = nav.querySelectorAll('.nxl-hasmenu');

        Array.prototype.forEach.call(items, function (item) {
            if (item.classList.contains('nxl-trigger')) {
                item.setAttribute('data-smartclub-was-open', '1');
            } else {
                item.removeAttribute('data-smartclub-was-open');
            }
        });
    }

    function normalizeActiveSubmenus(isMini) {
        var nav = getNav();

        if (!nav) {
            return;
        }

        var items = nav.querySelectorAll('.nxl-hasmenu');

        Array.prototype.forEach.call(items, function (item) {
            var submenu = findDirectSubmenu(item);

            if (!submenu) {
                return;
            }

            if (isMini) {
                item.classList.remove('nxl-trigger');
                submenu.style.display = 'none';
                return;
            }

            var shouldStayOpen = item.classList.contains('active') || item.getAttribute('data-smartclub-was-open') === '1';

            item.classList.toggle('nxl-trigger', shouldStayOpen);
            submenu.style.display = shouldStayOpen ? 'block' : 'none';
        });
    }

    function closeDesktopOverlays() {
        if (!isDesktopViewport()) {
            return;
        }

        var nav = getNav();

        if (nav) {
            nav.classList.remove('mob-navigation-active');
        }

        Array.prototype.forEach.call(document.querySelectorAll('.nxl-menu-overlay'), removeNode);
        Array.prototype.forEach.call(document.querySelectorAll('.hamburger.is-active'), function (hamburger) {
            hamburger.classList.remove('is-active');
        });
    }

    function applyShellState(desktopMini, options) {
        var nav = getNav();
        var html = document.documentElement;
        var nextDesktopMini = Boolean(desktopMini);
        var shouldRenderMini = isDesktopViewport() && nextDesktopMini;
        var wasMini = Boolean(nav && nav.classList.contains('mini-nav'));

        if (shouldRenderMini && !wasMini) {
            rememberExpandedMenus();
        }

        if (nav) {
            nav.classList.toggle('mini-nav', shouldRenderMini);
        }

        html.classList.toggle('minimenu', shouldRenderMini);
        updateToggleButtons(shouldRenderMini);
        normalizeActiveSubmenus(shouldRenderMini);
        closeDesktopOverlays();

        if (!(options && options.skipPersist)) {
            persistShellState(nextDesktopMini);
        }
    }

    function syncShellState() {
        var shellState = readShellState();
        applyShellState(shellState.desktopMini, {
            skipPersist: true
        });
    }

    function scheduleShellSync() {
        if (resizeFrame) {
            window.cancelAnimationFrame(resizeFrame);
        }

        if (syncTimer) {
            window.clearTimeout(syncTimer);
        }

        resizeFrame = window.requestAnimationFrame(function () {
            syncShellState();
            syncTimer = window.setTimeout(syncShellState, 0);
        });
    }

    function toggleDesktopNavigation() {
        var shellState = readShellState();
        applyShellState(!shellState.desktopMini);
    }

    function handleToggleClick(event) {
        var toggleButton = event.target.closest('[data-nav-toggle]');

        if (!toggleButton) {
            return;
        }

        event.preventDefault();
        event.stopPropagation();

        if (typeof event.stopImmediatePropagation === 'function') {
            event.stopImmediatePropagation();
        }

        if (!isDesktopViewport()) {
            return;
        }

        toggleDesktopNavigation();
    }

    function init() {
        document.addEventListener('click', handleToggleClick, true);
        window.addEventListener('resize', scheduleShellSync, {
            passive: true
        });
        window.addEventListener('orientationchange', scheduleShellSync, {
            passive: true
        });
        window.addEventListener('pageshow', scheduleShellSync);
        window.addEventListener('load', scheduleShellSync);

        scheduleShellSync();
        window.setTimeout(scheduleShellSync, 120);
    }

    window.smartclubNav = {
        sync: scheduleShellSync,
        setMini: function (nextMiniState) {
            applyShellState(Boolean(nextMiniState));
        }
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init, {
            once: true
        });
    } else {
        init();
    }
})();
