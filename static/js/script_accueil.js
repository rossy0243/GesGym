(function () {
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
