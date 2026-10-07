"""
generate_data.py
Creates synthetic data for a multi-vendor data-append project:
  - an outbound household file (what we send to vendors)
  - three vendor return files, each with its own layout and data problems
  - call outcomes for the final contact file (feedback loop on vendor quality)

All data is fictional. Vendor names are generic (Vendor A/B/C).
Run:  python generate_data.py
"""
import numpy as np
import pandas as pd
from pathlib import Path

SEED = 42
N_HOUSEHOLDS = 40_000
OUT = Path("data/raw")
rng = np.random.default_rng(SEED)

STATES = {  # state: (share of households, share urban)
    "IL": (0.20, 0.80), "TX": (0.25, 0.75), "FL": (0.20, 0.85),
    "CA": (0.25, 0.90), "NM": (0.10, 0.55),
}
AGE_BANDS = ["18-34", "35-49", "50-64", "65+"]
AGE_P = [0.30, 0.30, 0.25, 0.15]

# Base match propensity by vendor, then adjustments by segment
VENDORS = {
    "A": {"base": 0.62},   # strongest vendor
    "B": {"base": 0.45},
    "C": {"base": 0.38},
}
SEGMENT_ADJ = {  # added to match probability
    "urban": 0.03, "rural": -0.12,
    "18-34": -0.15, "35-49": 0.00, "50-64": 0.06, "65+": 0.10,
}


def make_phone():
    area = rng.integers(201, 990)
    return f"{area}{rng.integers(200, 1000):03d}{rng.integers(0, 10000):04d}"


def build_households():
    states = rng.choice(list(STATES), N_HOUSEHOLDS, p=[v[0] for v in STATES.values()])
    urban = [rng.random() < STATES[s][1] for s in states]
    df = pd.DataFrame({
        "hh_id": [f"HH{i:06d}" for i in range(1, N_HOUSEHOLDS + 1)],
        "street": [f"{rng.integers(100, 9999)} {rng.choice(['Oak','Maple','Main','Pine','Cedar','Elm','Lake','Hill'])} "
                   f"{rng.choice(['St','Ave','Rd','Blvd','Dr'])}" for _ in range(N_HOUSEHOLDS)],
        "state": states,
        "zip": [f"{rng.integers(10000, 99999)}" for _ in range(N_HOUSEHOLDS)],
        "urban_rural": np.where(urban, "urban", "rural"),
        "age_band": rng.choice(AGE_BANDS, N_HOUSEHOLDS, p=AGE_P),
        "customer_type": rng.choice(["customer", "prospect"], N_HOUSEHOLDS, p=[0.4, 0.6]),
    })
    # "truth": each household's real phone (what a perfect vendor would return)
    df["_true_phone"] = [make_phone() for _ in range(N_HOUSEHOLDS)]
    return df


def vendor_matches(hh, vendor):
    p = (VENDORS[vendor]["base"]
         + hh["urban_rural"].map(SEGMENT_ADJ)
         + hh["age_band"].map(SEGMENT_ADJ)).clip(0.02, 0.98)
    matched = rng.random(len(hh)) < p
    # accuracy: share of returned phones that are the true phone (rest are stale/wrong)
    accuracy = {"A": 0.93, "B": 0.85, "C": 0.80}[vendor]
    phones = np.where(rng.random(len(hh)) < accuracy, hh["_true_phone"],
                      [make_phone() for _ in range(len(hh))])
    return matched, phones


def vendor_a(hh):
    """Clean CSV, stable layout."""
    matched, phones = vendor_matches(hh, "A")
    df = pd.DataFrame({
        "hh_id": hh["hh_id"],
        "match_flag": np.where(matched, "Y", "N"),
        "phone": np.where(matched, phones, ""),
        "match_confidence": np.where(matched, rng.uniform(0.7, 1.0, len(hh)).round(2), np.nan),
        "homeowner": np.where(matched, rng.choice(["Y", "N"], len(hh), p=[0.6, 0.4]), ""),
    })
    df.to_csv(OUT / "vendor_a_return.csv", index=False)


def vendor_b(hh):
    """Renamed columns, formatted phones, some invalid phones, duplicate rows."""
    matched, phones = vendor_matches(hh, "B")
    fmt = [f"({p[:3]}) {p[3:6]}-{p[6:]}" for p in phones]
    fmt = np.where(rng.random(len(hh)) < 0.02, "555-01", fmt)          # truncated / invalid
    df = pd.DataFrame({
        "HouseholdID": hh["hh_id"],
        "PhoneNumber": np.where(matched, fmt, ""),
        "MatchInd": np.where(matched, 1, 0),
        "Score": np.where(matched, rng.integers(60, 100, len(hh)), ""),
    })
    dups = df.sample(300, random_state=SEED)                          # duplicate records
    df = pd.concat([df, dups]).sample(frac=1, random_state=SEED)
    df.to_csv(OUT / "vendor_b_return.csv", index=False)


def vendor_c(hh):
    """Pipe-delimited, phone field moved, records missing, IDs never sent."""
    matched, phones = vendor_matches(hh, "C")
    df = pd.DataFrame({
        "process_date": "2026-09-15",
        "phone_nbr": np.where(matched, phones, ""),
        "cust_ref": hh["hh_id"],
        "hit": np.where(matched, "HIT", "NOHIT"),
    })
    df = df.drop(df.sample(250, random_state=SEED).index)            # missing records
    extra = pd.DataFrame({"process_date": "2026-09-15",
                          "phone_nbr": [make_phone() for _ in range(40)],
                          "cust_ref": [f"HX{i:06d}" for i in range(40)],  # never sent
                          "hit": "HIT"})
    df = pd.concat([df, extra])
    df.to_csv(OUT / "vendor_c_return.txt", sep="|", index=False)
    # Next year's delivery: vendor renamed and moved the phone field (layout drift)
    nxt = df.rename(columns={"phone_nbr": "phone_number"})[["cust_ref", "hit", "phone_number", "process_date"]]
    nxt.to_csv(OUT / "vendor_c_return_next_year.txt", sep="|", index=False)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    hh = build_households()
    hh.drop(columns="_true_phone").to_csv(OUT / "outbound_households.csv", index=False)
    hh[["hh_id", "_true_phone"]].rename(columns={"_true_phone": "true_phone"}) \
        .to_csv(OUT / "_truth_phones.csv", index=False)   # used only to simulate call outcomes
    vendor_a(hh); vendor_b(hh); vendor_c(hh)
    print(f"Wrote {N_HOUSEHOLDS:,} households and 3 vendor return files to {OUT}/")


if __name__ == "__main__":
    main()
