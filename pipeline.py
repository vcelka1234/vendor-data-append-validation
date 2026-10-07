"""
pipeline.py
Validates three vendor return files, standardizes them, applies a vendor
priority waterfall (A > B > C), and writes Tableau-ready summary tables.

Run after generate_data.py:  python pipeline.py
Outputs in data/output/:
  validation_results.csv   one row per vendor x check, with PASS/WARN/FAIL
  waterfall_summary.csv    standalone vs. added coverage by vendor
  match_by_segment.csv     match rate by vendor, urban/rural, age band
  vendor_agreement.csv     phone agreement where vendors overlap
  call_outcomes.csv        simulated call results by source vendor
  final_contact_file.csv   household-level file sent downstream
"""
import re
import numpy as np
import pandas as pd
from pathlib import Path

RAW, OUT = Path("data/raw"), Path("data/output")
PRIORITY = ["A", "B", "C"]

# Layout map: each vendor's file -> standard columns.
# When a vendor changes its layout, only this config needs updating.
LAYOUTS = {
    "A": {"file": "vendor_a_return.csv", "sep": ",",
          "cols": {"hh_id": "hh_id", "phone": "phone", "match": "match_flag"},
          "match_yes": "Y"},
    "B": {"file": "vendor_b_return.csv", "sep": ",",
          "cols": {"hh_id": "HouseholdID", "phone": "PhoneNumber", "match": "MatchInd"},
          "match_yes": "1"},
    "C": {"file": "vendor_c_return.txt", "sep": "|",
          "cols": {"hh_id": "cust_ref", "phone": "phone_nbr", "match": "hit"},
          "match_yes": "HIT"},
}


def status(value, warn, fail, higher_is_bad=True):
    if higher_is_bad:
        return "FAIL" if value >= fail else "WARN" if value >= warn else "PASS"
    return "FAIL" if value <= fail else "WARN" if value <= warn else "PASS"


def clean_phone(p):
    digits = re.sub(r"\D", "", str(p)) if pd.notna(p) else ""
    # valid US number: 10 digits, area code and exchange not starting with 0 or 1
    if len(digits) == 10 and digits[0] not in "01" and digits[3] not in "01":
        return digits
    return None


