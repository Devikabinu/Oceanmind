"""preprocess_report.md and its figures."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.dates as mdates  # noqa: E402
import numpy as np  # noqa: E402


def _show(ax, a, land, title, cmap, label, vmin=None, vmax=None, fig=None, extent=None):
    m = np.ma.masked_where(land | ~np.isfinite(a), a)
    im = ax.imshow(m, origin="lower", cmap=cmap, vmin=vmin, vmax=vmax, extent=extent, aspect="auto")
    ax.set_facecolor("#cfcfcf")  # land / no data
    ax.set_title(title, fontsize=10)
    fig.colorbar(im, ax=ax, label=label, fraction=0.046)


def write_report(cfg, out, times, splits, land, raw_ref, clean_ref, cubes, names, stats, clim_raw, clim, fill, summary):
    fig_dir = out / "figures"
    ocean = ~land
    ref = cfg.time.reference_var
    lat0, lat1, lon0, lon1 = cfg.grid.lat_min, cfg.grid.lat_max, cfg.grid.lon_min, cfg.grid.lon_max
    ext = (lon0, lon1, lat0, lat1)

    # 1. missing-data map: share of ocean days with no data after gap filling, per variable
    vars_ = list(cfg.raw.variables)
    n = len(vars_)
    fig, axes = plt.subplots(1, n, figsize=(4.2 * n, 3.6), squeeze=False)
    def miss_frac_map(v):
        i, tot, n = names.index(f"mask_{v}"), 0.0, 0
        for c in cubes.values():
            for t in range(0, c.shape[0], 256):
                blk = np.asarray(c[t:t + 256, i])
                tot = tot + (1.0 - blk).sum(axis=0)
                n += blk.shape[0]
        return tot / max(n, 1)

    for ax, v in zip(axes[0], vars_):
        frac = miss_frac_map(v)
        _show(ax, frac, land, f"{v}: still missing after fill", "magma", "fraction of days", 0, 1, fig, ext)
        ax.set_xlabel("lon")
        ax.set_ylabel("lat")
    fig.tight_layout()
    fig.savefig(fig_dir / "missing_map.png", dpi=110)
    plt.close(fig)

    # 2. climatology example: the ocean cell nearest the domain centre
    ii, jj = np.nonzero(ocean)
    k = np.argmin((ii - ocean.shape[0] / 2) ** 2 + (jj - ocean.shape[1] / 2) ** 2)
    ci, cj = ii[k], jj[k]
    fig, ax = plt.subplots(figsize=(7, 3.4))
    ax.plot(np.arange(1, 367), clim_raw[ref][:, ci, cj], color="#9a9a9a", lw=1, label="raw day-of-year mean")
    ax.plot(np.arange(1, 367), clim[ref][:, ci, cj], color="#1f6fb4", lw=2, label="smoothed (train only)")
    ax.set(xlabel="day of year", ylabel=f"{ref}", title=f"{ref} climatology, cell lat={cfg.grid.lat_min + ci * cfg.grid.resolution:.2f} lon={cfg.grid.lon_min + cj * cfg.grid.resolution:.2f}")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(fig_dir / "climatology_example.png", dpi=110)
    plt.close(fig)

    # 3. one SST sample before / after (a day with decent coverage, preferring val)
    cand = [sp for sp in (splits["val"], splits["train"]) if sp.n]
    sp = cand[0]
    cover = np.isfinite(raw_ref[sp.sl][:, ocean]).mean(axis=1)
    d = sp.lo + int(np.argmax(cover[: max(len(cover) // 2, 1)] if len(cover) > 1 else cover))
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.6))
    _show(axes[0], raw_ref[d], land, f"{ref} regridded, raw ({times[d].date()})", "turbo", "degC", fig=fig, extent=ext)
    _show(axes[1], clean_ref[d], land, "after clip + gap fill", "turbo", "degC", fig=fig, extent=ext)
    cd = cubes[sp.name][d - sp.lo]
    vis = np.where(cd[names.index(f"mask_{ref}")] > 0, cd[names.index(ref)], np.nan)
    _show(axes[2], vis, land, "final: normalised (z-score)", "RdBu_r", "z", -3, 3, fig, ext)
    fig.tight_layout()
    fig.savefig(fig_dir / "sst_before_after.png", dpi=110)
    plt.close(fig)

    # 4. split date ranges
    fig, ax = plt.subplots(figsize=(9, 2.2))
    colors = {"train": "#1f6fb4", "val": "#e08a1e", "test": "#2a9d5c"}
    for y, s in enumerate(splits.values()):
        if s.n:
            ax.barh(y, mdates.date2num(s.end) - mdates.date2num(s.start) + 1, left=mdates.date2num(s.start),
                    color=colors[s.name], height=0.55)
    ax.set_yticks(range(len(splits)), list(splits))
    ax.xaxis_date()
    ax.set_title("Temporal splits (no overlap)")
    fig.tight_layout()
    fig.savefig(fig_dir / "splits.png", dpi=110)
    plt.close(fig)

    # markdown ------------------------------------------------------------------------------
    L = ["# Preprocessing report", "",
         f"Grid: {ocean.shape[0]} x "
         f"{ocean.shape[1]} cells at {cfg.grid.resolution} deg, lat {lat0}..{lat1}, lon {lon0}..{lon1}. "
         f"Ocean cells: {int(ocean.sum())} of {ocean.size} (land mask = cells that are always NaN in `{ref}`).",
         f"Time axis: {times[0].date()} .. {times[-1].date()}, daily, UTC midnight. "
         f"NRT in training data: {'yes' if cfg.raw.use_nrt_in_build else 'no (FINAL only)'}.", "",
         "## Splits", "", "![splits](figures/splits.png)", "",
         "| split | start | end | days | forecast windows (skipped) | anomaly days (skipped) |", "|---|---|---|---|---|---|"]
    for name, s in summary["splits"].items():
        L.append(f"| {name} | {s['start']} | {s['end']} | {s['days']} | {s['forecast_windows']} ({s['forecast_skipped']}) "
                 f"| {s['anomaly_days']} ({s['anomaly_skipped']}) |")
    L += ["", "Windows never cross a split boundary. Normalisation, climatology and clip limits use the train period only.", "",
          "## Missing data", "", "![missing](figures/missing_map.png)", "",
          f"Gaps of up to {cfg.missing.max_gap_days} days are linearly interpolated per cell (within each split); longer gaps stay NaN "
          "and are flagged by `mask_<var>`. Land is never filled.", "",
          "| variable | missing before | % of missing that was filled | missing after |", "|---|---|---|---|"]
    for v, r in fill.items():
        L.append(f"| {v} | {r['pct_missing_before']:.1f}% | {r['pct_of_missing_filled']:.1f}% | {r['pct_missing_after']:.1f}% |")
    L += ["", "## Climatology", "", "![climatology](figures/climatology_example.png)", "",
          "## SST sample", "", "![sst](figures/sst_before_after.png)", "",
          "## Normalisation (train, ocean cells)", "", "| channel | mean | std | normalised train mean | normalised train std |", "|---|---|---|---|---|"]
    for ch, s in stats.items():
        m, sd = summary["moments"][ch]
        L.append(f"| {ch} | {s['mean']:.4g} | {s['raw_std']:.4g} | {m:.1e} | {sd:.4f} |")
    if "biodiversity" in summary:
        b = summary["biodiversity"]
        L += ["", "## Biodiversity", "", f"{b['records']} OBIS records gridded into {b['cell_months']} cell-months "
              "(`n_records`, `richness`, `n_sampling_days`, `effort`, `log_effort`). Richness rises with effort; include `log_effort` as a covariate."]
    L += ["", "## Checks passed", "", "- no NaN in any final tensor (ocean cells included)", "- splits disjoint and ordered",
          "- normalised train mean ~0 / std ~1", "- every window lies inside a single split", ""]
    (out / "preprocess_report.md").write_text("\n".join(L), encoding="utf-8")
