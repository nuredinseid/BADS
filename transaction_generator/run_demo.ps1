$p = "c:\Users\Noor\Desktop\final year\transaction_generator"
$vpy = "$p\.venv\Scripts\python.exe"
if (Test-Path $vpy) { $py = $vpy } else { $py = "python" }
& $py -m src.main --mode historical --days 7 --customers 200 --seed 42 --base-tpm 80 2>&1
