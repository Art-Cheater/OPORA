@echo off
echo Flashing IPP TCP v2.1 CLEAN STABLE...
C:\avrdude\avrdude.exe -c usbasp -p m8515 -U flash:w:firmware.hex:i
if errorlevel 1 (
  echo.
  echo FLASH FAILED
) else (
  echo.
  echo FLASH OK
)
pause
