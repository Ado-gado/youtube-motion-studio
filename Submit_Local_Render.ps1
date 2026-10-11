param([string]$Url,[string]$File,[string]$QueuePath)
$motionRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$motionPython = Join-Path $motionRoot '.venv/Scripts/python.exe'
$motionWorker = Join-Path $motionRoot 'scripts/local_worker.py'
if (-not $QueuePath) { $QueuePath = Join-Path $motionRoot 'LOCAL_RENDER' }
if (-not $Url -and -not $File) { $Url = Read-Host 'Paste the HTTPS motion-job ZIP link' }
if ($File) { & $motionPython $motionWorker submit --queue $QueuePath --file $File } else { & $motionPython $motionWorker submit --queue $QueuePath --url $Url }
if ($LASTEXITCODE -ne 0) { throw 'Submission failed. If the link requires login, download the ZIP in its Emergent browser account.' }
