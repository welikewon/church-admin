@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem ── 압축을 풀지 않고 실행하셨는지 확인 ──
if not exist "%~dp0python\python.exe" goto NOTUNZIPPED
if not exist "%~dp0_시스템\church_web.py" goto NOTUNZIPPED

echo 교회 종합행정 프로그램을 시작합니다... 잠시 후 브라우저에 열립니다.
echo (끄려면 이 검은 창을 닫으세요)
"%~dp0python\python.exe" "%~dp0_시스템\church_web.py"
pause
exit /b

:NOTUNZIPPED
echo.
echo   ┌────────────────────────────────────────────────┐
echo   │  잠깐만요! 압축을 먼저 풀어 주세요.            │
echo   └────────────────────────────────────────────────┘
echo.
echo   지금은 압축(zip) 안에서 실행하셔서 프로그램 본체가 함께 있지 않습니다.
echo.
echo   이렇게 해주세요 (30초면 됩니다)
echo     1. 받으신 zip 파일 위에서 마우스 오른쪽 버튼을 누릅니다.
echo     2. "압축 풀기" 또는 "전체 압축 풀기"를 선택합니다.
echo     3. 새로 생긴 폴더를 열고, 그 안의
echo        [ ★ 교회행정 시작 (여기를 더블클릭).bat ] 을 다시 더블클릭하세요.
echo.
echo   ※ 파이썬 같은 것은 따로 설치하지 않으셔도 됩니다.
echo      프로그램 안에 이미 들어 있습니다.
echo.
pause
exit /b
