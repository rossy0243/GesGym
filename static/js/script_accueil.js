(function () {
    const clientsDB = {
        "123456": null,
        "789012": null,
        "345678": null,
    };

    const passwords = {};

    const overlay = document.getElementById("modalOverlay");
    const closeBtn = document.getElementById("closeModal");
    const registerTriggers = document.querySelectorAll('[data-open-register="true"]');
    const registerModal = document.getElementById("registerModal");
    const loginModal = document.getElementById("loginModal");
    const step1 = document.getElementById("registerStep1");
    const step2 = document.getElementById("registerStep2");
    const clientNumberInput = document.getElementById("clientNumber");
    const password1 = document.getElementById("password1");
    const password2 = document.getElementById("password2");
    const checkClientBtn = document.getElementById("checkClientBtn");
    const createAccountBtn = document.getElementById("createAccountBtn");
    const registerError = document.getElementById("registerError");
    const loginSubmitBtn = document.getElementById("loginSubmitBtn");
    const menuBtn = document.getElementById("menu-btn");
    const mobileMenu = document.getElementById("mobile-menu");

    let currentRegisterNumber = "";

    if (!overlay || !closeBtn || !registerModal || !loginModal || !step1 || !step2) {
        return;
    }

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

    function resetRegisterFlow() {
        registerError.classList.add("hidden");
        registerError.textContent = "";
        registerModal.style.display = "block";
        loginModal.style.display = "none";
        step1.style.display = "block";
        step2.style.display = "none";
        clientNumberInput.value = "";
        password1.value = "";
        password2.value = "";
    }

    function openRegisterModal() {
        overlay.classList.add("active");
        document.body.classList.add("modal-open");
        resetRegisterFlow();
        closeMobileMenu();
    }

    function closeModal() {
        overlay.classList.remove("active");
        document.body.classList.remove("modal-open");
        registerModal.style.display = "none";
        loginModal.style.display = "none";
        registerError.classList.add("hidden");
    }

    registerTriggers.forEach((trigger) => {
        trigger.addEventListener("click", (event) => {
            event.preventDefault();
            openRegisterModal();
        });
    });

    closeBtn.addEventListener("click", closeModal);

    overlay.addEventListener("click", (event) => {
        if (event.target === overlay) {
            closeModal();
        }
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && overlay.classList.contains("active")) {
            closeModal();
        }
    });

    if (checkClientBtn) {
        checkClientBtn.addEventListener("click", () => {
            const num = clientNumberInput.value.trim();

            if (!num) {
                registerError.textContent = "Veuillez saisir un numero.";
                registerError.classList.remove("hidden");
                return;
            }

            if (Object.prototype.hasOwnProperty.call(clientsDB, num)) {
                currentRegisterNumber = num;
                step1.style.display = "none";
                step2.style.display = "block";
                registerError.classList.add("hidden");
                return;
            }

            registerError.textContent = "Numero client inconnu.";
            registerError.classList.remove("hidden");
        });
    }

    if (createAccountBtn) {
        createAccountBtn.addEventListener("click", () => {
            const pwd1 = password1.value;
            const pwd2 = password2.value;

            if (!pwd1 || !pwd2) {
                registerError.textContent = "Veuillez remplir les mots de passe.";
                registerError.classList.remove("hidden");
                return;
            }

            if (pwd1 !== pwd2) {
                registerError.textContent = "Les mots de passe ne correspondent pas.";
                registerError.classList.remove("hidden");
                return;
            }

            if (pwd1.length < 3) {
                registerError.textContent = "Le mot de passe doit contenir au moins 3 caracteres.";
                registerError.classList.remove("hidden");
                return;
            }

            passwords[currentRegisterNumber] = pwd1;

            Swal.fire({
                icon: "success",
                title: "Compte cree !",
                text: "Votre compte a ete cree avec succes. Vous pouvez maintenant vous connecter.",
                timer: 2000,
                showConfirmButton: true,
            }).then(() => {
                closeModal();
            });
        });
    }

    if (loginSubmitBtn) {
        loginSubmitBtn.addEventListener("click", (event) => {
            event.preventDefault();
        });
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

        const mobileLinks = mobileMenu.querySelectorAll("nav > a");
        mobileLinks.forEach((link) => {
            link.addEventListener("click", () => {
                closeMobileMenu();
            });
        });
    }

    document.querySelectorAll('a[href^="#"]').forEach((anchor) => {
        anchor.addEventListener("click", function (event) {
            if (this.dataset.openRegister === "true") {
                return;
            }
            event.preventDefault();
            const targetId = this.getAttribute("href");
            if (targetId === "#") {
                return;
            }
            const targetElement = document.querySelector(targetId);
            if (targetElement) {
                targetElement.scrollIntoView({ behavior: "smooth", block: "start" });
            }
        });
    });
})();
