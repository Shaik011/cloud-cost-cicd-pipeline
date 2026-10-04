#!/bin/bash

BUDGET=${BUDGET:-80}

AZURE=$(python3 -c "import json; print(json.load(open('terraform-infra/cost.json'))['summary']['total_monthly_cost'])")
AWS=$(python3 -c "import json; print(json.load(open('csp-comparison/aws/cost.json'))['summary']['total_monthly_cost'])")
GCP=$(python3 -c "import json; print(json.load(open('csp-comparison/gcp/cost.json'))['summary']['total_monthly_cost'])")

echo ""
echo "===== CLOUD COST GATE ====="
echo "Budget: \$$BUDGET"
echo "Azure : \$$AZURE"
echo "AWS   : \$$AWS"
echo "GCP   : \$$GCP"
echo "==========================="

if python3 -c "import sys; sys.exit(0 if float('$AZURE') <= float('$BUDGET') else 1)"
then
    echo ""
    echo "WITHIN BUDGET"
    echo "DEFAULT CSP: Azure"
    echo "WITHIN_BUDGET"
    exit 0
else
    echo ""
    echo "OVER BUDGET"
    echo "CSP comparison required."
    echo "OVER_BUDGET"
    exit 0
fi