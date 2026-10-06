import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import prices_live as live

HOURS = 730.0
DAYS = 30.4
HERE = os.path.dirname(os.path.abspath(__file__))

FREE_TYPES = {
    "azurerm_resource_group", "azurerm_role_assignment", "azurerm_virtual_network",
    "azurerm_subnet", "azurerm_network_security_group", "azurerm_user_assigned_identity",
    "azurerm_network_security_rule", "azurerm_subnet_network_security_group_association",
    "azurerm_storage_container",
}

OUTPUTS = {
    "Azure": "terraform-infra/cost.json",
    "AWS": "csp-comparison/aws/cost.json",
    "GCP": "csp-comparison/gcp/cost.json",
}


# ---------- reading the plan ----------

def load_plan(path):
    with open(path) as f:
        data = json.load(f)
    items = []
    for rc in data.get("resource_changes", []):
        if rc["change"]["actions"] == ["delete"]:
            continue
        items.append({
            "address": rc["address"],
            "type": rc["type"],
            "after": rc["change"].get("after") or {},
        })
    return items


def first(v):
    if isinstance(v, list):
        return v[0] if v else {}
    return v or {}


def node_count(pool):
    if pool.get("enable_auto_scaling") or pool.get("auto_scaling_enabled"):
        return int(pool.get("max_count") or pool.get("node_count") or 1)  # worst case
    return int(pool.get("node_count") or 1)


def build_demands(items):
    demands, free, unknown = [], [], []
    for r in items:
        t, a, addr = r["type"], r["after"], r["address"]
        if t == "azurerm_kubernetes_cluster":
            demands.append({"kind": "k8s", "name": addr, "tier": a.get("sku_tier") or "Free"})
            p = first(a.get("default_node_pool"))
            demands.append({"kind": "compute", "name": addr + " default pool",
                            "size": p.get("vm_size"), "count": node_count(p), "os": "linux"})
        elif t == "azurerm_kubernetes_cluster_node_pool":
            demands.append({"kind": "compute", "name": addr, "size": a.get("vm_size"),
                            "count": node_count(a), "os": (a.get("os_type") or "linux").lower()})
        elif t in ("azurerm_linux_virtual_machine", "azurerm_windows_virtual_machine"):
            demands.append({"kind": "compute", "name": addr, "size": a.get("size"), "count": 1,
                            "os": "windows" if "windows" in t else "linux"})
        elif t == "azurerm_container_registry":
            demands.append({"kind": "registry", "name": addr, "sku": a.get("sku") or "Basic"})
        elif t == "azurerm_storage_account":
            demands.append({"kind": "storage", "name": addr,
                            "tier": a.get("account_tier") or "Standard",
                            "repl": a.get("account_replication_type") or "LRS",
                            "access": a.get("access_tier") or "Hot"})
        elif t == "azurerm_managed_disk":
            demands.append({"kind": "disk", "name": addr, "gb": int(a.get("disk_size_gb") or 0),
                            "type": a.get("storage_account_type") or "Standard_LRS"})
        elif t in FREE_TYPES:
            free.append(addr)
        else:
            unknown.append(addr + " (" + t + ")")
    return demands, free, unknown


def region_of(items):
    for r in items:
        loc = r["after"].get("location")
        if loc:
            return loc.lower().replace(" ", "")
    return "centralindia"


# ---------- Azure live prices ----------

def query(filter_str):
    url = "https://prices.azure.com/api/retail/prices?$filter=" + urllib.parse.quote(filter_str)
    out = []
    while url:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.load(resp)
        out += data.get("Items", [])
        url = data.get("NextPageLink")
    return out


def monthly(item):
    price, unit = float(item["retailPrice"]), item["unitOfMeasure"].lower()
    if "hour" in unit:
        return price * HOURS
    if "day" in unit:
        return price * DAYS
    if "month" in unit:
        return price
    raise ValueError("Unknown unit " + item["unitOfMeasure"])


def azure_vm_monthly(size, region, os_name):
    items = query("serviceName eq 'Virtual Machines' and armRegionName eq '%s' "
                  "and armSkuName eq '%s' and priceType eq 'Consumption'" % (region, size))
    items = [i for i in items if "Spot" not in i["skuName"] and "Low Priority" not in i["skuName"]
             and float(i["retailPrice"]) > 0]
    want_windows = os_name == "windows"
    items = [i for i in items if ("Windows" in i["productName"]) == want_windows]
    if not items:
        raise RuntimeError("no Azure price for " + size + " in " + region)
    return monthly(items[0])


