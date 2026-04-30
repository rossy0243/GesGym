$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $pythonExe)) {
    throw "Python virtuel introuvable : $pythonExe"
}

$localIPv4 = Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object {
        $_.IPAddress -like "192.168.*" -or
        $_.IPAddress -like "10.*" -or
        $_.IPAddress -like "172.16.*" -or
        $_.IPAddress -like "172.17.*" -or
        $_.IPAddress -like "172.18.*" -or
        $_.IPAddress -like "172.19.*" -or
        $_.IPAddress -like "172.2*" -or
        $_.IPAddress -like "172.30.*" -or
        $_.IPAddress -like "172.31.*"
    } |
    Select-Object -First 1 -ExpandProperty IPAddress

if (-not $localIPv4) {
    throw "Impossible de detecter une adresse IPv4 locale privee."
}

$allowedHosts = @("127.0.0.1", "localhost", $localIPv4) -join ","
$env:DJANGO_ALLOWED_HOSTS = $allowedHosts

Write-Host "Demarrage Django sur 0.0.0.0:8000"
Write-Host "Acces local   : http://127.0.0.1:8000"
Write-Host "Acces mobile  : http://$localIPv4`:8000"
Write-Host "ALLOWED_HOSTS : $allowedHosts"

& $pythonExe manage.py runserver 0.0.0.0:8000
