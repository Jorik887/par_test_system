param(
  [string]$BaseUrl = "http://127.0.0.1:8000",
  [int]$TargetId = 1,
  [string]$DictName = "Файлы",
  [string]$SearchColumn = "uuid",
  [string]$SearchValue = "",
  [int]$Warmup = 2,
  [int]$Loops = 10
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Invoke-Timed {
  param(
    [string]$Name,
    [scriptblock]$Action
  )
  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  try {
    $res = & $Action
    $sw.Stop()
    [pscustomobject]@{ name=$Name; ok=$true; ms=[math]::Round($sw.Elapsed.TotalMilliseconds,2); error=""; payload=$res }
  } catch {
    $sw.Stop()
    $msg = $_.Exception.Message
    if ($_.ErrorDetails -and $_.ErrorDetails.Message) { $msg = $_.ErrorDetails.Message }
    [pscustomobject]@{ name=$Name; ok=$false; ms=[math]::Round($sw.Elapsed.TotalMilliseconds,2); error=$msg; payload=$null }
  }
}

function Run-Metric {
  param([string]$Name,[scriptblock]$Action,[int]$WarmupCount,[int]$LoopCount)

  if ($WarmupCount -gt 0) {
    1..$WarmupCount | ForEach-Object {
      try { & $Action | Out-Null } catch { }
    }
  }

  $runs = @()
  1..$LoopCount | ForEach-Object {
    $r = Invoke-Timed -Name $Name -Action $Action
    $runs += $r
  }

  $okRuns = @($runs | Where-Object { $_.ok })
  $failRuns = @($runs | Where-Object { -not $_.ok })

  $p50 = if ($okRuns.Count -gt 0) { [math]::Round((@($okRuns.ms | Sort-Object))[[int]([math]::Floor(($okRuns.Count-1)*0.5))],2) } else { $null }
  $p95 = if ($okRuns.Count -gt 0) { [math]::Round((@($okRuns.ms | Sort-Object))[[int]([math]::Floor(($okRuns.Count-1)*0.95))],2) } else { $null }

  [pscustomobject]@{
    endpoint = $Name
    total = $runs.Count
    success = $okRuns.Count
    failed = $failRuns.Count
    avg_ms = if ($okRuns.Count -gt 0) { [math]::Round(($okRuns | Measure-Object -Property ms -Average).Average,2) } else { $null }
    p50_ms = $p50
    p95_ms = $p95
    max_ms = if ($okRuns.Count -gt 0) { [math]::Round(($okRuns | Measure-Object -Property ms -Maximum).Maximum,2) } else { $null }
    sample_error = if ($failRuns.Count -gt 0) { $failRuns[0].error } else { "" }
  }
}

$healthAction = { Invoke-RestMethod -Method GET "$BaseUrl/health" -TimeoutSec 10 }
$probeAction = { Invoke-RestMethod -Method POST "$BaseUrl/targets/$TargetId/probe" -TimeoutSec 30 }
$dictsAction = {
  $body = @{ name = $DictName; filters = @() }
  if (-not [string]::IsNullOrWhiteSpace($SearchValue)) {
    $body.filters = @(@{ column=$SearchColumn; condition="Равно"; value=$SearchValue })
  }
  $json = $body | ConvertTo-Json -Compress -Depth 8
  Invoke-RestMethod -Method POST "$BaseUrl/dicts/search?target_id=$TargetId" -ContentType "application/json; charset=utf-8" -Body $json -TimeoutSec 60
}

$metrics = @()
$metrics += Run-Metric -Name "GET /health" -Action $healthAction -WarmupCount 0 -LoopCount 3
$metrics += Run-Metric -Name "POST /targets/{id}/probe" -Action $probeAction -WarmupCount $Warmup -LoopCount $Loops
$metrics += Run-Metric -Name "POST /dicts/search" -Action $dictsAction -WarmupCount $Warmup -LoopCount $Loops

"`n=== PERF SUMMARY ==="
$metrics | Format-Table -AutoSize

"`n=== QUICK READ ==="
foreach ($m in $metrics) {
  $state = if ($m.failed -eq 0) { "OK" } else { "WARN" }
  "[$state] $($m.endpoint): avg=$($m.avg_ms)ms p95=$($m.p95_ms)ms failed=$($m.failed)/$($m.total)"
  if ($m.sample_error) { "  sample_error: $($m.sample_error)" }
}