def azure_acr_monthly(sku, region):
    items = query("serviceName eq 'Container Registry' and armRegionName eq '%s' "
                  "and skuName eq '%s'" % (region, sku))
    items = [i for i in items if float(i["retailPrice"]) > 0]
    units = [i for i in items if "Registry Unit" in i.get("meterName", "")]
    items = units or items
    if not items:
        raise RuntimeError("no Azure price for ACR " + sku)
    return monthly(items[0])


DISK_TYPES = {
    "Premium_LRS": ("P", [(4, 1), (8, 2), (16, 3), (32, 4), (64, 6), (128, 10), (256, 15),
                          (512, 20), (1024, 30), (2048, 40), (4096, 50), (8192, 60)]),
    "StandardSSD_LRS": ("E", [(4, 1), (8, 2), (16, 3), (32, 4), (64, 6), (128, 10), (256, 15),
                              (512, 20), (1024, 30), (2048, 40), (4096, 50), (8192, 60)]),
    "Standard_LRS": ("S", [(32, 4), (64, 6), (128, 10), (256, 15), (512, 20), (1024, 30),
                           (2048, 40), (4096, 50), (8192, 60)]),
}
SKIP_WORDS = ("operation", "mount", "snapshot", "burst", "transaction")


def azure_storage_monthly(d, region, gb):
    if d["tier"].lower() != "standard":
        raise RuntimeError("Premium storage accounts are not priced")
    sku = "%s %s" % (d["access"], d["repl"])
    items = query("serviceName eq 'Storage' and armRegionName eq '%s' and skuName eq '%s'" % (region, sku))
    items = [i for i in items if "Data Stored" in i.get("meterName", "")
             and ("Block Blob" in i["productName"] or "Blob Storage" in i["productName"])
             and float(i["retailPrice"]) > 0]
    if not items:
        raise RuntimeError("no Azure price for storage '%s' in %s" % (sku, region))
    items.sort(key=lambda i: float(i.get("tierMinimumUnits", 0) or 0))
    return float(items[0]["retailPrice"]) * gb


def azure_disk_monthly(d, region):
    if d["type"] not in DISK_TYPES:
        raise RuntimeError("disk type " + d["type"] + " not priced")
    if d["gb"] <= 0:
        raise RuntimeError("disk size unknown in plan")
    letter, tiers = DISK_TYPES[d["type"]]
    fit = [n for size, n in tiers if size >= d["gb"]]
    if not fit:
        raise RuntimeError("disk size too large")
    sku = "%s%d LRS" % (letter, fit[0])
    items = query("serviceName eq 'Storage' and armRegionName eq '%s' and skuName eq '%s'" % (region, sku))
    items = [i for i in items if "Managed Disks" in i["productName"] and float(i["retailPrice"]) > 0
             and not any(w in (i.get("meterName", "") + i["productName"]).lower() for w in SKIP_WORDS)]
    if not items:
        raise RuntimeError("no Azure price for disk " + sku)
    return monthly(items[0]), sku


# ---------- VM size -> vCPU / memory ----------

def size_specs(size, region, table):
    try:
        out = subprocess.run(["az", "vm", "list-sizes", "--location", region, "-o", "json"],
                             capture_output=True, text=True, timeout=60)
        if out.returncode == 0:
            for s in json.loads(out.stdout):
                if s["name"] == size:
                    return s["numberOfCores"], s["memoryInMb"] / 1024.0
    except Exception:
        pass
    if size in table["azure_sizes"]:
        v, m = table["azure_sizes"][size]
        return v, float(m)
    return None


def equivalent(cloud_table, vcpu, mem):
    ok = [c for c in cloud_table["compute"] if c["vcpu"] >= vcpu and c["memory_gb"] >= mem]
    return min(ok, key=lambda c: c["hourly"]) if ok else None


# ---------- pricing each cloud ----------

