@echo off
rem superboxes: serve the built app on localhost and open it in its own window.
cd /d "%~dp0"
if not exist dist\index.html (
  echo First run: building the app. Needs Node.js and Python.
  call npm install || goto :fail
  call npm run setup || goto :fail
  call npm run build || goto :fail
)
python serve.py %*
goto :eof
:fail
echo Build failed - see the messages above.
pause
