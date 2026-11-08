# Monthly go-live check for the AAA model.
#
# usage (one line):
#   python run_monthly.py --hospital my_hospital --month 2027-01 --folder monthly_data/my_hospital/2027-01 --profile monitoring/reference_profile.joblib
#
# The folder holds features.parquet, predictions.parquet, embeddings.parquet and, when confirmed
# answers exist, labels.parquet. Exit code 2 = at least one RED alert (so a scheduler can notify someone).
import argparse, sys
from pathlib import Path
import joblib
import pandas as pd
import monitor


def read_month(folder):
    folder = Path(folder)
    df = (pd.read_parquet(folder / "features.parquet")
          .merge(pd.read_parquet(folder / "predictions.parquet"), on="case_id", how="left")
          .merge(pd.read_parquet(folder / "embeddings.parquet"), on="case_id"))
    if (folder / "labels.parquet").exists():
        df = df.merge(pd.read_parquet(folder / "labels.parquet"), on="case_id", how="left")
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hospital", required=True)
    ap.add_argument("--month", required=True, help="e.g. 2027-01")
    ap.add_argument("--folder", required=True)
    ap.add_argument("--profile", default="monitoring/reference_profile.joblib")
    ap.add_argument("--out", default="monitoring")
    a = ap.parse_args()
    prof = joblib.load(a.profile)
    res = monitor.monthly_check(read_month(a.folder), prof, a.hospital, month=a.month, out_dir=a.out)
    c = res["status"].value_counts()
    red, yel = int(c.get("RED", 0)), int(c.get("YELLOW", 0))
    print(f"{a.hospital} {a.month}: {red} red, {yel} yellow, {int(c.get('GREEN', 0))} green")
    for _, r in res[res["status"].isin(["RED", "YELLOW"])].iterrows():
        print(f"  [{r['status']}] {r['trigger']}: {r['meaning']}")
    print("report:", Path(a.out) / f"report_{a.hospital}_{a.month}.html")
    sys.exit(2 if red else 0)


if __name__ == "__main__":
    main()
