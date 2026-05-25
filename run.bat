@echo off
title 한반도 경제 모니터링 시스템 (SNS & News Economy Monitor)
cls

:menu
echo =============================================================
echo    한반도 경제 실시간 모니터링 시스템 (SNS & News Monitor)
echo =============================================================
echo.
echo  [1] 실시간 감시 시작 (Flask 웹서버 구동 및 대시보드 자동 팝업) - 추천
echo  [2] 단회성 빠른 검사 (1회 실행 후 종료)
echo  [3] 실시간 HTML 대시보드 화면 열기 (http://localhost:5000)
echo  [4] 제미나이 지원 모델 확인 진단기 실행 (list_models.py)
echo  [5] 구글 API 키 등록/변경하기 (임시 세션 환경변수)
echo  [6] 종료 (Exit)
echo.
echo =============================================================
echo.
set /p choice="실행할 작업의 번호를 입력하세요 (1-6): "

if "%choice%"=="1" goto run_daemon
if "%choice%"=="2" goto run_once
if "%choice%"=="3" goto open_dashboard
if "%choice%"=="4" goto run_diagnostic
if "%choice%"=="5" goto set_key
if "%choice%"=="6" goto exit_app
goto menu

:run_daemon
cls
echo [가동] Flask 웹서버 및 실시간 백그라운드 수집을 가동합니다...
python main.py
pause
goto menu

:run_once
cls
echo [가동] 뉴스 및 SNS 1회 일괄 수집/분석을 시작합니다...
python main.py --once
pause
goto menu

:open_dashboard
cls
echo [실행] 브라우저에서 대시보드 화면(http://localhost:5000)을 엽니다...
start http://localhost:5000
pause
goto menu

:run_diagnostic
cls
echo [진단] 구글 API가 수용하는 전체 모델 목록을 검사합니다...
python list_models.py
pause
goto menu

:set_key
cls
echo =============================================================
echo  구글 제미나이 API 키 입력 페이지
echo =============================================================
echo.
echo  * 팁: 여기에 입력된 키는 이 터미널 세션 동안 활성화되며,
echo        config.json 파일에 안전하게 보관되지 않고 휘발성으로 사용됩니다.
echo.
set /p key="구글 API 키를 입력하십시오 (엔터 입력 시 취소): "
if "%key%"=="" goto menu
set GEMINI_API_KEY=%key%
echo.
echo [성공] API 키 환경 변수가 설정되었습니다.
pause
goto menu

:exit_app
exit
