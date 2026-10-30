<#
Registers (or removes) the Windows scheduled task that keeps the Pacific data current without a manual refresh.

    powershell -ExecutionPolicy Bypass -File scripts\install_daily_task.ps1            # install
    powershell -ExecutionPolicy Bypass -File scripts\install_daily_task.ps1 -Remove    # uninstall
    powershell -ExecutionPolicy Bypass -File scripts\install_daily_task.ps1 -At 19:15 -EveryHours 2

When it runs: NOAA posts the preliminary OISST file of day D on day D+1 at about 13:31 UTC. The first run of each day is therefore set to 13:45 UTC, converted to this computer's local time
(19:15 in India), and it repeats every 2 hours for 22 hours, so a run that finds nothing yet, or that happens while the computer is asleep, is followed by another one soon. A run that finds nothing
newer changes nothing. The task also runs as soon as possible after a missed start (StartWhenAvailable) and may wake the computer (WakeToRun); a laptop that is switched off or asleep for the
whole window cannot refresh, and the dashboard then says that the data are delayed and why.

The task runs scripts\daily_refresh.py with the project's virtual environment. Log: logs\daily_refresh.log; outcome of the last run: data\refresh_status.json.
#>
param([switch]$Remove, [string]$At = "", [int]$EveryHours = 2, [string]$Name = "OceanMind daily SST refresh")
$root = Split-Path -Parent $PSScriptRoot
if ($Remove) { Unregister-ScheduledTask -TaskName $Name -Confirm:$false -ErrorAction SilentlyContinue; "removed $Name"; return }
if (-not $At) {
    $utc = [DateTime]::SpecifyKind([DateTime]::UtcNow.Date.AddHours(13).AddMinutes(45), [DateTimeKind]::Utc)          # 13:45 UTC, after NOAA's usual upload time
    $At = [TimeZoneInfo]::ConvertTimeFromUtc($utc, [TimeZoneInfo]::Local).ToString("HH:mm")
}
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Virtual environment not found at $python" }
$action = New-ScheduledTaskAction -Execute $python -Argument "scripts\daily_refresh.py" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$rep = (New-ScheduledTaskTrigger -Once -At $At -RepetitionInterval (New-TimeSpan -Hours $EveryHours) -RepetitionDuration (New-TimeSpan -Hours 22)).Repetition
$trigger.Repetition = $rep
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 3)
Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings -Description "Downloads the newest NOAA OISST day, rebuilds the Pacific dataset, forecast, heatwaves and SST history." -Force | Out-Null
"registered '$Name' (daily at $At local time = 13:45 UTC, repeating every $EveryHours hours for 22 hours)"
