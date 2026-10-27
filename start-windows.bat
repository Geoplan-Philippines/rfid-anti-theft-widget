@echo off
cd /d "%~dp0"
if exist "%LOCALAPPDATA%\Programs\Python\Python312-32\pythonw.exe" (
    start "" "%LOCALAPPDATA%\Programs\Python\Python312-32\pythonw.exe" -m hax7700_widget %*
) else (
    py -3-32 -m hax7700_widget %* 2>nul || py -3 -m hax7700_widget %*
)
