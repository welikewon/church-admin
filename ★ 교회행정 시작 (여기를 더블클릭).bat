@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 교회 종합행정 프로그램을 시작합니다... 잠시 후 브라우저에 열립니다.
echo (끄려면 이 검은 창을 닫으세요)
"%~dp0python\python.exe" "%~dp0_시스템\church_web.py"
pause
