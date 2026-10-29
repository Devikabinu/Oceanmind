<#
Registers (or removes) the Windows scheduled task that keeps the Pacific data current without a manual refresh.

    powershell -ExecutionPolicy Bypass -File scripts\install_daily_task.ps1            # install: every day at 07:00, repeated every 6 hours for 18 hours
    powershell -ExecutionPolicy Bypass -File scripts\install_daily_task.ps1 -Remove    # uninstall

The task runs scripts\daily_refresh.py with the project's virtual environment. NOAA publishes the newest day about one day late, so the repeats pick the data up as soon as it
appears; a run that finds nothing newer changes nothing. If the computer was off at the scheduled time the task runs when it is next on. Log: logs\daily_refresh.log,
outcome of the last run: data\refresh_status.json.
#>
param([switch]$Remove, [string]$At = "07:00", [string]$Name = "OceanMind daily SST refresh")
$root = Split-Path -Parent $PSScriptRoot
if ($Remove) { Unregister-ScheduledTask -TaskName $Name -Confirm:$false -ErrorAction SilentlyContinue; "removed $Name"; return }
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Virtual environment not found at $python" }
$action = New-ScheduledTaskAction -Execute $python -Argument "scripts\daily_refresh.py" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$rep = (New-ScheduledTaskTrigger -Once -At $At -RepetitionInterval (New-TimeSpan -Hours 6) -RepetitionDuration (New-TimeSpan -Hours 18)).Repetition
$trigger.Repetition = $rep
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 3)
Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings -Description "Downloads the newest NOAA OISST day, rebuilds the Pacific dataset, forecast, heatwaves and SST history." -Force | Out-Null
"registered '$Name' (daily at $At, repeating every 6 hours)"
