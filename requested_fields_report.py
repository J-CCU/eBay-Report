"""
Requested-fields report (READ-ONLY: never edits eBay or Shopify)

Outputs one CSV with ONLY the requested fields, named and ordered exactly as requested.
One row per listing (multi-condition listings get one row per condition).

Run:
    python requested_fields_report.py                   # asks which account when config.yaml has more than one
    python requested_fields_report.py --account <name>  # a specific account, no menu
    python requested_fields_report.py --with-id         # also add Item Number at the front

Needs ccu_ebay_report.py in the same folder (it reuses its eBay/Shopify connection code) and config.yaml
next to the scripts or in Downloads / Documents.
Writes: ccu_report_output/requested_fields_<account>_<date>_<time>.csv
"""
import argparse, csv, datetime as dt, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ccu_ebay_report as core  # noqa: E402

# Exactly as requested, in the requested order (duplicates are intentional).
REQUESTED = [
    # Listing
    ("Listing Name", "Title"),          # the eBay listing title (not the Card Name item specific)
    # Shipping Fields
    ("Shipping Cost type", "ship_type"),
    ("Service", "service"),
    # Price
    ("Operator", "Operator"),
    ("Input", "Input"),
    ("Result", "Result"),
    # Item Specifics
    ("Brand", "Brand"),
    ("Franchise", "Franchise"),
    ("Game", "Game"),
    ("Grade", "IS: Grade"),
    ("Graded", "Graded"),
    ("Language", "Language"),
    ("Manufacturer", "Manufacturer"),
    ("Set", "Set"),
    ("Sport", "Sport"),
    # Recommended
    ("Autographed", "Autographed"),
    ("Card Name", "Card Name"),
    ("Card Number", "Card Number"),
    ("Card Type", "Card Type"),
    ("Character", "Character"),
    ("Features", "Features"),
    ("League", "League"),
    ("Player/Athlete", "Player/Athlete"),
    ("Signed By", "Signed By"),
    ("Team", "Team"),
    ("Finish", "Finish"),
    ("Rarity", "Rarity"),
    # Optional
    ("Card Condition", "IS: Card Condition"),
    ("HP", "HP"),
    ("Professional Grader", "IS: Professional Grader"),
    ("Stage", "Stage"),
    ("Year Manufactured", "Year Manufactured"),
    # Condition
    ("eBay Condition", "eBay Condition"),
    ("Card Condition", "Condition: Card Condition"),
    ("Professional Grader", "Condition: Professional Grader"),
    ("Grade", "Condition: Grade"),
    ("Certification Number", "Certification Number"),
]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", help="skip the menu and use this account")
    ap.add_argument("--config", help="path to config.yaml (default: next to this program, then Downloads / Documents)")
    ap.add_argument("--with-id", action="store_true", help="add Item Number as the first column")
    ap.add_argument("--refresh-shopify", action="store_true")
    a = ap.parse_args(argv)

    os.makedirs(core.OUT, exist_ok=True)
    a.config = core.find_config(a.config)
    print(f"Config: {a.config}")
    cfg = core.read_config(a.config)
    a.account = core.choose_account(cfg["ebay"], a.account)
    idx = core.ShopifyIndex(core.shopify_products(cfg["shopify"], a.refresh_shopify))
    eb = core.Ebay(cfg["ebay"], a.account)
    ids = eb.active_item_ids()
    print(f"eBay: {len(ids)} active listings")

    out_rows, failed = [], 0
    for n, iid in enumerate(ids, 1):
        print(f"  {n}/{len(ids)}  {iid}", end="\r")
        try:
            it, _ = eb.get_item(iid)
            d = core.parse_item(it)
        except Exception as e:
            failed += 1
            print(f"\n  could not read {iid}: {e}")
            continue
        service = "; ".join(re.sub(r"\s*\([^)]*\)$", "", s) for s in d["services"].split("; ") if s)
        for r in core.build_rows(d, idx):
            r["ship_type"] = d["ship_type"]
            r["service"] = service
            row = [r.get(src, "") for _, src in REQUESTED]
            if a.with_id:
                row = [d["item_id"]] + row
            out_rows.append(row)
    print()

    header = [name for name, _ in REQUESTED]
    if a.with_id:
        header = ["Item Number"] + header
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    path = os.path.join(core.OUT, f"requested_fields_{a.account}_{stamp}.csv")
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(out_rows)
    print(f"Rows: {len(out_rows)}   Columns: {len(header)}")
    if failed:
        print(f"Listings that could not be read: {failed}")
    print(f"CSV: {path}")
    return path


if __name__ == "__main__":
    main()
