@echo off
chcp 65001 >nul
set PYTHONUTF8=1
python -m aircontrol %*
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [Aircontrol] Gap loi khi chay chuong trinh. Nhan phim bat ky de dong...
    pause >nul
)
