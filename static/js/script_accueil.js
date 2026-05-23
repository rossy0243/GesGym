(function () {
    const menuBtn = document.getElementById("menu-btn");
    const mobileMenu = document.getElementById("mobile-menu");

    function closeMobileMenu() {
        if (!mobileMenu || !menuBtn) {
            return;
        }
        mobileMenu.classList.remove("open");
        const icon = menuBtn.querySelector("i");
        if (icon) {
            icon.classList.remove("fa-times");
            icon.classList.add("fa-bars");
        }
    }

    const elements = document.querySelectorAll(".animate-on-scroll");
    if (elements.length) {
        const observer = new IntersectionObserver(
            (entries) => {
                entries.forEach((entry) => {
                    if (entry.isIntersecting) {
                        entry.target.classList.add("visible");
                        observer.unobserve(entry.target);
                    }
                });
            },
            { threshold: 0.2, rootMargin: "0px 0px -50px 0px" }
        );
        elements.forEach((element) => observer.observe(element));
    }

    if (menuBtn && mobileMenu) {
        menuBtn.addEventListener("click", () => {
            mobileMenu.classList.toggle("open");
            const icon = menuBtn.querySelector("i");
            if (!icon) {
                return;
            }
            if (mobileMenu.classList.contains("open")) {
                icon.classList.remove("fa-bars");
                icon.classList.add("fa-times");
            } else {
                icon.classList.remove("fa-times");
                icon.classList.add("fa-bars");
            }
        });

        const mobileLinks = mobileMenu.querySelectorAll("nav > a, .mobile-auth-buttons a");
        mobileLinks.forEach((link) => {
            link.addEventListener("click", () => {
                closeMobileMenu();
            });
        });
    }

    document.querySelectorAll('a[href^="#"]').forEach((anchor) => {
        anchor.addEventListener("click", function (event) {
            const targetId = this.getAttribute("href");
            if (!targetId || targetId === "#") {
                return;
            }
            const targetElement = document.querySelector(targetId);
            if (targetElement) {
                event.preventDefault();
                targetElement.scrollIntoView({ behavior: "smooth", block: "start" });
            }
        });
    });
})();
