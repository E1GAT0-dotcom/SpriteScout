@echo off
rem Runs spritescout.py with Python. Use this if Windows blocks SpriteScout.exe.
py "%~dp0spritescout.py" %*
if errorlevel 9009 (
    echo Python isn't installed, so this can't run. Get it from https://www.python.org/downloads/
    pause
)
