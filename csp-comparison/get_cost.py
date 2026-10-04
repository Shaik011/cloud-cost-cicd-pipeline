import json
import sys

KEYS = ("totalMonthlyCost", "total_monthly_cost", "monthlyCost", "monthly_cost")


def find_cost(obj):
    if isinstance(obj, dict):
        for key in KEYS:
            if key in obj and isinstance(obj[key], (str, int, float)):
                try:
                    return float(obj[key])
                except ValueError:
                    pass
        for value in obj.values():
            found = find_cost(value)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = find_cost(item)
            if found is not None:
                return found
    return None


def main():
    path = sys.argv[1]
    with open(path) as f:
        data = json.load(f)

    cost = find_cost(data)
    if cost is None:
        keys = list(data.keys()) if isinstance(data, dict) else type(data).__name__
        print("ERROR: could not find a monthly cost in " + path)
        print("Top-level keys: " + str(keys))
        sys.exit(1)
    if cost == 0:
        print("ERROR: monthly cost is 0 - resources may be unpriced")
        sys.exit(1)

    print("Azure: $%.2f/month" % cost)


if __name__ == "__main__":
    main()