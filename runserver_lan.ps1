$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $pythonExe)) {
    throw "Python virtuel introuvable : $pythonExe"
}

# Adresse locale a annoncer. On prend celle qui porte la route par defaut
# plutot que la premiere adresse privee trouvee : une machine a souvent
# plusieurs interfaces, et l'ancienne detection choisissait parfois celle du
# tunnel VPN, injoignable depuis un telephone ou un lecteur du reseau local.
$routeParDefaut = Get-NetRoute -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue |
    Sort-Object RouteMetric |
    Select-Object -First 1

$adressesCandidates = Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object {
        $_.IPAddress -notlike "127.*" -and
        $_.IPAddress -notlike "169.254.*" -and
        # Interfaces de tunnel : Proton, OpenVPN, WireGuard, Tailscale...
        $_.InterfaceAlias -notmatch "ProTUN|VPN|TAP|WireGuard|Tailscale|Loopback"
    }

$localIPv4 = $null
if ($routeParDefaut) {
    $localIPv4 = $adressesCandidates |
        Where-Object { $_.InterfaceIndex -eq $routeParDefaut.InterfaceIndex } |
        Select-Object -First 1 -ExpandProperty IPAddress
}

if (-not $localIPv4) {
    $localIPv4 = $adressesCandidates | Select-Object -First 1 -ExpandProperty IPAddress
}

if (-not $localIPv4) {
    throw "Impossible de detecter une adresse IPv4 locale utilisable."
}

$allowedHosts = @("127.0.0.1", "localhost", $localIPv4) -join ","
$env:DJANGO_ALLOWED_HOSTS = $allowedHosts

# Les liens envoyes par e-mail et affiches dans l'application doivent pointer
# vers cette adresse, sinon un lien vers 127.0.0.1 arrive sur le telephone du
# membre et ne s'ouvre pas.
if (-not $env:DJANGO_PUBLIC_BASE_URL) {
    $env:DJANGO_PUBLIC_BASE_URL = "http://${localIPv4}:8000"
}

Write-Host "Demarrage Django sur 0.0.0.0:8000"
Write-Host "Acces local     : http://127.0.0.1:8000"
Write-Host "Acces reseau    : http://${localIPv4}:8000"
Write-Host "ALLOWED_HOSTS   : $allowedHosts"
Write-Host ""

# Les interfaces ecartees sont listees : si l'acces mobile ne marche pas,
# on voit tout de suite si l'adresse retenue est la bonne.
$ecartees = Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object {
        $_.IPAddress -notlike "127.*" -and
        $_.IPAddress -ne $localIPv4
    }
if ($ecartees) {
    Write-Host "Autres adresses de cette machine, non annoncees :"
    foreach ($a in $ecartees) {
        Write-Host ("   {0,-16} {1}" -f $a.IPAddress, $a.InterfaceAlias)
    }
    Write-Host ""
}

& $pythonExe manage.py runserver 0.0.0.0:8000
