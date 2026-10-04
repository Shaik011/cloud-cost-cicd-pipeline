$budget = [double]$env:BUDGET

$azure = [double](Get-Content ".\terraform-infra\cost.json" -Raw | ConvertFrom-Json).summary.total_monthly_cost
$aws   = [double](Get-Content ".\csp-comparison\aws\cost.json" -Raw | ConvertFrom-Json).summary.total_monthly_cost
$gcp   = [double](Get-Content ".\csp-comparison\gcp\cost.json" -Raw | ConvertFrom-Json).summary.total_monthly_cost

Write-Host ""
Write-Host "===== CLOUD COST GATE ====="
Write-Host ("Budget: $" + $budget)
Write-Host ("Azure : $" + $azure)
Write-Host ("AWS   : $" + $aws)
Write-Host ("GCP   : $" + $gcp)
Write-Host "==========================="

if ($azure -le $budget) {
    Write-Host ""
    Write-Host "WITHIN BUDGET"
    Write-Host "DEFAULT CSP: Azure"

    # Tell Jenkins Azure is safe to deploy.
    Write-Output "WITHIN_BUDGET"
    exit 0
}

Write-Host ""
Write-Host "OVER BUDGET"
Write-Host "CSP comparison required."

# Tell Jenkins that it needs to ask the user.
Write-Output "OVER_BUDGET"
exit 0