def price_azure(demands, region, table):
    rows, notes = [], []
    for d in demands:
        try:
            if d["kind"] == "k8s":
                tier = d["tier"].lower()
                if tier == "free":
                    cost = 0.0
                elif tier == "standard":
                    cost = table["azure"]["aks_standard_tier_hourly"] * HOURS
                else:
                    notes.append(d["name"] + ": AKS tier " + d["tier"] + " not priced")
                    continue
                rows.append(("AKS control plane (%s tier) [LIVE]" % d["tier"], cost))
            elif d["kind"] == "compute":
                cost = azure_vm_monthly(d["size"], region, d["os"]) * d["count"]
                rows.append(("%s (%s x%d) [LIVE]" % (d["name"], d["size"], d["count"]), cost))
            elif d["kind"] == "registry":
                rows.append(("%s (ACR %s) [LIVE]" % (d["name"], d["sku"]), azure_acr_monthly(d["sku"], region)))
            elif d["kind"] == "storage":
                gb = table["assumptions"]["storage_account_gb"]
                rows.append(("%s (%s %s, assumed %d GB) [LIVE]" % (d["name"], d["access"], d["repl"], gb),
                             azure_storage_monthly(d, region, gb)))
            elif d["kind"] == "disk":
                cost, sku = azure_disk_monthly(d, region)
                rows.append(("%s (%s, %d GB) [LIVE]" % (d["name"], sku, d["gb"]), cost))
        except Exception as e:
            notes.append(d["name"] + ": " + str(e))
    return rows, notes


def live_or_ref(fn, ref, notes, what):
    try:
        return fn(), "LIVE"
    except Exception as e:
        notes.append("%s: live lookup failed (%s) - REFERENCE price used" % (what, e))
        return ref, "REFERENCE"


def tag(src):
    return "[LIVE]" if src == "LIVE" else "[REF]"


def price_aws(demands, region, table):
    t = table["aws"]
    rows, notes = [], []
    code = table.get("regions", {}).get(region, {}).get("aws")
    if not code:
        notes.append("region " + region + " not in price_table.json 'regions' - AWS uses REFERENCE prices")
    cache = {}

    def ec2():
        if "ec2" not in cache:
            cache["ec2"] = live.aws_ec2(code, t.get("families", ["t3", "t3a", "m5", "m6i"]))
        return cache["ec2"]

    def gp3():
        v = ec2()[1]
        if not v:
            raise RuntimeError("no gp3 price in file")
        return v

    for d in demands:
        if d["kind"] == "k8s":
            cost, src = live_or_ref(lambda: live.aws_eks_hourly(code) * HOURS,
                                    t["k8s_control_plane_hourly"] * HOURS, notes, "EKS control plane") if code \
                else (t["k8s_control_plane_hourly"] * HOURS, "REFERENCE")
            rows.append(("Kubernetes control plane (EKS) " + tag(src), cost))
        elif d["kind"] == "compute":
            specs = size_specs(d["size"], region, table) if d["size"] else None
            if not specs:
                notes.append(d["name"] + ": unknown vCPU/memory for " + str(d["size"]))
                continue
            ref = equivalent(t, specs[0], specs[1])
            try:
                if not code:
                    raise RuntimeError("no region mapping")
                itype, _, _, hourly = live.pick_instance(ec2()[0], specs[0], specs[1])
                src = "LIVE"
            except Exception as e:
                if not ref:
                    notes.append(d["name"] + ": no AWS price (%s)" % e)
                    continue
                if code:
                    notes.append(d["name"] + ": live lookup failed (%s) - REFERENCE price used" % e)
                itype, hourly, src = ref["type"], ref["hourly"], "REFERENCE"
            rows.append(("%s (%s x%d) %s" % (d["name"], itype, d["count"], tag(src)), hourly * HOURS * d["count"]))
        elif d["kind"] == "registry":
            gb = table["assumptions"]["registry_storage_gb"]
            rate, src = live_or_ref(lambda: live.aws_ecr_gb_month(code), t["registry_gb_month"], notes, "ECR") if code \
                else (t["registry_gb_month"], "REFERENCE")
            rows.append(("%s (ECR, %d GB) %s" % (d["name"], gb, tag(src)), rate * gb))
        elif d["kind"] == "storage":
            gb = table["assumptions"]["storage_account_gb"]
            rate, src = live_or_ref(lambda: live.aws_s3_gb_month(code), t["object_storage_gb_month"], notes, "S3") if code \
                else (t["object_storage_gb_month"], "REFERENCE")
            rows.append(("%s (S3, assumed %d GB) %s" % (d["name"], gb, tag(src)), rate * gb))
        elif d["kind"] == "disk":
            if d["gb"] <= 0:
                notes.append(d["name"] + ": disk size unknown in plan")
                continue
            rate, src = live_or_ref(gp3, t["disk_gb_month"], notes, "EBS gp3") if code else (t["disk_gb_month"], "REFERENCE")
            rows.append(("%s (EBS, %d GB) %s" % (d["name"], d["gb"], tag(src)), rate * d["gb"]))
    return rows, notes


