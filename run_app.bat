@echo off
setlocal

cd /d "%~dp0"
set "PROJECT_DIR=%CD%"
set "APP_PYTHON=%PROJECT_DIR%\.venv\Scripts\python.exe"

if not exist "%APP_PYTHON%" call :create_venv
if errorlevel 1 goto venv_failed

"%APP_PYTHON%" -c "import sys" >nul 2>nul
if errorlevel 1 (
  set "VENV_BACKUP=.venv-backup-%RANDOM%%RANDOM%"
  echo Backing up an unusable virtual environment to %VENV_BACKUP%...
  ren ".venv" "%VENV_BACKUP%"
  if errorlevel 1 goto venv_failed
  call :create_venv
  if errorlevel 1 goto venv_failed
)

"%APP_PYTHON%" -c "import nd2, numpy, PySide6, pyqtgraph, scipy" >nul 2>nul
if errorlevel 1 (
  echo Installing Python packages...
  "%APP_PYTHON%" -m pip install -e .
  if errorlevel 1 goto install_failed
)

rem Always run the MOSAIC source next to this launcher.
set "PYTHONPATH=%PROJECT_DIR%\src;%PYTHONPATH%"
"%APP_PYTHON%" -m mosaic.main
if errorlevel 1 goto app_failed

exit /b 0

:venv_failed
echo.
echo Failed to create .venv. Install Python 3.9 or newer, then try again.
pause
exit /b 1

:install_failed
echo.
echo Failed to install required Python packages.
pause
exit /b 1

:app_failed
echo.
echo The app exited with an error.
pause
exit /b 1

:create_venv
echo Creating Python virtual environment...
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -m venv .venv
) else (
  python -m venv .venv
)
if errorlevel 1 exit /b 1

"%APP_PYTHON%" -m pip install -U pip
if errorlevel 1 exit /b 1

"%APP_PYTHON%" -m pip install -e .
if errorlevel 1 exit /b 1
exit /b 0
