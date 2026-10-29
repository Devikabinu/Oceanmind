# Plan for the third benchmark run (written BEFORE it was run; not edited afterwards)

Purpose: the first two runs disagreed (2-year block / summer test: hybrid worst; 3-year block / winter-spring test: hybrid best, but not clearly better than CNN-only).
This run is a stronger, fair test: more training data, a test block covering every season, more seeds, paired comparisons.

## Fixed in advance
* Block: 2374 continuous days ending at the last NOAA FINAL day (2026-10-12): about 5 years of training, **183 days validation, 365 days test (the last 12 months, all four seasons)**.
* Same region (28-44N, 150-130W), 0.5 degree grid, same 6 input channels, same 7-day window and 1-7 day horizons, same training settings (AdamW, constant lr, batch 8, early stopping on validation), same model sizes (CNN-only 127,913 / LSTM-only 125,895 / hybrid 127,239 parameters). The hybrid architecture is unchanged.
* **5 seeds** per model (0-4). Climatology and normalisation from data before the validation block / the train block only.
* Config: `scripts/benchmark/benchmark_config_5yr.yaml`. Output: `processed/benchmark/followup_5yr_fullyear/`.

## How the result will be judged (decision rule)
* Primary metric: mean RMSE over horizons 1-7 on the full 12-month test block. Secondary: MAE, ACC, per-season RMSE, RMSE by horizon.
* "The hybrid is clearly better than model X" will be written ONLY IF the hybrid is better than X in **all 5 seeds** (paired by seed) AND the mean gap is **larger than the seed-to-seed standard deviation of the paired differences**. Otherwise the wording is "comparable / within noise" (or "worse" if the roles are reversed).
* Per-season results are reported even if they disagree with the full-year result.
* This is the last benchmark run for this question. Whatever it shows is reported next to the first two runs; no run is removed, re-run with different settings, or re-interpreted afterwards.