def price_gcp(demands, region, table):
    t = table["gcp"]
    rows, notes = [], []
    code = table.get("regions", {}).get(region, {}).get("gcp")
    key = os.environ.get("GCP_API_KEY")
    if not key:
        notes.append("GCP_API_KEY not set - GCP uses REFERENCE prices")
    elif not code:
        notes.append("region " + region + " not in price_table.json 'regions' - GCP uses REFERENCE prices")
    rates = None
    if key and code:
        try:
            rates = live.gcp_compute_rates(code, key)
        except Exception as e:
            notes.append("GCP compute: live lookup failed (%s) - REFERENCE price used" % e)

    for d in demands:
        if d["kind"] == "k8s":
            rows.append(("Kubernetes control plane (GKE) [REF]", t["k8s_control_plane_hourly"] * HOURS))
        elif d["kind"] == "compute":
            specs = size_specs(d["size"], region, table) if d["size"] else None
            if not specs:
                notes.append(d["name"] + ": unknown vCPU/memory for " + str(d["size"]))
                continue
            if rates:
                name, hourly = live.gcp_instance_hourly(rates, specs[0], specs[1])
                src = "LIVE"
            else:
                eq = equivalent(t, specs[0], specs[1])
                if not eq:
                    notes.append(d["name"] + ": no gcp size with %d vCPU / %.0f GB" % (specs[0], specs[1]))
                    continue
                name, hourly, src = eq["type"], eq["hourly"], "REFERENCE"
            rows.append(("%s (%s x%d) %s" % (d["name"], name, d["count"], tag(src)), hourly * HOURS * d["count"]))
        elif d["kind"] == "registry":
            gb = table["assumptions"]["registry_storage_gb"]
            rows.append(("%s (Artifact Registry, %d GB) [REF]" % (d["name"], gb), t["registry_gb_month"] * gb))
        elif d["kind"] == "storage":
            gb = table["assumptions"]["storage_account_gb"]
            rows.append(("%s (Cloud Storage, assumed %d GB) [REF]" % (d["name"], gb), t["object_storage_gb_month"] * gb))
        elif d["kind"] == "disk":
            if d["gb"] <= 0:
                notes.append(d["name"] + ": disk size unknown in plan")
                continue
            rows.append(("%s (disk, %d GB) [REF]" % (d["name"], d["gb"]), t["disk_gb_month"] * d["gb"]))
    return rows, notes


def write(cloud, region, rows, free, notes):
    total = round(sum(c for _, c in rows), 2)
    data = {
        "provider": cloud, "region": region,
        "summary": {"total_monthly_cost": total, "currency": "USD"},
        "resources": [{"name": n, "monthly_cost": round(c, 2)} for n, c in rows]
                     + [{"name": f, "monthly_cost": 0.0} for f in free],
        "not_estimated": notes,
    }
    with open(OUTPUTS[cloud], "w") as f:
        json.dump(data, f, indent=2)
    return total


def main():
    plan = sys.argv[1]
    strict = os.environ.get("FAIL_ON_UNESTIMATED") == "1"
    with open(os.path.join(HERE, "price_table.json")) as f:
        table = json.load(f)

    items = load_plan(plan)
    demands, free, unknown = build_demands(items)
    region = region_of(items)

    print("Region: " + region + "   [LIVE] = fetched now, [REF] = reference table (updated " + table["updated"] + ")")
    problems = list(unknown)
    for cloud in ("Azure", "AWS", "GCP"):
        if cloud == "Azure":
            rows, notes = price_azure(demands, region, table)
        elif cloud == "AWS":
            rows, notes = price_aws(demands, region, table)
        else:
            rows, notes = price_gcp(demands, region, table)
        total = write(cloud, region, rows, free, notes + [u + ": not estimated" for u in unknown])
        print("")
        print(cloud)
        for n, c in rows:
            print("  %-48s $%9.2f" % (n, c))
        print("  %-48s $%9.2f" % ("TOTAL / month", total))
        problems += notes if cloud == "Azure" else []
        for n in notes:
            print("  WARNING: " + n)

    if unknown:
        print("")
        print("WARNING - resource types with no price model (NOT counted):")
        for u in unknown:
            print("  - " + u)
    if strict and problems:
        print("FAIL_ON_UNESTIMATED=1 and some resources could not be priced.")
        sys.exit(1)


if __name__ == "__main__":
    main()