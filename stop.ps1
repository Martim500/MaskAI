Get-CimInstance Win32_Process |
    Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -like '*streamlit*app.py*' } |
    ForEach-Object {
        Write-Host "Stopping process $($_.ProcessId)..."
        Stop-Process -Id $_.ProcessId -Force
    }
Write-Host "Done."
