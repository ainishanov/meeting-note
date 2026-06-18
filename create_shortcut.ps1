$ProjectPath = $PSScriptRoot
$PythonwPath = Join-Path $ProjectPath "venv\Scripts\pythonw.exe"
$RunPath = Join-Path $ProjectPath "run.py"

if (-not (Test-Path -LiteralPath $PythonwPath)) {
    throw "pythonw.exe not found. Create a venv and install requirements first: $PythonwPath"
}

if (-not (Test-Path -LiteralPath $RunPath)) {
    throw "run.py not found: $RunPath"
}

$DesktopPaths = @(
    [Environment]::GetFolderPath('Desktop'),
    (Join-Path $env:USERPROFILE 'Desktop'),
    (Join-Path $env:USERPROFILE 'OneDrive\Desktop')
) | Where-Object {
    -not [string]::IsNullOrWhiteSpace($_) -and (Test-Path -LiteralPath $_)
} | Select-Object -Unique

if (-not $DesktopPaths) {
    throw "No Desktop folder found for current user"
}

$WshShell = New-Object -ComObject WScript.Shell

foreach ($DesktopPath in $DesktopPaths) {
    $ShortcutPath = Join-Path $DesktopPath 'Meeting Note.lnk'
    $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = $PythonwPath
    $Shortcut.Arguments = "`"$RunPath`""
    $Shortcut.WorkingDirectory = $ProjectPath
    $Shortcut.Description = "Meeting Note - Audio Transcription"
    $Shortcut.WindowStyle = 1
    $Shortcut.Save()

    $CreatedShortcut = $WshShell.CreateShortcut($ShortcutPath)
    if ([string]::IsNullOrWhiteSpace($CreatedShortcut.TargetPath)) {
        throw "Shortcut target is empty after creation: $ShortcutPath"
    }

    Write-Host "Shortcut created at: $ShortcutPath"
}
