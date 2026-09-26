# Fault injection: FREEZE the local OmniParser (process alive, port listening, not answering)
# and check that bridge_watchdog.ps1 detects it and heals it.
#
# Why this exists: the service's task restarts a DEAD process (2-min repeat trigger,
# IgnoreNew) but a frozen one still counts as "running". One such stall happened for
# real; this reproduces it with NtSuspendProcess. It restarts the real service, so it
# is a manual tool, not a test. Expect the watchdog to take ~1-2 min, then a normal
# restart of ~25 s (one cold start took ~5 min under heavy machine load - see
# docs/lenovo_performance.md), so the script's 2-min recovery wait can report
# 'recovered=False' on a slow start even though the heal worked; re-check health.
#
#   powershell -File local_omniparser\fault_inject_freeze.ps1
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition 'using System;using System.Runtime.InteropServices;public class NtP{[DllImport("ntdll.dll")]public static extern int NtSuspendProcess(IntPtr h);[DllImport("ntdll.dll")]public static extern int NtResumeProcess(IntPtr h);}'
$root = Split-Path -Parent $PSScriptRoot
$old  = (Get-NetTCPConnection -LocalPort 7871 -State Listen).OwningProcess
$proc = Get-Process -Id $old
"service pid $old, up {0:N0}s, healthy before: {1}" -f ((Get-Date) - $proc.StartTime).TotalSeconds, [bool](Invoke-RestMethod http://127.0.0.1:7871/api/health -TimeoutSec 5).ok

[void][NtP]::NtSuspendProcess($proc.Handle)
Start-Sleep 1
$frozen = try { Invoke-RestMethod http://127.0.0.1:7871/api/health -TimeoutSec 3; $false } catch { $true }
"FROZEN: process alive={0}, listening={1}, health unresponsive={2}" -f (-not $proc.HasExited), [bool](Get-NetTCPConnection -LocalPort 7871 -State Listen), $frozen

$sw = [Diagnostics.Stopwatch]::StartNew()
$p = Start-Process powershell -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File',"$root\bridge_watchdog.ps1" -WindowStyle Hidden -PassThru -Wait
"watchdog ran {0:N0}s, exit {1}" -f $sw.Elapsed.TotalSeconds, $p.ExitCode

# recovery: new pid answering?
$rec = $false; foreach ($i in 1..40) { Start-Sleep 3; try { $h = Invoke-RestMethod http://127.0.0.1:7871/api/health -TimeoutSec 3; $rec = $true; break } catch {} }
$new = (Get-NetTCPConnection -LocalPort 7871 -State Listen -ErrorAction SilentlyContinue).OwningProcess
"recovered={0} after {1:N0}s more; old pid {2} -> new pid {3}; ocr={4}" -f $rec, ($i*3), $old, $new, $h.ocr

# safety net: never leave the old process suspended
try { $o = Get-Process -Id $old -ErrorAction Stop; [void][NtP]::NtResumeProcess($o.Handle); "old process still existed and was resumed" } catch { "old process is gone (killed by the watchdog)" }
Get-Content "$root\ufo_skill_state\evidence\bridge\watchdog.log" -Tail 4 | ForEach-Object { $_ -replace '^\S+\s+','' }
