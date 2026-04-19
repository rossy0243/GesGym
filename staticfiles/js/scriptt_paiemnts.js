function searchClient() {

    const query = document.getElementById("clientSearch").value;

    if (query.length < 2) {
        document.getElementById("searchResults").style.display = "none";
        return;
    }

    fetch(`/core/search-members/?q=${query}`)
    .then(res => res.json())
    .then(data => {

        const box = document.getElementById("searchResults");
        box.innerHTML = "";

        if (data.members.length === 0) {
            box.innerHTML = "<div class='p-2 text-muted'>Aucun client trouvé</div>";
            box.style.display = "block";
            return;
        }

        data.members.forEach(member => {

            const item = document.createElement("div");
            item.className = "p-2 border-bottom client-item";

            item.innerHTML =
                "<strong>" + member.name + "</strong><br>" +
                "<small>" + member.phone + "</small>";

            item.onclick = function () {
                chooseClient(member);
            };

            box.appendChild(item);

        });

        box.style.display = "block";
    });
}

function chooseClient(member) {

    selectedClient = member;

    document.getElementById("clientSearch").value = member.name;
    document.getElementById("searchResults").style.display = "none";

    document.getElementById("clientName").innerText = member.name;
    document.getElementById("clientStatus").innerText = member.status;

    document.getElementById("clientCard").style.display = "block";
    document.getElementById("formuleSection").style.display = "block";
}

