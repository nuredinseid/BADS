# BADS Real-Time Dashboard Launcher
# Run this script to start the web dashboard

$p = "c:\Users\Noor\Desktop\final year\transaction_generator"
$vpy = "$p\.venv\Scripts\python.exe"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  BADS Real-Time Transaction Dashboard" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if Flask is installed
& $vpy -c "import flask" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing Flask..." -ForegroundColor Yellow
    & $vpy -m pip install flask --quiet
}

Write-Host "Starting dashboard server..." -ForegroundColor Green
Write-Host ""
Write-Host "Open your browser to:" -ForegroundColor Yellow
Write-Host "  http://localhost:5000" -ForegroundColor White
Write-Host ""
Write-Host "Press Ctrl+C to stop the server" -ForegroundColor Gray
Write-Host ""

& $vpy "$p\web_app.py"
