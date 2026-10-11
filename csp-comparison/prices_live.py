import csv
import json
import os
import time
import urllib.request

AWS_BASE = "https://pricing.us-east-1.amazonaws.com"
GCP_COMPUTE_SERVICE = "6F81-5844-456A"
CACHE_DIR = os.environ.get("PRICE_CACHE_DIR", os.path.expanduser("~/.cache/cloud-cost-prices"))
MAX_AGE = 7 * 24 * 3600


def http_json(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def download(url, dest):
    tmp = dest + ".part"
    with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
        while True:
            chunk = r.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
    os.replace(tmp, dest)


# ---------- AWS (public Price List bulk files, no credentials) ----------

def aws_offer_file(service, region, ext):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, "%s-%s.%s" % (service, region, ext))
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < MAX_AGE:
        return path
    idx = http_json("%s/offers/v1.0/aws/%s/current/region_index.json" % (AWS_BASE, service))
    rel = idx["regions"][region]["currentVersionUrl"]
    download(AWS_BASE + rel.replace(".json", "." + ext), path)
    return path


def aws_ec2(region, families):
    """One pass over the EC2 CSV: Linux on-demand instances + gp3 volume price."""
    path = aws_offer_file("AmazonEC2", region, "csv")
    instances, gp3 = [], None
    with open(path, newline="", encoding="utf-8") as f:
        header = None
        for line in f:
            if line.startswith('"SKU"'):
                header = next(csv.reader([line]))
                break
        if header is None:
            raise RuntimeError("EC2 price file header not found")
        for row in csv.reader(f):
            if len(row) != len(header):
                continue
            d = dict(zip(header, row))
            try:
                price = float(d.get("PricePerUnit") or 0)
            except ValueError:
                continue
            if price <= 0:
                continue
            pf = d.get("Product Family")
            if pf == "Compute Instance":
                if (d.get("Tenancy") == "Shared" and d.get("Operating System") == "Linux"
                        and d.get("Pre Installed S/W") == "NA"
                        and d.get("License Model") == "No License required"
                        and d.get("CapacityStatus") == "Used"
                        and not d.get("LeaseContractLength")):
                    itype = d.get("Instance Type", "")
                    if itype.split(".")[0] in families:
                        instances.append((itype, int(d["vCPU"]), float(d["Memory"].split()[0]), price))
            elif pf == "Storage" and d.get("Volume API Name") == "gp3":
                gp3 = price
    if not instances:
        raise RuntimeError("no EC2 instance prices found in " + path)
    return instances, gp3


def pick_instance(instances, vcpu, mem):
    ok = [i for i in instances if i[1] >= vcpu and i[2] >= mem]
    if not ok:
        raise RuntimeError("no AWS instance with %d vCPU / %.0f GB" % (vcpu, mem))
    return min(ok, key=lambda i: i[3])  # (type, vcpu, mem, hourly)


def aws_json_rate(service, region, usage_suffix):
    with open(aws_offer_file(service, region, "json")) as f:
        data = json.load(f)
    for sku, prod in data["products"].items():
        if prod["attributes"].get("usagetype", "").endswith(usage_suffix):
            for term in data["terms"]["OnDemand"].get(sku, {}).values():
                for dim in term["priceDimensions"].values():
                    price = float(dim["pricePerUnit"].get("USD", 0))
                    if price > 0 and dim.get("beginRange", "0") in ("0", "0.0"):
                        return price
    raise RuntimeError("no %s price for %s in %s" % (usage_suffix, service, region))


def aws_eks_hourly(region):
    return aws_json_rate("AmazonEKS", region, "AmazonEKS-Hours:perCluster")


def aws_s3_gb_month(region):
    return aws_json_rate("AmazonS3", region, "TimedStorage-ByteHrs")


def aws_ecr_gb_month(region):
    return aws_json_rate("AmazonECR", region, "TimedStorage-ByteHrs")


# ---------- GCP (Cloud Billing Catalog API, needs a free API key) ----------

def gcp_compute_rates(region, key, families=("E2", "N2")):
    rates = {f: {} for f in families}
    url = ("https://cloudbilling.googleapis.com/v1/services/%s/skus?key=%s&pageSize=5000&currencyCode=USD"
           % (GCP_COMPUTE_SERVICE, key))
    page = None
    while True:
        data = http_json(url + ("&pageToken=" + page if page else ""))
        for sku in data.get("skus", []):
            cat = sku.get("category", {})
            if cat.get("resourceFamily") != "Compute" or cat.get("usageType") != "OnDemand":
                continue
            if region not in sku.get("serviceRegions", []):
                continue
            desc = sku.get("description", "")
            for fam in families:
                kind = None
                if desc.startswith(fam + " Instance Core running"):
                    kind = "core"
                elif desc.startswith(fam + " Instance Ram running"):
                    kind = "ram"
                if kind:
                    tier = sku["pricingInfo"][0]["pricingExpression"]["tieredRates"][0]["unitPrice"]
                    rates[fam][kind] = int(tier.get("units", 0) or 0) + tier.get("nanos", 0) / 1e9
        page = data.get("nextPageToken")
        if not page:
            break
    good = {f: r for f, r in rates.items() if "core" in r and "ram" in r}
    if not good:
        raise RuntimeError("no GCP compute prices for " + region)
    return good


def gcp_instance_hourly(rates, vcpu, mem):
    best = min(rates.items(), key=lambda kv: vcpu * kv[1]["core"] + mem * kv[1]["ram"])
    fam, r = best
    return "%s custom/standard %dvCPU-%dGB" % (fam.lower(), vcpu, mem), vcpu * r["core"] + mem * r["ram"]