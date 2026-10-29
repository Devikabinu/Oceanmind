# Model benchmark: does the hybrid ConvLSTM beat CNN-only and LSTM-only?

**Short answer: no, not in this experiment.** Trained fresh on the same small sample under identical conditions, the hybrid ConvLSTM was the *worst*
of the three learned models on RMSE, MAE and ACC, and none of the three beat simple persistence ("tomorrow = today"). This does **not** show that the
hybrid is a bad architecture; it shows that, on about 18 months of training data and a summer-only test window, it did not demonstrate an advantage.
Read the limitations before drawing any conclusion about full-data training.

All numbers below are real outputs of `scripts/benchmark/` (model output / derived metrics, evaluated on the held-out test block).
Full numbers: `results.json`; tables: `results_table.md`; figures: `error_vs_horizon.png`, `sample_maps.png`, `sample_map_<model>.png`.

## What was run

| | |
|---|---|
| Data | NOAA OISST v2.1 daily SST, observed (not model-generated) |
| Region / grid | 28-44N, 150-130W (open ocean, no land), averaged to 0.5 deg: 32 x 40 = 1,280 cells |
| Benchmark block | **2024-10-13 to 2026-10-12** (730 continuous days = the most recent 2 years of FINAL data) |
| Split (chronological, no shuffling) | train 2024-10-13..2026-04-13 (548 d, 75.1%) / validation 2026-04-14..2026-07-10 (88 d, 12.1%) / **test 2026-07-11..2026-10-12 (94 d, 12.9%)** |
| Windows | 535 train / 75 validation / 81 test (7 input days, forecast 1-7 days ahead; identical for all models) |
| Inputs | the project's 6 channels (SST, anomaly, gradient, day-of-year sin/cos, mask), z-scored with **train-block statistics only** |
| Climatology / anomaly | day-of-year climatology from 2012-01-01 up to the end of the train block (everything before validation), via the project's own code. The older history is used **only** for the climatology, never as training windows |
| Seeds | 3 per model (0, 1, 2); mean +- sample standard deviation |
| Training (identical) | AdamW, lr 0.001 constant, weight decay 1e-4, batch 8, grad-clip 1.0, masked MSE, max 30 epochs, early stopping (patience 5) on validation loss; best-validation weights scored on the test block |
| Device | Apple M2 GPU (MPS); total training time of all 9 runs about 5 minutes |

