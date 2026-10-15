# Preprocessing report

Grid: 120 x 160 cells at 0.25 deg, lat 20.125..49.875, lon -159.875..-120.125. Ocean cells: 18333 of 19200 (land mask = cells that are always NaN in `sst`).
Time axis: 2012-01-01 .. 2026-09-27, daily, UTC midnight. NRT in training data: no (FINAL only).

## Splits

![splits](figures/splits.png)

| split | start | end | days | forecast windows (skipped) | anomaly days (skipped) |
|---|---|---|---|---|---|
| train | 2012-01-01 | 2023-12-31 | 4383 | 4363 (7) | 4374 (9) |
| val | 2024-01-01 | 2024-12-31 | 366 | 353 (0) | 366 (0) |
| test | 2025-01-01 | 2026-09-27 | 635 | 622 (0) | 635 (0) |

Windows never cross a split boundary. Normalisation, climatology and clip limits use the train period only.

## Missing data

![missing](figures/missing_map.png)

Gaps of up to 3 days are linearly interpolated per cell (within each split); longer gaps stay NaN and are flagged by `mask_<var>`. Land is never filled.

| variable | missing before | % of missing that was filled | missing after |
|---|---|---|---|
| sst | 0.4% | 52.6% | 0.2% |

## Climatology

![climatology](figures/climatology_example.png)

## SST sample

![sst](figures/sst_before_after.png)

## Normalisation (train, ocean cells)

| channel | mean | std | normalised train mean | normalised train std |
|---|---|---|---|---|
| sst | 17.88 | 5.282 | -7.8e-09 | 1.0000 |
| sst_anom | 0.0003957 | 0.9208 | 2.1e-09 | 1.0000 |
| sst_grad | 0.7413 | 0.5325 | 3.1e-08 | 1.0000 |

## Checks passed

- no NaN in any final tensor (ocean cells included)
- splits disjoint and ordered
- normalised train mean ~0 / std ~1
- every window lies inside a single split
