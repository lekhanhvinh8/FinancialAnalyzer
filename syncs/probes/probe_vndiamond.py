import os; os.environ["PYTHONUTF8"] = "1"
from vnstock import Listing

lst = Listing(source="KBS")

# Try known group codes including diamond variants
for code in ["VNDiamond", "VNDIAMONDTR", "VN-DIAMOND", "Diamond", "DIAMOND"]:
    try:
        df = lst.symbols_by_group(group=code)
        print(f"{code}: {len(df)} symbols -> {df['symbol'].tolist()[:10]}")
    except Exception as e:
        print(f"{code}: ERROR {str(e)[:80]}")
