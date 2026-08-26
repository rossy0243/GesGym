<#
    Tunnel permanent - adresse fixe, service Windows, redemarrage automatique.

    A lancer une seule fois par salle, en administrateur, sur la machine qui
    reste allumee. Le tunnel repart tout seul apres une coupure de courant.

    Prealable : le domaine technique doit etre gere par Cloudflare. Ce n'est
    pas le domaine du site : prenez-en un separement, il n'est jamais vu par
    les membres, et le site de production n'est jamais touche.

    Usage, en PowerShell administrateur :
        .\tunnel-permanent.ps1 -Salle royal -Domaine exemple-technique.com
        .\tunnel-permanent.ps1 -Salle royal -Domaine exemple-technique.com -Lecteur 192.168.1.50
#>

param(
    [Parameter(Mandatory = $true)][string]$Salle,
    [Parameter(Mandatory = $true)][string]$Domaine,
    [string]$Lecteur = "192.168.1.188",
    [int]$Port = 80
)

$ErrorActionPreference = "Stop"

$identite = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $identite.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Ce script doit etre lance dans un PowerShell administrateur." -ForegroundColor Red
    Write-Host "Clic droit sur PowerShell, puis 'Executer en tant qu'administrateur'."
    exit 1
}

$nomTunnel = "royalgym-$Salle"
$hote = "$Salle.$Domaine"
$dossier = Join-Path $env:LOCALAPPDATA "RoyalGym\tunnel"
$exe = Join-Path $dossier "cloudflared.exe"
$configuration = Join-Path $env:USERPROFILE ".cloudflared\config.yml"

if (-not (Test-Path $dossier)) {
    New-Item -ItemType Directory -Force -Path $dossier | Out-Null
}

if (-not (Test-Path $exe)) {
    Write-Host "Telechargement de cloudflared (environ 55 Mo)..." -ForegroundColor Cyan
    $source = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
    Invoke-WebRequest -Uri $source -OutFile $exe -UseBasicParsing
}

Write-Host ""
Write-Host "Verification du lecteur sur $Lecteur port $Port..." -ForegroundColor Cyan
$liaison = Test-NetConnection -ComputerName $Lecteur -Port $Port -WarningAction SilentlyContinue
if (-not $liaison.TcpTestSucceeded) {
    Write-Host "Le lecteur ne repond pas sur $Lecteur : $Port. Installation interrompue." -ForegroundColor Red
    exit 1
}
Write-Host "Le lecteur repond." -ForegroundColor Green

# --- 1. Autorisation Cloudflare -------------------------------------------
# Ouvre le navigateur. Choisissez le domaine technique dans la liste.
$certificat = Join-Path $env:USERPROFILE ".cloudflared\cert.pem"
if (-not (Test-Path $certificat)) {
    Write-Host ""
    Write-Host "Autorisation Cloudflare : votre navigateur va s'ouvrir." -ForegroundColor Cyan
    Write-Host "Selectionnez le domaine $Domaine, puis revenez ici."
    & $exe tunnel login
}

# --- 2. Creation du tunnel -------------------------------------------------
$existants = & $exe tunnel list 2>&1 | Out-String
if ($existants -match [regex]::Escape($nomTunnel)) {
    Write-Host "Le tunnel $nomTunnel existe deja, il est reutilise." -ForegroundColor Yellow
} else {
    Write-Host "Creation du tunnel $nomTunnel..." -ForegroundColor Cyan
    & $exe tunnel create $nomTunnel
}

# --- 3. Fichier de configuration -------------------------------------------
# Le tunnel ne publie qu'une seule chose : le lecteur. Tout le reste est
# refuse par la regle finale.
$contenu = @"
tunnel: $nomTunnel
credentials-file: $env:USERPROFILE\.cloudflared\$nomTunnel.json

ingress:
  - hostname: $hote
    service: http://${Lecteur}:${Port}
  - service: http_status:404
"@

$dossierConfig = Split-Path $configuration -Parent
if (-not (Test-Path $dossierConfig)) {
    New-Item -ItemType Directory -Force -Path $dossierConfig | Out-Null
}
Set-Content -Path $configuration -Value $contenu -Encoding utf8
Write-Host "Configuration ecrite dans $configuration" -ForegroundColor Green

# --- 4. Nom public ----------------------------------------------------------
Write-Host "Association de $hote au tunnel..." -ForegroundColor Cyan
& $exe tunnel route dns $nomTunnel $hote

# --- 5. Service Windows -----------------------------------------------------
# Sans service, le tunnel meurt avec la session : apres une coupure de
# courant, personne ne penserait a le relancer.
$service = Get-Service -Name "cloudflared" -ErrorAction SilentlyContinue
if ($service) {
    Write-Host "Service deja installe, redemarrage..." -ForegroundColor Yellow
    Restart-Service -Name "cloudflared"
} else {
    Write-Host "Installation du service Windows..." -ForegroundColor Cyan
    & $exe service install
    Start-Service -Name "cloudflared"
}

Set-Service -Name "cloudflared" -StartupType Automatic

Write-Host ""
Write-Host "Termine." -ForegroundColor Green
Write-Host ""
Write-Host "Dans l'application, ouvrez la fiche du lecteur, cliquez Modifier :"
Write-Host "   Adresse ou nom d'hote : $hote"
Write-Host "   Port                  : 443"
Write-Host "   Lecteur joint par un tunnel (HTTPS) : coche"
Write-Host "   Mot de passe          : laisser vide"
Write-Host ""
Write-Host "Puis protegez ce nom par un jeton Cloudflare Access - voir LISEZMOI.md."
Write-Host "Sans ce jeton, le lecteur reste joignable par qui connait l'adresse." -ForegroundColor Yellow
