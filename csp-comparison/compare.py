import json


def to_f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def res_cost(r):
    total = sum(to_f(c.get("total_monthly_cost")) for c in r.get("cost_components") or [])
    for s in r.get("subresources") or []:
        total += res_cost(s)
    return total


def load(path):
    with open(path) as f:
        d = json.load(f)
    rows = []
    if "projects" in d:
        for p in d["projects"]:
            for r in p.get("resources", []):
                rows.append((r.get("name", "?"), res_cost(r)))
    else:
        for r in d.get("resources", []):
            rows.append((r["name"], to_f(r.get("monthly_cost"))))
    total = to_f(d.get("summary", {}).get("total_monthly_cost"))
    if not total:
        total = sum(c for _, c in rows)
    return rows, total


def main():
    sources = [
        ("Azure", "terraform-infra/cost.json"),
        ("AWS", "csp-comparison/aws/cost.json"),
        ("GCP", "csp-comparison/gcp/cost.json"),
    ]
    totals = {}

    print("")
    print("===== RESOURCE-WISE COMPARISON =====")
    for name, path in sources:
        try:
            rows, total = load(path)
        except Exception as e:
            print("")
            print("%s: could not read %s (%s)" % (name, path, e))
            continue
        totals[name] = total
        print("")
        print("%s" % name)
        for rname, cost in rows:
            print("  %-40s $%8.2f" % (rname, cost))
        print("  %-40s $%8.2f" % ("TOTAL", total))

    print("")
    print("===== OVERALL (monthly) =====")
    for name, total in sorted(totals.items(), key=lambda x: x[1]):
        print("  %-8s $%8.2f" % (name, total))
    if totals:
        cheapest = min(totals, key=totals.get)
        print("")
        print("CHEAPEST: %s ($%.2f/month)" % (cheapest, totals[cheapest]))


if __name__ == "__main__":
    main()