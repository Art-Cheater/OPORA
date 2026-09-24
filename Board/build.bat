@echo off
setlocal
set PATH=C:\avr-gcc\bin;%PATH%

echo ============================================
echo  IPP TCP v2.2.7 PHASE INPUTS
echo  ATmega8515 @ 6 MHz
echo ============================================
echo.

avr-gcc -mmcu=atmega8515 -DF_CPU=6000000UL -Os -flto -mcall-prologues -std=gnu99 -Wall -Wextra -ffunction-sections -fdata-sections -Wl,--gc-sections,--relax -Wl,-Map=firmware.map -o firmware.elf main.c
if errorlevel 1 goto :error

avr-objcopy -O ihex -R .eeprom firmware.elf firmware.hex
if errorlevel 1 goto :error

echo.
avr-size firmware.elf
echo.

avr-nm -S --size-sort -t d firmware.elf > symbols_by_size.txt
echo symbols_by_size.txt saved.
echo.
echo BUILD OK
pause
exit /b 0

:error
echo.
echo BUILD FAILED
pause
exit /b 1
