$py = "c:\Users\Noor\Desktop\final year\transaction_generator\.venv\Scripts\python.exe"
Write-Host "Installing Flask..." -ForegroundColor Yellow
& $py -m pip install flask 2>&1 | Out-File -FilePath "logs\flask_install.txt"
if ($LASTEXITCODE -eq 0) {
    Write-Host "Flask installed successfully!" -ForegroundColor Green
} else {
    Write-Host "Installation log saved to logs\flask_install.txt" -ForegroundColor Red
}
