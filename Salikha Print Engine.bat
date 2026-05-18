@echo off
title Salikha Print Engine Reinstaller
echo ==========================================
echo    SALIKHA STUDIO - PRINT ENGINE INSTALLER
echo ==========================================
echo.

echo [1/3] Installing Required Libraries...
pip install pywin32 watchdog Pillow pyinstaller

echo.
echo [2/3] Cleaning old build files...
if exist build rd /s /q build
if exist dist rd /s /q dist

echo.
echo [3/3] Building Salikha Engine Stable EXE...
python -m PyInstaller --clean --onefile --windowed --collect-all PIL --name "Salikha_Print_Engine" salikha_pro.py

echo.
echo ==========================================
echo    INSTALLATION COMPLETE!
echo    Check the "dist" folder for your EXE.
echo ==========================================
pause