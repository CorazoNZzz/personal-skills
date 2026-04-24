Param(
  [int]$TargetRow = 0,
  [string]$ProjectName = "",
  [int]$ProjectCol = 2,
  [int]$ScanRowFrom = 3,
  [int]$ScanRowTo = 200,

  [string]$StartDate = "",
  [string]$EndDate = "",
  [string]$NextWeekPlan = "",
  [string]$NextWeekPlanFile = "",
  [switch]$Apply
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$skillRoot = Split-Path -Parent $scriptDir
$templateFile = Join-Path $scriptDir "mcporter_templates.example.json"

if (-not (Test-Path $templateFile)) {
  throw "Template file not found: $templateFile"
}

if ($TargetRow -le 0 -and [string]::IsNullOrWhiteSpace($ProjectName)) {
  throw "Either -TargetRow or -ProjectName is required."
}

if (-not $StartDate -or -not $EndDate) {
  $today = Get-Date
  $monday = $today.AddDays(-([int]$today.DayOfWeek - 1))
  if ($today.DayOfWeek -eq [System.DayOfWeek]::Sunday) {
    $monday = $today.AddDays(-6)
  }
  $friday = $monday.AddDays(4)
  if (-not $StartDate) { $StartDate = $monday.ToString("yyyy-MM-dd") }
  if (-not $EndDate) { $EndDate = $friday.ToString("yyyy-MM-dd") }
}

Push-Location $skillRoot
try {
  $args = @(
    "scripts/sync_weekly_kdocs.py",
    "--start-date", $StartDate,
    "--end-date", $EndDate,
    "--daily-archive-file", "data/daily_records.jsonl",
    "--backend", "mcporter",
    "--mcporter-template-file", $templateFile,
    "--confirm-range", "YES"
  )

  if ($TargetRow -gt 0) {
    $args += @("--target-row", "$TargetRow")
  }
  if (-not [string]::IsNullOrWhiteSpace($ProjectName)) {
    $args += @("--project-name", $ProjectName)
    $args += @("--project-col", "$ProjectCol")
    $args += @("--scan-row-from", "$ScanRowFrom")
    $args += @("--scan-row-to", "$ScanRowTo")
  }

  if ($NextWeekPlanFile) {
    $args += @("--next-week-plan-file", $NextWeekPlanFile)
  } elseif ($NextWeekPlan) {
    $args += @("--next-week-plan", $NextWeekPlan)
  }

  if ($Apply) {
    $args += @("--apply", "--confirm-write", "WRITE")
  }

  & python @args
  if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
  }
}
finally {
  Pop-Location
}
