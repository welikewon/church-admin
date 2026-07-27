@echo off
chcp 65001 >nul
title 교회 행정 - 바탕화면 아이콘 만들기
set "APPDIR=%~dp0"
set "TARGET=%~dp0★ 교회행정 시작 (여기를 더블클릭).bat"
set "ICO=%~dp0_시스템\_교회행정아이콘.ico"
set "CFG=%~dp0_시스템\church_config.json"
if not exist "%TARGET%" (
  echo.
  echo  [알림] 시작 파일을 찾지 못했습니다.
  echo  이 파일은 교회행정 프로그램 폴더 안에서 실행해 주세요.
  echo.
  pause
  exit /b
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$nm='교회'; if(Test-Path $env:CFG){try{$j=Get-Content $env:CFG -Raw -Encoding UTF8 | ConvertFrom-Json; if($j.'교회명'){$nm=$j.'교회명'}}catch{}}; $d=[Environment]::GetFolderPath('Desktop'); $w=New-Object -ComObject WScript.Shell; $s=$w.CreateShortcut((Join-Path $d ($nm+' 행정.lnk'))); $s.TargetPath=$env:TARGET; $s.WorkingDirectory=$env:APPDIR; if(Test-Path $env:ICO){$s.IconLocation=$env:ICO+',0'}else{$s.IconLocation='%SystemRoot%\System32\imageres.dll,109'}; $s.Description=($nm+' 종합행정시스템 - 여기를 눌러 시작'); $s.Save(); Write-Host ('  만든 아이콘 이름: '+$nm+' 행정')"
echo.
echo  =========================================================
echo   [완료] 바탕화면에 '(우리 교회 이름) 행정' 아이콘을 만들었습니다.
echo.
echo   이제부터는 폴더를 열 필요 없이,
echo   바탕화면의 그 아이콘만 더블클릭하시면 프로그램이 켜집니다.
echo.
echo   ※ 아이콘 이름이 'OO교회'로 나오면: 프로그램에서 '교회 이름 설정'을
echo      먼저 하신 뒤, 이 파일을 한 번만 다시 실행해 주세요.
echo  =========================================================
echo.
pause
