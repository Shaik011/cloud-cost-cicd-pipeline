$azure = (Get-Content ".\terraform-infra\cost.json" -Raw | ConvertFrom-Json).summary.total_monthly_cost
$aws   = (Get-Content ".\csp-comparison\aws\cost.json" -Raw | ConvertFrom-Json).summary.total_monthly_cost
$gcp   = (Get-Content ".\csp-comparison\gcp\cost.json" -Raw | ConvertFrom-Json).summary.total_monthly_cost

Write-Host ""
Write-Host "===== CSP COST COMPARISON ====="
Write-Host ("Azure : $" + $azure)
Write-Host ("AWS   : $" + $aws)
Write-Host ("GCP   : $" + $gcp)
Write-Host "==============================="

$costs = @{
    Azure = [double]$azure
    AWS   = [double]$aws
    GCP   = [double]$gcp
}

$cheapest = $costs.GetEnumerator() | Sort-Object Value | Select-Object -First 1

Write-Host ""
Write-Host ("CHEAPEST CSP: " + $cheapest.Name + " ($" + $cheapest.Value + "/month)")