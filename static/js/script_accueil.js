(function () {
    var menuBtn = document.getElementById("menu-btn");
    var mobileMenu = document.getElementById("mobile-menu");

    function updateMenuIcon(isOpen) {
        if (!menuBtn) {
            return;
        }
        var icon = menuBtn.querySelector("i");
        if (!icon) {
            return;
        }
        if (isOpen) {
            icon.classList.remove("fa-bars");
            icon.classList.add("fa-times");
        } else {
            icon.classList.remove("fa-times");
            icon.classList.add("fa-bars");
        }
    }

    function closeMobileMenu() {
        if (!mobileMenu) {
            return;
        }
        mobileMenu.classList.remove("open");
        if (menuBtn) {
            menuBtn.setAttribute("aria-expanded", "false");
        }
        updateMenuIcon(false);
    }

    function toggleLandingMenu() {
        if (!mobileMenu) {
            return false;
        }
        var isOpen = mobileMenu.classList.toggle("open");
        if (menuBtn) {
            menuBtn.setAttribute("aria-expanded", isOpen ? "true" : "false");
        }
        updateMenuIcon(isOpen);
        return false;
    }

    window.toggleLandingMenu = toggleLandingMenu;

    if (menuBtn && mobileMenu) {
        menuBtn.addEventListener("click", function (event) {
            event.preventDefault();
            toggleLandingMenu();
        });

        var mobileLinks = mobileMenu.querySelectorAll("a");
        for (var i = 0; i < mobileLinks.length; i += 1) {
            mobileLinks[i].addEventListener("click", function () {
                closeMobileMenu();
            });
        }
    }

    var elements = document.querySelectorAll(".animate-on-scroll");
    if (elements.length && "IntersectionObserver" in window) {
        var observer = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (entry.isIntersecting) {
                    entry.target.classList.add("visible");
                    observer.unobserve(entry.target);
                }
            });
        }, { threshold: 0.2, rootMargin: "0px 0px -50px 0px" });

        for (var j = 0; j < elements.length; j += 1) {
            observer.observe(elements[j]);
        }
    } else if (elements.length) {
        for (var k = 0; k < elements.length; k += 1) {
            elements[k].classList.add("visible");
        }
    }

    var anchors = document.querySelectorAll('a[href^="#"]');
    for (var a = 0; a < anchors.length; a += 1) {
        anchors[a].addEventListener("click", function (event) {
            var targetId = this.getAttribute("href");
            if (!targetId || targetId === "#") {
                return;
            }
            var targetElement = document.querySelector(targetId);
            if (targetElement) {
                event.preventDefault();
                targetElement.scrollIntoView({ behavior: "smooth", block: "start" });
            }
        });
    }
})();
