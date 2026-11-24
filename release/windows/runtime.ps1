function Get-PlanRuntime {
    $dataPath = if ($env:PLAN_REVIEW_DESKTOP_DATA) {
        [IO.Path]::GetFullPath($env:PLAN_REVIEW_DESKTOP_DATA)
    } else {
        Join-Path $env:LOCALAPPDATA 'EASPhubPlanReview\workspace'
    }
    return @{ Data=$dataPath }
}
