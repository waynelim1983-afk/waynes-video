@echo off
chcp 65001 >nul
cd /d C:\projects\YT\smartcat-yt-automation-public
echo Running Gemini video end-to-end test...
python gemini_video_browser.py --prompt "A golden retriever puppy playing in autumn leaves, cinematic slow motion, warm sunlight" --output output\test_gemini_video.mp4 --max-wait 300 > logs\gemini_video_test.txt 2>&1
echo Exit code: %ERRORLEVEL%
echo.
echo === Last 30 lines of log ===
powershell -Command "Get-Content logs\gemini_video_test.txt | Select-Object -Last 30"
pause
