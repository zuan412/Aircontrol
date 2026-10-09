@echo off
setlocal enabledelayedexpansion

echo =======================================================
echo        AIRCONTROL WINDOWS RELEASE PACKAGER
echo =======================================================
echo.

cd /d "%~dp0"

echo [1/4] Kiem tra moi truong Python...
if not exist ".venv\Scripts\python.exe" (
    echo [LOI] Khong tim thay moi truong ao .venv!
    pause
    exit /b 1
)

echo [2/4] Don dep thu muc build cu...
if exist "build" rmdir /s /q "build"
if exist "dist\Aircontrol" rmdir /s /q "dist\Aircontrol"
if exist "dist\Aircontrol-v0.1.0-win64.zip" del /q "dist\Aircontrol-v0.1.0-win64.zip"

echo [3/4] Tien hanh dong goi Standalone Binary bang PyInstaller...
.venv\Scripts\python.exe -m PyInstaller -y --clean Aircontrol.spec
if %ERRORLEVEL% neq 0 (
    echo [LOI] PyInstaller dong goi that bai!
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo [4/4] Tao file nen Portable ZIP san sang phat hanh len GitHub...
powershell -NoProfile -Command "Compress-Archive -Path 'dist\Aircontrol' -DestinationPath 'dist\Aircontrol-v0.1.0-win64.zip' -Force"

echo.
echo =======================================================
echo  THANH CONG! BAN THU NGHIEM DA DUOC DONG GOI HOAN TAT:
echo  - Thu muc chay truc tiep: dist\Aircontrol\Aircontrol.exe
echo  - File phat hanh GitHub: dist\Aircontrol-v0.1.0-win64.zip
echo =======================================================
echo.
pause
