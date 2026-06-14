@echo off
echo ============================================
echo Salikha Studio Pro - Build Script
echo ============================================
echo.

REM Check if running as admin (for some operations)
net session >nul 2>&1
if %errorLevel% == 0 (
    echo Running as Administrator
) else (
    echo Running as Standard User
)
echo.

REM Step 1: Install dependencies
echo [1/4] Installing Python dependencies...
pip install -r requirements.txt
if %errorLevel% neq 0 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)
echo.

REM Step 2: Build with PyInstaller
echo [2/4] Building executable with PyInstaller...
python -m PyInstaller salikha_pro.spec --clean
if %errorLevel% neq 0 (
    echo ERROR: PyInstaller build failed
    pause
    exit /b 1
)
echo.

REM Step 3: Create output directories
echo [3/4] Preparing installer output...
if not exist "installer" mkdir installer
if not exist "hot_input" mkdir hot_input
if not exist "prints_archive" mkdir prints_archive
echo.

REM Step 4: Build installer with Inno Setup
echo [4/4] Building installer with Inno Setup...
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" salikha_pro_setup.iss
) else if exist "C:\Program Files (x86)\Inno Setup 5\ISCC.exe" (
    "C:\Program Files (x86)\Inno Setup 5\ISCC.exe" salikha_pro_setup.iss
) else if exist "C:\Program Files\Inno Setup 6\ISCC.exe" (
    "C:\Program Files\Inno Setup 6\ISCC.exe" salikha_pro_setup.iss
) else if exist "C:\Program Files\Inno Setup 5\ISCC.exe" (
    "C:\Program Files\Inno Setup 5\ISCC.exe" salikha_pro_setup.iss
) else (
    echo WARNING: Inno Setup not found. Skipping installer creation.
    echo Please install Inno Setup from https://jrsoftware.org/isinfo.php
    echo Then run: "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" salikha_pro_setup.iss
)
echo.

echo ============================================
echo Build Complete!
echo ============================================
echo.
echo Executable: dist\salikha_pro.exe
if exist "installer\SalikhaStudioPro_Setup_v1.0.0.exe" (
    echo Installer: installer\SalikhaStudioPro_Setup_v1.0.0.exe
)
echo.
pause