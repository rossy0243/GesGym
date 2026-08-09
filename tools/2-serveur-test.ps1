<#
    ETAPE 2 - Serveur GesGym pour le test du lecteur.

    Demarre Django en acceptant l'adresse 192.0.0.100, celle par laquelle le
    lecteur viendra deposer ses evenements.

    Laisse cette fenetre OUVERTE pendant tous les tests : chaque scan s'y
    affiche en direct, et tout est aussi enregistre dans
    tools\journal-serveur.txt

    Pour arreter : Ctrl+C
#>

$ErrorActionPreference = "Continue"

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$journal = Join-Path $PSScriptRoot "journal-serveur.txt"

if (-not (Test-Path $python)) {
    Write-Host "Python introuvable : $python" -ForegroundColor Red
    exit 1
}

$env:DJANGO_ALLOWED_HOSTS = "127.0.0.1,localhost,192.168.1.71,192.0.0.100"

Write-Host ""
Write-Host "=== SERVEUR DE TEST GESGYM ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Interface  : http://127.0.0.1:8000"
Write-Host "Identifiant: test-lecteur"
Write-Host ""
Write-Host "URL webhook a saisir dans le lecteur :" -ForegroundColor Yellow

& $python (Join-Path $projectRoot "manage.py") shell -c @"
from access.models import AccessDevice
device = AccessDevice.objects.first()
if device:
    print('  http://192.0.0.100:8000/access/devices/webhook/%s/' % device.webhook_token)
else:
    print('  AUCUN LECTEUR ENREGISTRE')
"@

Write-Host ""
Write-Host "Journal : $journal"
Write-Host "Laisse cette fenetre ouverte. Ctrl+C pour arreter."
Write-Host ""

Set-Location $projectRoot
& $python manage.py runserver 0.0.0.0:8000 2>&1 | Tee-Object -FilePath $journal
