# Multi-Vendor Data Append: Validation & Coverage Waterfall

A small, end-to-end version of a vendor data-append process: send a household file
to three vendors, validate what comes back, combine vendors with a priority rule,
and measure match rates, vendor agreement, and downstream outcomes.
All data is synthetic; vendor names are generic.

## Run it in your browser (no setup)
[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/vcelka1234/vendor-data-append-validation/blob/main/vendor_append_walkthrough.ipynb)

Click the badge to open the step-by-step walkthrough notebook in Google Colab, then choose
**Runtime → Run all**. It runs in about a minute and shows every validation check, the coverage
waterfall, segment match rates, vendor agreement, and call outcomes, with charts.
You can also click `vendor_append_walkthrough.ipynb` in the file list above to read it, with results, right here on GitHub.

## Interactive dashboards
Two Tableau dashboards built from the output tables:
**Feed Health** (validation results) and **Vendor Performance** (coverage, gaps and accuracy).

[View on Tableau Public](https://public.tableau.com/views/VendorDataAppendValidationCoverage/Dashboard_VendorValid?:language=en-US&:sid=&:redirect=auth&:display_count=n&:origin=viz_share_link)

## Why this project
It mirrors a process I ran every year at Nielsen (phone appends from three vendors
for ~40,000 survey households) and applies the same approach to the vendor
audience-data work done by media/marketing data teams: outbound feeds, return-file
validation, match rates, and vendor evaluation.

## How to run the scripts on your own computer
```
pip install -r requirements.txt
python generate_data.py   # writes data/raw/
python pipeline.py        # writes data/output/
```

## What the pipeline checks
| Check | Why it matters |
|---|---|
| Expected columns present | Catches vendor layout changes before data loads |
| Record count vs. sent | Reconciles what came back with what was sent |
| IDs not in outbound file | Records the vendor should not have returned |
| Sent IDs missing from return | Records lost in delivery |
| Duplicate household IDs | Prevents double-counting |
| Invalid phone format | Unusable records |
| Phone shared across households | Possible bad links in vendor data |

Each check is scored PASS / WARN / FAIL. A layout map (`LAYOUTS` in `pipeline.py`)
translates each vendor's columns to a standard layout, so a vendor layout change
means updating one config entry instead of the code. The included
"next year" Vendor C file has a renamed phone field and fails the layout check on purpose.

## Outputs (Tableau-ready, in data/output/)
The summary tables are included in this repository. The raw vendor files are not stored here; run the two scripts to recreate them.
| File | Use in Tableau |
|---|---|
| validation_results.csv | Feed-health table with PASS/WARN/FAIL colors |
| waterfall_summary.csv | Coverage waterfall: what each vendor adds |
| match_by_segment.csv | Match rate by vendor, urban/rural, age band |
| vendor_agreement.csv | How often vendors return the same phone |
| call_outcomes.csv | Downstream feedback: completed vs. disconnected/wrong by vendor |
| final_contact_file.csv | Household-level file sent downstream (not stored in the repo; created when you run the pipeline) |

## Key findings (synthetic data)
- Vendor A alone covers ~61% of households; adding B and C raises coverage to ~84%.
- Vendor C adds only ~7% new coverage and has the highest disconnected/wrong-number share.
- Match rates are lowest for rural and 18–34 households, a coverage gap worth flagging
  before using the data for targeting or measurement.
