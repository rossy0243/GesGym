(function () {
    const body = document.body;
    const serviceWorkerUrl = body ? body.dataset.serviceWorkerUrl : "";
    const installButton = document.getElementById("installAppBtn");
    const toast = document.getElementById("copyToast");
    let deferredInstallPrompt = null;
    let toastTimer = null;

    function showToast(message) {
        if (!toast) return;
        toast.textContent = message;
        toast.classList.add("is-visible");
        window.clearTimeout(toastTimer);
        toastTimer = window.setTimeout(function () {
            toast.classList.remove("is-visible");
        }, 1800);
    }

    if ("serviceWorker" in navigator && serviceWorkerUrl) {
        window.addEventListener("load", function () {
            navigator.serviceWorker.register(serviceWorkerUrl, { scope: "/members/" }).catch(function () {});
        });
    }

    window.addEventListener("beforeinstallprompt", function (event) {
        event.preventDefault();
        deferredInstallPrompt = event;
        if (installButton) {
            installButton.hidden = false;
        }
    });

    if (installButton) {
        installButton.addEventListener("click", async function () {
            if (!deferredInstallPrompt) {
                showToast("Installation indisponible sur ce navigateur");
                return;
            }

            deferredInstallPrompt.prompt();
            await deferredInstallPrompt.userChoice.catch(function () {});
            deferredInstallPrompt = null;
            installButton.hidden = true;
        });
    }

    document.querySelectorAll("[data-copy]").forEach(function (button) {
        button.addEventListener("click", function () {
            const value = button.getAttribute("data-copy") || "";
            if (!value) return;

            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(value).then(function () {
                    showToast("Identifiant copie");
                }).catch(function () {
                    showToast("Copie impossible");
                });
                return;
            }

            const input = document.createElement("input");
            input.value = value;
            input.setAttribute("readonly", "readonly");
            input.style.position = "fixed";
            input.style.opacity = "0";
            document.body.appendChild(input);
            input.select();
            try {
                document.execCommand("copy");
                showToast("Identifiant copie");
            } catch (error) {
                showToast("Copie impossible");
            }
            document.body.removeChild(input);
        });
    });

    if (window.matchMedia("(display-mode: standalone)").matches && installButton) {
        installButton.hidden = true;
    }
})();