Models (all predict the change from the last observed SST map, as the project's ConvLSTM does):

| Model | What it can "see" | Parameters |
|---|---|---|
| CNN-only | space, but no memory (7 frames stacked as 42 channels, 4 conv layers) | 127,913 |
| LSTM-only | time, but no spatial structure (frame flattened, 7-unit LSTM state) | 125,895 |
| Hybrid ConvLSTM | both: the project's existing `OceanConvLSTM`, imported unchanged, trained from scratch here | 127,239 |

The three are within about 1% of each other in size. The old checkpoint was **not** used.

## Results (test block, mean over horizons 1-7 days; mean +- sd over 3 seeds)

| Model | RMSE (degC) | MAE (degC) | ACC | Train time |
|---|---|---|---|---|
| CNN-only | 0.505 +- 0.131 | 0.417 +- 0.131 | 0.60 +- 0.22 | 19 s |
| **LSTM-only** | **0.428 +- 0.078** | **0.348 +- 0.094** | **0.75 +- 0.13** | 21 s |
| Hybrid ConvLSTM | 0.598 +- 0.053 | 0.515 +- 0.051 | 0.43 +- 0.08 | 61 s |
| *Persistence* | *0.327* | *0.235* | *0.89* | - |
| *Climatology* | *0.696* | *0.590* | *n/a* | - |

(ACC = anomaly correlation against the train-period climatology, pooled over test windows and cells; it is undefined for climatology because its anomaly is zero.)

At a 1-day horizon all three are close to persistence (RMSE 0.15-0.17 vs 0.13 degC). The gap opens quickly with horizon: at 7 days the RMSE is
0.66 (LSTM-only), 0.78 (CNN-only), 0.96 (hybrid) against 0.47 for persistence.

## Which model won, and by how much

* **The hybrid did not win.** Mean RMSE: LSTM-only is 0.17 degC (28%) better than the hybrid and CNN-only is 0.09 degC (16%) better.
* **Is the gap bigger than seed-to-seed variation?**
  * Hybrid vs LSTM-only: the gap (0.17) is about 2x the seed standard deviation of either model, and LSTM-only was better than the hybrid in **all three** seeds. With only three seeds this is suggestive, not conclusive.
  * Hybrid vs CNN-only: the gap (0.09) is **smaller** than CNN-only's own seed variation (sd 0.13), so this difference is **within noise**. The CNN beat the hybrid in two seeds and essentially tied in the third (0.654 vs 0.659).
  * CNN-only vs LSTM-only: also within noise.
* **The hybrid was the most consistent** across seeds (smallest sd), but consistently worse. It also took about 3x longer to train.
* **No learned model beat persistence at any horizon** (including 1 day). All three beat climatology at short horizons; from day 5-6 the hybrid and CNN-only are worse than climatology on RMSE.

## Why this probably happened (best explanation, not proven)

The pattern in the data points to **a seasonal mismatch plus very little training data**, not to the CNN or LSTM being cleverer than the ConvLSTM:

1. On the **validation** block (April-July) the CNN-only and hybrid models beat persistence in every seed (best validation loss about 0.009 vs 0.013 for persistence, in normalised units) and LSTM-only did in two of three seeds. On the **test** block (July-October) none did. The models learned something that worked in spring and failed in late summer.
2. The errors are mostly a **warm bias that grows with horizon** (mean forecast minus truth at 7 days: hybrid +0.80, CNN +0.56, LSTM-only +0.32 degC, persistence -0.10). During the test block the region's mean SST peaked at 21.6 degC in late summer and then slowly cooled, while the models kept extending the spring warming trend they had seen. The sample maps show this: every learned model is too warm almost everywhere.
3. The training set contains **only one summer** and the models also receive day-of-year inputs, so a flexible model can memorise "what happens at this time of year" from a single example. The more spatially expressive models (hybrid, CNN) were hurt more than the LSTM-only model, whose 7-number temporal state limits how much it can learn and therefore keeps it closer to persistence. A model with *less* ability to learn looking best is a typical sign of over-fitting small data, not of a better architecture.

I did not run any extra experiment to confirm this (for example removing the day-of-year channels or training on more years); doing so after seeing the results would break the rule against adjusting things after the fact, and it is the natural next step if you want to investigate.

## Limitations (important)

* **Small controlled sample.** 535 training windows from 1.5 years, one region of 1,280 cells, 0.5 degree grid. This is deliberately far smaller than the project's real training (about 12 years, 0.25 degree). Results may **not carry over** to full-data training, where the hybrid may well do better.
* **The test window covers only 94 days (11 July to 12 October), one partial season (summer into early autumn).** Winter/spring behaviour is not tested, and one season's mismatch can dominate the result.
* **Three seeds** give a rough idea of variation only; standard deviations from three values are themselves uncertain.
* **The LSTM-only model is a deliberately narrow model** (7-unit state) because matching the other two models' parameter count forces that: a flattened 7,680-value frame makes the input layer expensive. A larger LSTM would be a different comparison.
* Batch size is 8 (the project uses 2), the same for all models; one hyper-parameter setting per model was run, none tuned, none tuned for the hybrid only.
* The project's own anomaly-detection / risk / alert code was **not** compared. It is built around the full processed data store and fixed baseline settings and cannot be run on an arbitrary forecast array without modifying existing code, which this add-on must not do.

## Data provenance (deviation from the plan)

The project's own downloader (NOAA ERDDAP, FINAL product) was unavailable on the day of the run ("dataset unknown", about 10 minutes of retries). The same NOAA OISST v2.1 product
was read from the NOAA PSL mirror instead, and the window ends at **2026-10-12, the last day NCEI lists as FINAL** (13 October onward is preliminary and was excluded).
Values from the PSL mirror may differ slightly from the ERDDAP FINAL files; this is recorded in `data/data_meta.json` and `results.json`. A re-run with ERDDAP is
possible with `python scripts/benchmark/prepare_data.py --source erddap` once the server is back.

## Reproduce

```bash
scripts/benchmark/.venv/bin/python scripts/benchmark/prepare_data.py --source psl --end 2026-10-12
scripts/benchmark/.venv/bin/python scripts/benchmark/run_benchmark.py --speed-test
scripts/benchmark/.venv/bin/python scripts/benchmark/run_benchmark.py
scripts/benchmark/.venv/bin/python scripts/benchmark/make_report.py
```
