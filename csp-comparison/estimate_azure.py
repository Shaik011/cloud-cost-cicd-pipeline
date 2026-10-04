import json
import sys
import urllib.parse
import urllib.request

REGION = "centralindia"
VM_SIZE = "Standard_B2s_v2"
NODE_COUNT = 1
HOURS_PER_MONTH = 730
DAYS_PER_MONTH = 30.4


def query(filter_str):
    url = "https://prices.azure.com/api/retail/prices?$filter=" + urllib.parse.quote(filter_str)
    items = []
    while url:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.load(resp)
        items += data.get("Items", [])
        url = data.get("NextPageLink")
    return items


def monthly(item):
    price = float(item["retailPrice"])
    unit = item["unitOfMeasure"].lower()
    if "hour" in unit:
        return price * HOURS_PER_MONTH
    if "day" in unit:
        return price * DAYS_PER_MONTH
    if "month" in unit:
        return price
    raise ValueError("Unknown unit: " + item["unitOfMeasure"])


def vm_price():
    items = query(
        "serviceName eq 'Virtual Machines' and armRegionName eq '%s' "
        "and armSkuName eq '%s' and priceType eq 'Consumption'" % (REGION, VM_SIZE)
    )
    items = [
        i for i in items
        if "Windows" not in i["productName"]
        and "Spot" not in i["skuName"]
        and "Low Priority" not in i["skuName"]
        and float(i["retailPrice"]) > 0
    ]
    if not items:
        raise RuntimeError("No Linux price found for " + VM_SIZE + " in " + REGION)
    return monthly(items[0]) * NODE_COUNT


def acr_price():
    items = query(
        "serviceName eq 'Container Registry' and armRegionName eq '%s' "
        "and skuName eq 'Basic'" % REGION
    )
    items = [i for i in items if float(i["retailPrice"]) > 0]
    if not items:
        raise RuntimeError("No ACR Basic price found in " + REGION)
    return monthly(items[0])


def main():
    out_path = sys.argv[1]

    resources = [
        {"name": "AKS node (%s x%d)" % (VM_SIZE, NODE_COUNT), "monthly_cost": round(vm_price(), 2)},
        {"name": "Container Registry (Basic)", "monthly_cost": round(acr_price(), 2)},
        {"name": "AKS control plane (Free tier)", "monthly_cost": 0.0},
        {"name": "Resource group + role assignment", "monthly_cost": 0.0},
    ]
    total = round(sum(r["monthly_cost"] for r in resources), 2)

    result = {
        "provider": "Azure",
        "region": REGION,
        "summary": {"total_monthly_cost": total, "currency": "USD"},
        "resources": resources,
    }
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)

    print("Azure estimate (" + REGION + "):")
    for r in resources:
        print("  %-36s $%.2f/month" % (r["name"], r["monthly_cost"]))
    print("  TOTAL: $%.2f/month" % total)


if __name__ == "__main__":
    main()