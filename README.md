# oceanmind_preprocess

```bash
pip install numpy pandas xarray zarr scipy pyyaml pyarrow matplotlib torch pytest   # xesmf optional
python -m oceanmind_preprocess build  --config config.yaml
python -m oceanmind_preprocess latest --config config.yaml [--date 2025-06-01] [--out window.npz]
python -m pytest tests
```

## Expected raw layout (edit `paths` / `raw` in config.yaml)
`<raw_dir>/<store>_final.zarr` and optional `<store>_nrt.zarr` per variable (dims time/lat/lon, names auto-detected,
0..360 longitudes converted, a depth axis reduced to the level nearest `depth`), plus `obis/occurrences.parquet`.
Timestamps are treated as UTC and floored to midnight; sub-daily samples are averaged.

## Outputs (`paths.out_dir`)
`land_mask.npy` (True = land), `stats.json` (mean/std + clip limits, train only), `climatology.zarr`,
`cubes/<split>.npy` (T,C,H,W float32, memory-mappable) + `_dates.npy`/`_nrt.npy`, `forecast/windows_<split>.parquet`,
`anomaly/index_<split>.parquet`, `biodiversity/obis_monthly.{parquet,zarr}`, `meta.json`, `preprocess_report.md`.

Datasets: `from oceanmind_preprocess.datasets import ForecastDataset, AnomalyDataset`. Inference:
`from oceanmind_preprocess import build_latest_window`.

Channel conventions: `mask_<var>` = 1 where that variable has data (observed or gap-filled) on an ocean cell, else 0 (land
or long gap); use `land_mask.npy` / the `ocean` item to tell them apart. Land and unfilled cells are 0 after normalisation.

## SST ingestion (NOAA OISST v2.1 via ERDDAP)
```powershell
python download_sst.py check        # verify both endpoints, print latest FINAL / NRT dates
python download_sst.py smoke        # 7-day verified download + preprocessing probe
python download_sst.py historical   # FINAL history from ingest.history_start, 12-month batches, cached/resumable
python download_sst.py nrt          # new FINAL days + refreshed preliminary NRT window; FINAL supersedes NRT
python download_sst.py status
```
Region comes from `grid.*`. Raw subsets are cached in `data/raw/cache/`, composed into `data/raw/sst_final.zarr` /
`sst_nrt.zarr`, with per-date provenance in `data/raw/sst_manifest.parquet`. The NOAA products have genuine missing
days; they are recorded (`gap_days_in_source`) and handled by the normal gap-fill / mask logic.
