@echo off
title IRON NEST Freezer
echo ============================================================
echo  IRON NEST - Timer + Requisition freezer
echo  - Leave this window open while playing.
echo  - It waits for the game, then locks the timer and sets
echo    requisition to 999999 and freezes it.
echo  - Close this window (or press Ctrl+C) to stop freezing.
echo ============================================================
echo.
"C:\Users\Owner\AppData\Local\Programs\Python\Python311\python.exe" "C:\Users\Owner\ironnest_freezer.py" set=999999
pause
