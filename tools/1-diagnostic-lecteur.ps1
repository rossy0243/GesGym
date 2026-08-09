<#
    ETAPE 1 - Diagnostic du lecteur Hikvision.

    A lancer APRES avoir ferme Proton VPN.
    Ne modifie rien : verifie le reseau et interroge le lecteur.
    Tout est enregistre dans tools\rapport-lecteur.txt
#>

$ErrorActionPreference = "Continue"

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$rapport = Join-Path $PSScriptRoot "rapport-lecteur.txt"

Start-Transcript -Path $rapport -Force | Out-Null

Write-Host ""
Write-Host "=== DIAGNOSTIC LECTEUR HIKVISION ===" -ForegroundColor Cyan
Write-Host "Date : $(Get-Date -Format 'dd/MM/yyyy HH:mm:ss')"
Write-Host ""

# --- 1. Proton VPN doit etre ferme -----------------------------------------
Write-Host "--- 1. Etat du VPN ---" -ForegroundColor Yellow
$protonProcs = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match "Proton" })
$protun = Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object { $_.Name -eq "ProTUN" -and $_.Status -eq "Up" }

if ($protonProcs.Count -gt 0 -or $protun) {
    Write-Host "ECHEC : Proton VPN est encore actif." -ForegroundColor Red
    Write-Host "  Processus Proton : $($protonProcs.Count)"
    Write-Host "  Adaptateur ProTUN actif : $([bool]$protun)"
    Write-Host ""
    Write-Host "  Ferme Proton (Settings > Kill switch > desactiver, puis Quit)"
    Write-Host "  et relance ce script. Les tests ne peuvent pas aboutir sinon."
    Stop-Transcript | Out-Null
    exit 1
}
Write-Host "OK : aucun VPN actif." -ForegroundColor Green
Write-Host ""

# --- 2. Adresse dans le sous-reseau du lecteur ------------------------------
Write-Host "--- 2. Adresse IP de test ---" -ForegroundColor Yellow
$alias = "Ethernet"
$ip = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
      Where-Object { $_.IPAddress -eq "192.0.0.100" }

if (-not $ip) {
    Write-Host "192.0.0.100 absente, ajout sur '$alias'..."
    try {
        New-NetIPAddress -InterfaceAlias $alias -IPAddress 192.0.0.100 -PrefixLength 24 -ErrorAction Stop | Out-Null
        Write-Host "OK : adresse ajoutee." -ForegroundColor Green
        Start-Sleep -Seconds 2
    } catch {
        Write-Host "ECHEC : $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "  Relance ce script dans un PowerShell EN ADMINISTRATEUR."
        Stop-Transcript | Out-Null
        exit 1
    }
} else {
    Write-Host "OK : 192.0.0.100 deja presente sur '$($ip.InterfaceAlias)'." -ForegroundColor Green
}
Write-Host ""

# --- 3. Le lecteur repond-il ? ---------------------------------------------
Write-Host "--- 3. Joignabilite du lecteur (192.0.0.64) ---" -ForegroundColor Yellow
$ping = Test-Connection -ComputerName 192.0.0.64 -Count 2 -Quiet -ErrorAction SilentlyContinue
Write-Host "Ping : $ping"
$http = Test-NetConnection -ComputerName 192.0.0.64 -Port 80 -InformationLevel Quiet -WarningAction SilentlyContinue
Write-Host "Port 80 : $http"

if (-not $http) {
    Write-Host "ECHEC : le lecteur ne repond pas sur le port 80." -ForegroundColor Red
    Write-Host "  Verifie qu'il est alimente et que le cable RJ45 est branche."
    Stop-Transcript | Out-Null
    exit 1
}
Write-Host "OK : le lecteur repond." -ForegroundColor Green
Write-Host ""

# --- 4. Inventaire ISAPI ----------------------------------------------------
Write-Host "--- 4. Capacites du lecteur (ISAPI) ---" -ForegroundColor Yellow
Write-Host "C'est la partie que je dois analyser a ton retour."
Write-Host ""

& $python (Join-Path $projectRoot "manage.py") shell -c @"
from access.models import AccessDevice
from access import hikvision

device = AccessDevice.objects.first()
if not device:
    print('AUCUN LECTEUR ENREGISTRE DANS L APPLICATION')
    raise SystemExit

client = hikvision.HikvisionClient.from_device(device, timeout=10)

endpoints = [
    '/ISAPI/System/deviceInfo',
    '/ISAPI/System/capabilities',
    '/ISAPI/AccessControl/capabilities',
    '/ISAPI/AccessControl/AcsEvent/capabilities?format=json',
    '/ISAPI/AccessControl/UserInfo/capabilities?format=json',
    '/ISAPI/AccessControl/CardInfo/capabilities?format=json',
    '/ISAPI/AccessControl/QRCodeConfig/capabilities?format=json',
    '/ISAPI/AccessControl/Configuration/capabilities?format=json',
    '/ISAPI/AccessControl/verifyMode/capabilities?format=json',
    '/ISAPI/AccessControl/Door/param/1',
    '/ISAPI/Event/notification/httpHosts',
    '/ISAPI/Event/notification/httpHosts/capabilities',
    '/ISAPI/Event/triggersCap',
]

for path in endpoints:
    print('=' * 72)
    print(path)
    print('=' * 72)
    try:
        print(client.request(path)[:3000])
    except Exception as exc:
        print('ERREUR:', type(exc).__name__, exc)
    print()

print('URL WEBHOOK A SAISIR DANS LE LECTEUR :')
print('http://192.0.0.100:8000/access/devices/webhook/%s/' % device.webhook_token)
"@

Write-Host ""
Write-Host "=== TERMINE ===" -ForegroundColor Cyan
Write-Host "Rapport enregistre dans : $rapport"
Write-Host "Passe a l'etape 2 : tools\2-serveur-test.ps1"
Write-Host ""

Stop-Transcript | Out-Null
