param([string]$DownloadsPath,[string]$QueuePath,[switch]$Foreground)
$motionRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$motionPython = Join-Path $motionRoot '.venv/Scripts/python.exe'
$motionWorker = Join-Path $motionRoot 'scripts/local_worker.py'
if (-not (Test-Path -LiteralPath $motionPython)) { throw 'Run python scripts/install.py --project-root . first.' }
if (-not $QueuePath) { $QueuePath = Join-Path $motionRoot 'LOCAL_RENDER' }
if (-not $DownloadsPath) {
    $motionUserFolders = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders'
    try { $DownloadsPath = [Environment]::ExpandEnvironmentVariables((Get-ItemProperty -LiteralPath $motionUserFolders -Name '{374DE290-123F-4565-9164-39C4925E467B}').'{374DE290-123F-4565-9164-39C4925E467B}') } catch { $DownloadsPath = Join-Path ([Environment]::GetFolderPath('UserProfile')) 'Downloads' }
}
$motionStatusText = & $motionPython $motionWorker status --queue $QueuePath
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect local render queue.' }
$motionStatus = $motionStatusText | ConvertFrom-Json
if ($motionStatus.running) { Write-Output ('Worker is already running. Videos: ' + $motionStatus.ready); exit 0 }
$motionArguments = @('-X','utf8',$motionWorker,'watch','--queue',$QueuePath,'--downloads',$DownloadsPath)
if ($Foreground) { & $motionPython @motionArguments; exit $LASTEXITCODE }
# Python detaches the worker with CREATE_NO_WINDOW and redirects all handles to
# files. PowerShell Start-Process redirection can otherwise keep this command alive.
& $motionPython -X utf8 $motionWorker start --queue $QueuePath --downloads $DownloadsPath
exit $LASTEXITCODE
