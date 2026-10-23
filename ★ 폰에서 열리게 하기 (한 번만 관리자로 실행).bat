@echo off
chcp 65001 >nul
rem ─────────────────────────────────────────────────────────────────────────
rem  폰에서 열리게 하기 (2026-10-23)
rem   하는 일: 윈도우 방화벽에 «폰이 이 컴퓨터의 8899번 문으로 들어오는 것»을 허용하는
rem            규칙 ★하나만 더합니다. 교회·집 와이파이(개인 망)와 회사 망에서만 듣습니다.
rem   하지 않는 일: 지금 쓰시는 다른 방화벽 설정을 바꾸거나 끄지 않습니다.
rem                 와이파이 종류(공용/개인)도 바꾸지 않습니다 — 알려 드리기만 합니다.
rem   왜 관리자 권한이 필요한가: 윈도우가 방화벽 규칙을 더할 때 관리자 확인을 요구합니다.
rem ─────────────────────────────────────────────────────────────────────────
net session >nul 2>&1
if errorlevel 1 (
  echo.
  echo  이 파일은 관리자 권한으로 실행하셔야 합니다.
  echo  이 창을 닫고, 파일을 ★오른쪽 단추로 누른 뒤 «관리자 권한으로 실행»을 골라 주세요.
  echo.
  pause
  exit /b 1
)

set "RULE=교회행정 폰 접속 (8899)"
rem 같은 이름의 규칙이 이미 있으면 그것만 지우고 다시 넣습니다(겹쳐 쌓이지 않게)
netsh advfirewall firewall delete rule name="%RULE%" >nul 2>&1
netsh advfirewall firewall add rule name="%RULE%" dir=in action=allow protocol=TCP localport=8899 profile=private,domain >nul
if errorlevel 1 (
  echo.
  echo  방화벽 허용을 넣지 못했습니다. 백신 프로그램이 막고 있을 수 있습니다.
  echo.
  pause
  exit /b 1
)

echo.
echo  ✓ 방화벽 허용을 넣었습니다 — 8899번 문 · 교회/집 와이파이(개인 망)에서만 듣습니다.
echo.
echo  ■ 지금 연결된 망의 종류
powershell -NoProfile -Command "Get-NetConnectionProfile | ForEach-Object { '    ' + $_.Name + ' : ' + $(if ($_.NetworkCategory -eq 'Public') {'공용 — ★이 망에서는 폰이 못 들어옵니다'} else {'개인/회사 — 괜찮습니다'}) }"
echo.
echo  ※ «공용»으로 나오면: 윈도우 설정 → 네트워크 및 인터넷 → 지금 와이파이 → «네트워크 프로필 유형»을
echo     «개인»으로 바꿔 주세요. ★교회·집처럼 믿을 수 있는 와이파이에서만 바꾸십시오(카페·공항은 바꾸지 마세요).
echo.
echo  ■ 폰에서 칠 주소 (이 컴퓨터의 주소)
powershell -NoProfile -Command "Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254*' } | ForEach-Object { '    http://' + $_.IPAddress + ':8899' }"
echo.
echo  ※ 프로그램의 «📱 폰 접속 설정» 카드를 다시 실행해 보시면, 막는 것이 남았는지 다시 알려 드립니다.
echo     (공유기·폰 쪽은 이 컴퓨터가 볼 수 없어 «열립니다»라고는 말씀드리지 않습니다.)
echo.
pause
