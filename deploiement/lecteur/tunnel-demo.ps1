<#
    Tunnel de demonstration - adresse jetable, aucun compte, aucun domaine.

    A lancer sur une machine du reseau de la salle pour verifier, en quelques
    minutes, que l'application en ligne peut piloter le lecteur. L'adresse
    obtenue change a chaque demarrage : cette methode sert a prouver, jamais a
    installer.

    ATTENTION : pendant que ce script tourne, l'interface d'administration du
    lecteur est joignable par toute personne connaissant l'adresse. Fermez la
    fenetre des que le test est fait.

    Usage :
        .\tunnel-demo.ps1
        .\tunnel-demo.ps1 -Lecteur 192.168.1.50
#>

param(
    [string]$Lecteur = "192.168.1.188",
    [int]$Port = 80
)

$ErrorActionPreference = "Stop"

$dossier = Join-Path $env:LOCALAPPDATA "RoyalGym\tunnel"
$exe = Join-Path $dossier "cloudflared.exe"

if (-not (Test-Path $dossier)) {
    New-Item -ItemType Directory -Force -Path $dossier | Out-Null
}

if (-not (Test-Path $exe)) {
    Write-Host "Telechargement de cloudflared (environ 55 Mo)..." -ForegroundColor Cyan
    $source = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
    Invoke-WebRequest -Uri $source -OutFile $exe -UseBasicParsing
    Write-Host "Telecharge." -ForegroundColor Green
}

Write-Host ""
Write-Host "Verification du lecteur sur $Lecteur port $Port..." -ForegroundColor Cyan
$liaison = Test-NetConnection -ComputerName $Lecteur -Port $Port -WarningAction SilentlyContinue

if (-not $liaison.TcpTestSucceeded) {
    Write-Host ""
    Write-Host "Le lecteur ne repond pas sur $Lecteur : $Port." -ForegroundColor Red
    Write-Host "Verifiez qu'il est allume et que cette machine est sur le meme reseau."
    Write-Host "Son adresse est affichee sur sa fiche dans l'application."
    exit 1
}

Write-Host "Le lecteur repond." -ForegroundColor Green
Write-Host ""
Write-Host "Ouverture du tunnel. Reperez la ligne contenant trycloudflare.com :" -ForegroundColor Cyan
Write-Host "c'est l'adresse a saisir dans la fiche du lecteur, avec le port 443"
Write-Host "et la case 'Lecteur joint par un tunnel (HTTPS)' cochee."
Write-Host ""
Write-Host "Fermez cette fenetre pour couper le tunnel." -ForegroundColor Yellow
Write-Host ""

& $exe tunnel --url "http://${Lecteur}:${Port}" --no-autoupdate