def load_vendor(v, sent_ids):
    cfg = LAYOUTS[v]
    raw = pd.read_csv(RAW / cfg["file"], sep=cfg["sep"], dtype=str)
    checks = []

    def add(check, value, stat, detail=""):
        checks.append({"vendor": f"Vendor {v}", "check": check, "value": value,
                       "status": stat, "detail": detail})

    # 1. Schema / layout check
    missing_cols = [c for c in cfg["cols"].values() if c not in raw.columns]
    add("Expected columns present", len(missing_cols), "FAIL" if missing_cols else "PASS",
        ", ".join(missing_cols) or "all present")
    df = raw.rename(columns={src: std for std, src in cfg["cols"].items()})[list(cfg["cols"])]

    # 2. Record count reconciliation
    diff = len(df) - len(sent_ids)
    add("Record count vs. sent", diff, status(abs(diff) / len(sent_ids), 0.001, 0.01),
        f"received {len(df):,} / sent {len(sent_ids):,}")

    # 3. IDs returned that were never sent
    unknown = (~df["hh_id"].isin(sent_ids)).sum()
    add("IDs not in outbound file", unknown, status(unknown, 1, 100))

    # 4. Sent IDs missing from return
    missing = len(sent_ids - set(df["hh_id"]))
    add("Sent IDs missing from return", missing, status(missing / len(sent_ids), 0.001, 0.01))

    # 5. Duplicate IDs
    dups = df["hh_id"].duplicated().sum()
    add("Duplicate household IDs", dups, status(dups, 1, 500))

    # Keep only valid, unique, known IDs from here on
    df = df[df["hh_id"].isin(sent_ids)].drop_duplicates("hh_id")
    df["matched"] = df["match"].astype(str) == cfg["match_yes"]

    # 6. Phone format validity among matched
    df["phone_clean"] = df["phone"].map(clean_phone)
    m = df[df["matched"]]
    invalid = m["phone_clean"].isna().sum()
    add("Invalid phone format (matched)", invalid,
        status(invalid / max(len(m), 1), 0.005, 0.03), f"{invalid / max(len(m),1):.1%} of matches")

    # 7. Same phone on multiple households
    shared = m["phone_clean"].dropna().duplicated(keep=False).sum()
    add("Phone shared across households", shared, status(shared, 1, 200))

    df["has_phone"] = df["matched"] & df["phone_clean"].notna()
    return df[["hh_id", "has_phone", "phone_clean"]], checks


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    hh = pd.read_csv(RAW / "outbound_households.csv", dtype=str)
    sent = set(hh["hh_id"])

    vendors, checks = {}, []
    for v in PRIORITY:
        vendors[v], c = load_vendor(v, sent)
        checks += c
    # Layout-drift test: next year's Vendor C file is checked against the same layout map
    nxt = pd.read_csv(RAW / "vendor_c_return_next_year.txt", sep="|", dtype=str, nrows=5)
    missing_cols = [c for c in LAYOUTS["C"]["cols"].values() if c not in nxt.columns]
    checks.append({"vendor": "Vendor C (next year)", "check": "Expected columns present",
                   "value": len(missing_cols), "status": "FAIL" if missing_cols else "PASS",
                   "detail": f"missing: {', '.join(missing_cols)}; found: {', '.join(nxt.columns)}"})
    pd.DataFrame(checks).to_csv(OUT / "validation_results.csv", index=False)

    # Wide household table: one column per vendor's phone
    wide = hh.copy()
    for v, df in vendors.items():
        df = df[df["has_phone"]].set_index("hh_id")["phone_clean"]
        wide[f"phone_{v}"] = wide["hh_id"].map(df)

    # Waterfall: take the first vendor in priority order that has a phone
    wide["final_phone"], wide["source_vendor"] = None, None
    rows = []
    for order, v in enumerate(PRIORITY, 1):
        has = wide[f"phone_{v}"].notna()
        new = has & wide["final_phone"].isna()
        wide.loc[new, "final_phone"] = wide.loc[new, f"phone_{v}"]
        wide.loc[new, "source_vendor"] = f"Vendor {v}"
        rows.append({"order": order, "vendor": f"Vendor {v}",
                     "standalone_matches": int(has.sum()),
                     "standalone_rate": has.mean(),
                     "new_matches_added": int(new.sum()),
                     "cumulative_matches": int(wide["final_phone"].notna().sum()),
                     "cumulative_rate": wide["final_phone"].notna().mean()})
    rows.append({"order": 4, "vendor": "No phone (in-person follow-up)",
                 "standalone_matches": None, "standalone_rate": None,
                 "new_matches_added": int(wide["final_phone"].isna().sum()),
                 "cumulative_matches": len(wide), "cumulative_rate": 1.0})
    pd.DataFrame(rows).to_csv(OUT / "waterfall_summary.csv", index=False)

    # Match rate by segment (long format for Tableau)
    seg = []
    for v in PRIORITY:
        t = wide.assign(matched=wide[f"phone_{v}"].notna())
        g = t.groupby(["urban_rural", "age_band"]).agg(sent=("hh_id", "size"), matched=("matched", "sum")).reset_index()
        g["vendor"] = f"Vendor {v}"
        seg.append(g)
    g = wide.assign(matched=wide["final_phone"].notna()) \
        .groupby(["urban_rural", "age_band"]).agg(sent=("hh_id", "size"), matched=("matched", "sum")).reset_index()
    g["vendor"] = "Combined (waterfall)"
    seg.append(g)
    seg = pd.concat(seg)
    seg["match_rate"] = seg["matched"] / seg["sent"]
    seg.to_csv(OUT / "match_by_segment.csv", index=False)

    # Agreement between vendors where both returned a phone
    agree = []
    for a, b in [("A", "B"), ("A", "C"), ("B", "C")]:
        both = wide[f"phone_{a}"].notna() & wide[f"phone_{b}"].notna()
        same = (wide.loc[both, f"phone_{a}"] == wide.loc[both, f"phone_{b}"]).sum()
        agree.append({"pair": f"Vendor {a} vs Vendor {b}", "overlap_households": int(both.sum()),
                      "same_phone": int(same), "agreement_rate": same / max(both.sum(), 1)})
    pd.DataFrame(agree).to_csv(OUT / "vendor_agreement.csv", index=False)

    # Simulated call outcomes (feedback loop): wrong phones mostly end as disconnected/wrong
    truth = pd.read_csv(RAW / "_truth_phones.csv", dtype=str).set_index("hh_id")["true_phone"]
    rng = np.random.default_rng(7)
    called = wide[wide["final_phone"].notna()].copy()
    correct = called["final_phone"].values == called["hh_id"].map(truth).values
    r = rng.random(len(called))
    called["call_result"] = np.where(
        correct,
        np.select([r < 0.55, r < 0.90], ["Completed interview", "No answer / refused"], "Disconnected"),
        np.select([r < 0.60, r < 0.95], ["Disconnected", "Wrong number"], "No answer / refused"))
    outcomes = called.groupby(["source_vendor", "call_result"]).size().reset_index(name="households")
    outcomes["share"] = outcomes["households"] / outcomes.groupby("source_vendor")["households"].transform("sum")
    outcomes.to_csv(OUT / "call_outcomes.csv", index=False)

    final = wide[["hh_id", "street", "state", "zip", "urban_rural", "age_band",
                  "customer_type", "final_phone", "source_vendor"]]
    final.to_csv(OUT / "final_contact_file.csv", index=False)

    print(pd.DataFrame(checks).to_string(index=False))
    print()
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
