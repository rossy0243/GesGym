let html5QrCode

function openScannerModal(){

    let modal = new bootstrap.Modal(
        document.getElementById("scannerModal")
    )

    modal.show()

    setTimeout(startScanner,500)

}

function startScanner(){

    scanner = new Html5Qrcode("reader")

    scanner.start(
        { facingMode: "environment" },
        { fps: 10, qrbox: 250 },
        onScanSuccess
    )

}


function onScanSuccess(decodedText){

    scanner.stop()

    fetch(`/core/access/${decodedText}/`)
    .then(res => res.json())
    .then(data => {

        let result = document.getElementById("scanResult")

        let color = data.access ? "success" : "danger"

        result.innerHTML = `
            <div class="alert alert-${color} text-center">

                <h4>${data.member}</h4>

                <p>${data.access ? "Accès autorisé" : "Accès refusé"}</p>

                ${data.reason ? `<small>${data.reason}</small>` : ""}

            </div>
        `

        result.style.display = "block"

        document.getElementById("todayEntries").innerText = data.stats.entries
        document.getElementById("todayDenied").innerText = data.stats.denied

    })

}
function displayScanResult(data){

    let result = document.getElementById("scanResult")

    result.style.display = "block"

    if(data.access){

        result.innerHTML = `
        <div class="alert alert-success text-center">

            <h4>Accès autorisé</h4>

            <strong>${data.member}</strong>

        </div>
        `

    }else{

        result.innerHTML = `
        <div class="alert alert-danger text-center">

            <h4>Accès refusé</h4>

            ${data.reason}

        </div>
        `

    }

}

function search_members(){

    let query = document.getElementById("manuelSearch").value

    if(query.length < 2){
        document.getElementById("manuelResults").innerHTML=""
        return
    }

    fetch(`/core/access/manual/search/?q=${query}`)
    .then(res=>res.json())
    .then(data=>{

        let container = document.getElementById("manuelResults")

        container.innerHTML=""

        data.members.forEach(member=>{

            container.innerHTML += `

            <div class="d-flex align-items-center p-2 border-bottom member-result"
                onclick="loadMemberDetails(${member.id})">

                <img src="${member.photo}" 
                     width="40" 
                     class="rounded-circle me-2">

                <div>

                    <strong>${member.name}</strong>

                    <div class="text-muted small">${member.phone}</div>

                </div>

            </div>
            `
        })

    })

}

function member_detail(memberId){

    fetch(`/core/access/manual/member/${memberId}/`)
    .then(res=>res.json())
    .then(data=>{

        document.getElementById("manuelClientDetails").innerHTML = `

        <div class="text-center">

            <img src="${data.photo}" 
                 width="80"
                 class="rounded-circle mb-2">

            <h5>${data.name}</h5>

            <p class="text-muted">${data.phone}</p>

            <span class="badge bg-success">
                ${data.status}
            </span>

            <div class="mt-3">

                <button class="btn btn-success"
                        onclick="confirmManualAccess(${data.id})">

                    Autoriser l'entrée

                </button>

            </div>

        </div>
        `

    })

}

function confirmManualAccess(memberId){

    fetch(`/core/access/manual/entry/${memberId}/`)
    .then(res=>res.json())
    .then(data=>{

        if(data.access){

            alert("Accès autorisé")

        }else{

            alert("Accès refusé")

        }

    })

}