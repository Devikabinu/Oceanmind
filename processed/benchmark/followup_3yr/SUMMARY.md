# Follow-up benchmark: 3 years of data, winter-spring test block

Same code, models and training settings as the first benchmark (`../SUMMARY.md`). Two things were changed on purpose, **decided before running**:
the block is 3 years instead of 2, and it ends on 2026-04-30 so the test block is a different season. All numbers are real outputs
(model output / derived metrics on a held-out test block). Full numbers: `results.json`, `results_table.md`; figures: `error_vs_horizon.png`, `sample_maps.png`.

## Setup

| | |
|---|---|
| Block | **2023-05-01 to 2026-04-30** (1,096 continuous days), same region and 0.5 deg grid as before |
| Train | 2023-05-01..2025-07-30 (822 d, 809 windows) |
| Validation | 2025-07-31..2025-12-09 (131 d, 119 windows) |
| **Test** | **2025-12-10..2026-04-30 (143 d, 129 windows): winter into spring** (the first run's test was July-October) |
| Climatology | 2012-01-01 up to the end of the train block (everything before validation) |
| Source | NOAA OISST v2.1 via the PSL mirror (same as before; the ERDDAP server was down during the first run) |
| Models / seeds / training | unchanged: CNN-only 127,913, LSTM-only 125,895, hybrid 127,239 parameters; 3 seeds; AdamW, batch 8, constant lr, early stopping |

## Results (test block, mean over horizons 1-7 days; mean +- sd over 3 seeds)

| Model | RMSE (degC) | MAE (degC) | ACC | Train time |
|---|---|---|---|---|
| CNN-only | 0.219 +- 0.012 | 0.168 +- 0.009 | 0.931 +- 0.010 | 23 s |
| LSTM-only | 0.240 +- 0.014 | 0.187 +- 0.013 | 0.929 +- 0.000 | 39 s |
| **Hybrid ConvLSTM** | **0.215 +- 0.012** | **0.164 +- 0.009** | **0.935 +- 0.010** | 56 s |
| *Persistence* | *0.242* | *0.189* | *0.930* | - |
| *Climatology* | *0.630* | *0.503* | *n/a* | - |

## What the results say

* **The hybrid had the lowest average error and, unlike in the first run, it beat persistence**: 11% lower RMSE (0.215 vs 0.242) and 13% lower MAE (0.164 vs 0.189). It beat persistence at every horizon from 3 days on; at 1-2 days all models are tied with persistence.
* **But the hybrid's lead over the CNN-only model is tiny and within noise.** The gap is 0.005 degC RMSE, about a third of one seed standard deviation (0.012). The hybrid was ahead of the CNN in each of the three seeds (0.228/0.208/0.208 vs 0.233/0.214/0.211), but only by 0.003-0.006 degC. This is consistent with "slightly better" and also with "equal". The CNN-only model also beat persistence (about 9% lower RMSE).
* **Against LSTM-only the lead is larger but not decisive.** The gap is 0.025 degC (about two seed standard deviations). The hybrid was better in two of three seeds; in seed 0 LSTM-only was better (0.223 vs 0.228). LSTM-only is essentially level with persistence (0.240 vs 0.242).
* **ACC is almost identical for every model and for persistence (0.93)**, so on the pattern measure there is no meaningful winner.
* Everything is far better than climatology (0.63), as expected at 1-7 days.

**Honest one-line verdict:** the hybrid came out best on average and clearly better than persistence and LSTM-only on average, but this experiment cannot show it is better than the CNN-only model; the evidence for that is weak.

## Comparison with the first run

| Mean RMSE (degC) | First run (2 yr, summer test) | Follow-up (3 yr, winter-spring test) |
|---|---|---|
| Hybrid | 0.598 | 0.215 |
| CNN-only | 0.505 | 0.219 |
| LSTM-only | 0.428 | 0.240 |
| Persistence | 0.327 | 0.242 |

**The ranking flipped, and I cannot say why with certainty.** I changed two things at once (more training data and a different test season), so these results cannot separate "more data fixed it" from "this season is easier for these models". Evidence for each: in the first run the models were too warm in summer after learning spring warming from a single summer of data; here the training block holds two summers and two winters, which would reduce that failure. But persistence itself is also easier in this season (RMSE 0.24 vs 0.33), so part of the change is the season.

## Limitations

* Still a small controlled sample: one region, 0.5 degree grid, about 2.2 years of training data, **3 seeds**, test block of 143 days (winter-spring only; the first run covers summer-autumn, so between them the year is covered but not in one experiment).
* Differences of a few thousandths of a degree between hybrid and CNN-only are within seed variation.
* Two experiments were run and both are reported. The first (hybrid worst) was not removed or reinterpreted after this result.
* Early stopping ended the hybrid after about 8 epochs and the CNN after about 10; LSTM-only ran about 19. Results for one hyper-parameter setting per model; none was tuned.
* Not a substitute for full-data evaluation, which the project already has (see the Model Performance page).
