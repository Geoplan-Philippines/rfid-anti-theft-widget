@echo off
cd /d "%~dp0"
py -3-32 -m hax7700_widget %* 2>nul || py -3 -m hax7700_widget %*
