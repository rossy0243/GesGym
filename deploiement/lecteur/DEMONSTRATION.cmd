@echo off
setlocal
cd /d "%~dp0"

rem Lanceur de la demonstration. Pas besoin des droits administrateur :
rem rien n'est installe, le tunnel vit le temps de la fenetre.

echo ================================================
echo   RoyalGym - tunnel de demonstration
echo ================================================
echo.
echo Laissez cette fenetre ouverte pendant le test.
echo Fermez-la des que le test est fait : tant qu'elle
echo tourne, le lecteur est joignable depuis internet.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tunnel-demo.ps1" %*

echo.
echo Tunnel ferme.
echo Appuyez sur une touche pour fermer cette fenetre.
pause >nul
