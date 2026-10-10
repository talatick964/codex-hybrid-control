param([string]$PythonExecutable = "", [string]$OutputDirectory = "dist")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
# Native tools write progress to stderr; check their exit codes explicitly.
$ErrorActionPreference = "Continue"
$outputPath = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot $OutputDirectory))

$python = $null
if ($PythonExecutable) {
    $python = $PythonExecutable
    $pyArgs = @()
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $python = "py"
    $pyArgs = @("-3")
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $python = "python"
    $pyArgs = @()
} else {
    throw "Python 3 не найден. Установи Python 3 один раз, чтобы собрать portable EXE."
}

& $python @pyArgs -c "import PyInstaller, PIL, websocket" *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "PyInstaller не найден. Устанавливаю..."
    & $python @pyArgs -m pip install -r requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw "Build dependencies failed." }
}


# Helper API-воркеров: host-side MCP, который запускает отдельные `codex exec --profile ...`
# вне нативного subagent/thread_spawn механизма root-сессии.
& $python @pyArgs -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --console `
    --distpath "$outputPath" `
    --name "Codex-Hybrid-Worker-Bridge" `
    --add-data "assets/codex-base-instructions.txt;assets" `
    worker_bridge_entry.py
if ($LASTEXITCODE -ne 0) { throw "Build failed: worker_bridge_entry.py" }

$workerBridge = Join-Path $outputPath "Codex-Hybrid-Worker-Bridge.exe"
if (-not (Test-Path $workerBridge)) { throw "Не удалось собрать Worker Bridge." }

# Консольный helper используется как stdio MCP-сервер. Он встраивается в итоговый
# GUI EXE и копируется в ~/.codex/hybrid-control/bin только при установке
# локального компьютерного моста.
& $python @pyArgs -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --console `
    --distpath "$outputPath" `
    --name "Codex-Hybrid-Computer-Bridge" `
    --add-data "assets/codex-base-instructions.txt;assets" `
    computer_bridge_entry.py
if ($LASTEXITCODE -ne 0) { throw "Build failed: computer_bridge_entry.py" }

$bridge = Join-Path $outputPath "Codex-Hybrid-Computer-Bridge.exe"
if (-not (Test-Path $bridge)) { throw "Не удалось собрать Computer Bridge." }

& $python @pyArgs -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --distpath "$outputPath" `
    --name "Codex-Hybrid-Control" `
    --icon "assets/app.ico" `
    --add-data "assets/app.png;assets" `
    --add-data "assets/codex-base-instructions.txt;assets" `
    --add-binary "$bridge;embedded" `
    --add-binary "$workerBridge;embedded" `
    control_entry.py
if ($LASTEXITCODE -ne 0) { throw "Build failed: control_entry.py" }

Write-Host ""
Write-Host "Portable-приложение собрано: $outputPath\Codex-Hybrid-Control.exe"
Write-Host "Helper Worker Bridge и Computer Bridge встроены в основной EXE. Worker Bridge устанавливается автоматически для API-делегирования."
exit 0
