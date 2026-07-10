import requests, json

headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Referer": "https://cafef.vn/"}

# Check SSI's income statement codes
r = requests.get(
    "https://apiweb.cafef.vn/api/v1/BCTC/GetReportSummary",
    params={"symbol": "SSI", "pageIndex": 1, "pageSize": 4, "reportType": "KQKD", "TypeTime": "QUY"},
    headers=headers, timeout=10
)
d = r.json()
# Print template
print("SSI KQKD template:")
for item in d["value"]["templace"][0]["data"]:
    print(f"  {item['code']}: {item['name']}")
print()
# Print first quarter codes
q = d["value"]["data"][0]["data"][0]
print(f"First quarter: {q['year']}-Q{q['quater']}")
for item in q["data"]:
    print(f"  {item['code']}: {item.get('value')}")
