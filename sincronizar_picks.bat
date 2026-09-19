@echo off
chcp 65001 > nul
title Rey Taco Picks - Sincronizador Express
echo =========================================================
echo    🌮 REY TACO PICKS - SINCRONIZADOR DE CARTELERA PLAYDOIT
echo =========================================================
echo.
echo Conectando con Playdoit y sincronizando con Supabase...
python "backend\fast_playdoit_sync.py"
echo.
echo Presiona cualquier tecla para cerrar esta ventana.
pause > nul
