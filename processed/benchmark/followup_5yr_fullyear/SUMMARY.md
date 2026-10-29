# Third benchmark run: 5 years of training, full-year test, 5 seeds

Run exactly as written in `PLAN.md` (decided before the run; decision rule included). Same models, settings and region as the first two runs.
All numbers are real outputs on a held-out test block (model output / derived metrics). Details: `results.json`, `results_table.md`, `error_vs_horizon.png`, `sample_maps.png`.

## Setup
| | |
|---|---|
| Block | 2020-04-13 to 2026-10-12 (2,374 continuous days), 28-44N, 150-130W, 0.5 deg grid (32 x 40) |
| Train | 2020-04-13..2025-04-12 (5 years, 1,813 windows) |
| Validation | 2025-04-13..2025-10-12 (183 d, 170 windows) |
| **Test** | **2025-10-13..2026-10-12: the last 12 months, all four seasons (352 windows)** |
| Seeds | 5 per model; sd = sample standard deviation across seeds |
| Models | CNN-only 127,913 / LSTM-only 125,895 / hybrid ConvLSTM 127,239 parameters (hybrid architecture unchanged) |
| Data source | NOAA OISST v2.1 via the PSL mirror, up to the last FINAL day (2026-10-12) |

## Results (test year, mean over horizons 1-7 days; mean +- sd over 5 seeds)

| Model | RMSE (degC) | MAE (degC) | ACC | Train time |
|---|---|---|---|---|
| **CNN-only** | **0.287 +- 0.010** | **0.218 +- 0.009** | **0.874 +- 0.010** | 57 s |
| LSTM-only | 0.314 +- 0.016 | 0.236 +- 0.012 | 0.860 +- 0.013 | 39 s |
| Hybrid ConvLSTM | 0.293 +- 0.011 | 0.221 +- 0.009 | 0.868 +- 0.011 | 157 s |
| *Persistence* | *0.331* | *0.242* | *0.860* | - |
| *Climatology* | *0.628* | *0.505* | *n/a* | - |

## Verdict, using the decision rule from PLAN.md

* **Hybrid vs LSTM-only: the hybrid is clearly better.** It won in all 5 seeds, and the mean gap (0.021 degC RMSE, about 7%) is more than three times the seed-to-seed spread of the paired differences (0.0065). It also wins in winter, spring and autumn; in summer the two are about level.
* **Hybrid vs CNN-only: the hybrid is NOT better.** The CNN was ahead on average (RMSE 0.287 vs 0.293, MAE 0.218 vs 0.221) and the hybrid won in only **1 of 5 seeds**. The gap (0.006 degC) is smaller than the seed spread (0.009), so the honest wording is **"comparable, with the CNN nominally ahead"**. The hybrid also took about 2.8x longer to train (157 s vs 57 s).
* **Versus persistence ("tomorrow = today"):** the hybrid is 11% better in RMSE (0.293 vs 0.331), the CNN 13% better, LSTM-only 5% better.
* **By season** (RMSE, hybrid vs CNN): level in winter (0.190 vs 0.192) and spring (0.274 vs 0.275); the hybrid is worse in summer (0.407 vs 0.392) and slightly worse in autumn (0.246 vs 0.240). Summer is the hardest season for every model.
* **By horizon:** the two are tied at 1-2 days; from day 3 the CNN is slightly better at every horizon. I had suggested earlier that the hybrid's edge might show up at longer horizons; in this experiment it did not.

## All three runs side by side (mean RMSE, degC)

| | Run 1: 2-yr block, summer test, 3 seeds | Run 2: 3-yr block, winter-spring test, 3 seeds | Run 3: 5-yr train, full-year test, 5 seeds |
|---|---|---|---|
| CNN-only | 0.505 | 0.219 | **0.287** |
| LSTM-only | 0.428 | 0.240 | 0.314 |
| Hybrid ConvLSTM | 0.598 | **0.215** | 0.293 |
| Persistence | 0.327 | 0.242 | 0.331 |
| Hybrid vs CNN-only | hybrid worse (within noise) | hybrid slightly ahead (within noise) | CNN slightly ahead (within noise) |
| Hybrid vs LSTM-only | hybrid worse | hybrid ahead (not decisive) | **hybrid clearly ahead** |

## What can and cannot be claimed

* Supported: with enough training data (here 5 years) and a full-year test, the **hybrid ConvLSTM is clearly better than a time-only LSTM** (the same size) and **clearly better than persistence**.
* Supported: the hybrid and a space-only CNN of the same size perform about the same on this sample; in none of the three runs was the hybrid reliably better than the CNN.
* **Not supported: that the hybrid outperforms the CNN-only model.** This benchmark does not show it.
* A possible, untested reason: on a 32 x 40 grid with a 7-day window, a stack of convolutions over the 7 frames already captures most of what is predictable, and recurrence adds little. Whether the hybrid pulls ahead on the full-size grid and full training data is not something this benchmark can say.

## Limitations
* Small controlled sample: one 16 x 20 degree open-ocean region, 0.5 degree grid, 5 training years, one hyper-parameter setting per model (none tuned), batch size 8 for all (the project uses 2).
* One test year; seasons are covered once each (autumn is split across the start and end of the year).
* 5 seeds is better than 3 but still limited; the per-season paired differences are indicative only.
* The CNN-only, LSTM-only and hybrid models were sized to the same number of parameters, which forces LSTM-only to be very narrow (7-unit state).
* The project's anomaly-detection / risk logic was not run on these forecasts (it needs the full processed data store; see the first run's summary).
