"""Temporary, deterministic, Pacific-wide SST generator, a stand-in for the real Pacific dataset.

THESE VALUES ARE GENERATED. They are not measurements and must never be labelled as NOAA, Copernicus or any other observational source. The field is built
from smooth analytic structure (zonal temperature profile, warm pool, cold tongue, boundary-current and upwelling features, seasonal cycle) plus smooth
spatial modes whose amplitudes evolve as sums of slow sinusoids, and a few persistent warm/cold anomaly features anchored to the end of the record. Every
day is a pure function of (configuration, date): the same configuration always gives bit-identical output, any date can be requested directly, and
adjacent days differ by small, smoothly varying amounts. Nothing is drawn independently per grid cell.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
import xarray as xr

from .base import DateNotAvailable, EnvironmentalDataProvider, ProviderMetadata
from .pacific_config import PacificDomainConfig
from .pacific_mask import build_ocean_mask

GENERATOR_VERSION = "1.0"
VARIABLES = {
    "sst": {"units": "degree_C", "long_name": "generated sea surface temperature (NOT an observation)"},
    "climatology": {"units": "degree_C", "long_name": "generated daily SST climatology (NOT an observation)"},
    "anomaly": {"units": "degree_C", "long_name": "generated SST anomaly = sst - climatology (NOT an observation)"},
}
MAX_REQUEST_BYTES = 1_500_000_000
_TWO_PI = 2.0 * np.pi
_YEAR = 365.25

# Persistent anomaly "forcing features": (name, lat, lon_east, sigma_lon_deg, sigma_lat_deg, amplitude_degC, onset_days_before_end, ramp_days, duration_days or None)
# They are smooth Gaussian patches with a smooth temporal envelope, anchored to the END of the record so the latest timestamp contains active anomalies.
# Whether any of them becomes a marine heatwave is decided later by the project's own detector, not here.
ANOMALY_FEATURES = [
    ("north_pacific_blob", 46.0, 215.0, 14.0, 7.0, 2.8, 70, 25, None),
    ("california_current", 34.0, 237.0, 5.0, 5.0, 2.6, 16, 7, None),
    ("hawaii_region", 21.0, 203.0, 7.0, 5.0, 2.2, 24, 9, None),
    ("tasman_sea", -40.0, 160.0, 9.0, 5.0, 3.0, 48, 16, None),
    ("coral_sea", -18.0, 153.0, 7.0, 5.0, 2.0, 20, 8, None),
    ("kuroshio_extension", 36.0, 158.0, 10.0, 5.0, 2.4, 33, 11, None),
    ("peru_ecuador_coast", -8.0, 278.0, 9.0, 5.0, 2.5, 27, 10, None),
    ("philippine_sea", 14.0, 135.0, 8.0, 6.0, 1.8, 13, 6, None),
    ("south_pacific_decayed", -30.0, 220.0, 15.0, 8.0, 2.0, 150, 20, 60),
    ("southeast_pacific_cold_patch", -45.0, 240.0, 12.0, 6.0, -1.8, 52, 15, None),
]


def _smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


class TemporaryPacificProvider(EnvironmentalDataProvider):
    def __init__(self, config: PacificDomainConfig):
        if config.provider != "temporary_pacific":
            raise ValueError(f"config.provider is {config.provider!r}, expected 'temporary_pacific'")
        self.config = config
        c = config
        n_lat = int(round((c.lat_max - c.lat_min) / c.resolution_deg))
        n_lon = int(round((c.lon_max - c.lon_min) / c.resolution_deg))
        self._lat = np.round(c.lat_min + c.resolution_deg * (np.arange(n_lat) + 0.5), 6)
        self._lon = np.round(c.lon_min + c.resolution_deg * (np.arange(n_lon) + 0.5), 6)
        self._ocean = build_ocean_mask(self._lat, self._lon, c.mask_source)
        self._LON, self._LAT = [a.astype("float32") for a in np.meshgrid(self._lon, self._lat)]
        self._dates = pd.date_range(pd.Timestamp(c.start_date).normalize(), pd.Timestamp(c.end_date).normalize(), freq="1D")
        self._rng = np.random.default_rng(c.seed)
        self._build_static_fields()
        self._clim_cache: dict[int, np.ndarray] = {}

    # ------------------------------------------------------------------------------------------------------------------ static structure
    def _pattern(self, n_waves, lon_wl, lat_wl):
        """Smooth spatial pattern: a sum of plane waves with long wavelengths, normalised to unit variance over ocean."""
        r, LON, LAT = self._rng, self._LON, self._LAT
        out = np.zeros(LON.shape, dtype="float64")
        for _ in range(n_waves):
            ang = r.uniform(0, _TWO_PI)
            kx = np.cos(ang) * _TWO_PI / r.uniform(*lon_wl)
            ky = np.sin(ang) * _TWO_PI / r.uniform(*lat_wl)
            out += np.cos(kx * LON + ky * LAT + r.uniform(0, _TWO_PI))
        sd = out[self._ocean].std() if self._ocean.any() else 1.0
        return (out / sd).astype("float32")

    def _build_static_fields(self):
        LON, LAT = self._LON.astype("float64"), self._LAT.astype("float64")
        g = lambda lon0, lat0, sx, sy: np.exp(-(((LON - lon0) / sx) ** 2 + ((LAT - lat0) / sy) ** 2))  # noqa: E731
        base = 30.5 * np.cos(np.deg2rad(LAT)) ** 2 - 2.0                      # warm tropics, cold high latitudes
        base += 1.8 * g(150, 0, 32, 14)                                         # western Pacific warm pool
        base -= 2.2 * g(245, 0, 40, 5.5)                                        # eastern equatorial cold tongue
        base -= 2.5 * g(284, -22, 9, 16)                                        # Humboldt / Peru-Chile upwelling
        base -= 1.8 * g(238, 35, 7, 9)                                          # California Current
        base += 1.2 * g(140, 32, 12, 7)                                         # Kuroshio
        base -= 2.0 * g(150, 45, 10, 5)                                         # Oyashio
        self._eddies = 0.5 * self._pattern(10, (8, 25), (6, 14))               # static meso-scale structure
        self._clim_base = (base + self._eddies).astype("float32")
        amp = 0.3 + 4.8 * (np.minimum(np.abs(LAT), 65) / 60.0) ** 1.5
        w = np.tanh(LAT / 6.0)
        self._seasonal_amp, self._hemi_w = amp.astype("float32"), w.astype("float32")

        r = self._rng
        # slowly evolving large-scale anomaly modes: coefficient_k(t) = sum_j sqrt(2/J) sin(2 pi t / P_kj + phi_kj)
        self._slow_patterns = np.stack([self._pattern(6, (20, 70), (12, 35)) for _ in range(8)])
        self._slow_periods = r.choice([45, 70, 100, 150, 210, 300, 420, 600], size=(8, 3)).astype("float64") * r.uniform(0.9, 1.1, size=(8, 3))
        self._slow_phases = r.uniform(0, _TWO_PI, size=(8, 3))
        self._fast_patterns = np.stack([self._pattern(5, (6, 18), (5, 12)) for _ in range(6)])
        self._fast_periods = r.uniform(4.0, 14.0, size=(6, 2))
        self._fast_phases = r.uniform(0, _TWO_PI, size=(6, 2))
        enso = g(235, 0, 45, 9) - 0.45 * g(145, 3, 30, 14)
        self._enso = enso.astype("float32")
        self._features = []
        for name, la, lo, sx, sy, a, onset, ramp, dur in ANOMALY_FEATURES:
            self._features.append((name, np.exp(-(((LON - lo) / sx) ** 2 + ((LAT - la) / sy) ** 2)).astype("float32"), a, onset, ramp, dur))

    # ------------------------------------------------------------------------------------------------------------------ fields
    def climatology_field(self, doy: int) -> np.ndarray:
        """(n_lat, n_lon) float32 climatological SST for a day of year; land is NaN."""
        doy = int(min(doy, 365))  # day 366 shares day 365 so the climatology is a function of a 365-day year
        if doy not in self._clim_cache:
            seas = self._seasonal_amp * ((1 + self._hemi_w) / 2 * np.cos(_TWO_PI * (doy - 235) / _YEAR) + (1 - self._hemi_w) / 2 * np.cos(_TWO_PI * (doy - 50) / _YEAR))
            self._clim_cache[doy] = np.where(self._ocean, np.maximum(self._clim_base + seas, -1.8), np.nan).astype("float32")
        return self._clim_cache[doy]

    def anomaly_field(self, date) -> np.ndarray:
        """(n_lat, n_lon) float32 generated SST anomaly for a date; land is NaN."""
        day = pd.Timestamp(date).normalize()
        t = float((day - self._dates[0]).days)
        c_slow = np.sqrt(2.0 / 3.0) * np.sin(_TWO_PI * t / self._slow_periods + self._slow_phases).sum(axis=1)
        c_fast = np.sqrt(2.0 / 2.0) * np.sin(_TWO_PI * t / self._fast_periods + self._fast_phases).sum(axis=1)
        a = 0.22 * np.tensordot(c_slow, self._slow_patterns, axes=1) + 0.12 * np.tensordot(c_fast, self._fast_patterns, axes=1)
        enso_idx = 0.9 * np.sin(_TWO_PI * t / (3.6 * _YEAR) + 0.7) + 0.4 * np.sin(_TWO_PI * t / (1.7 * _YEAR) + 2.1)
        a = a + enso_idx * self._enso
        days_to_end = float((day - self._dates[-1]).days)  # <= 0
        for _, shape, amp, onset, ramp, dur in self._features:
            rel = days_to_end + onset                       # days since the feature switched on
            env = float(_smoothstep(rel / ramp)) * (1.0 + 0.08 * np.sin(rel / 5.0))
            if dur is not None:
                env *= float(_smoothstep((dur + 12.0 - rel) / 12.0))
            if env > 0:
                a = a + amp * env * shape
        return np.where(self._ocean, a, np.nan).astype("float32")

    def sst_field(self, date) -> np.ndarray:
        day = pd.Timestamp(date).normalize()
        sst = self.climatology_field(day.dayofyear) + self.anomaly_field(day)
        return np.where(self._ocean, np.maximum(sst, -1.8), np.nan).astype("float32")

    # ------------------------------------------------------------------------------------------------------------------ provider interface
    def grid(self):
        return self._lat.copy(), self._lon.copy()

    def ocean_mask(self):
        return self._ocean.copy()

    def available_dates(self):
        return self._dates

    def metadata(self) -> ProviderMetadata:
        c = self.config
        h = c.resolution_deg / 2
        return ProviderMetadata(
            provider_id="temporary_pacific_generated",
            provider_type="generated_temporary",
            is_observational=False,
            description="Deterministic generated Pacific SST used as a development stand-in until the real Pacific dataset is connected. Not an observation.",
            dataset_type="sea_surface_temperature (generated)",
            variables=VARIABLES, units="degree_C",
            extent={"lat_min": float(self._lat[0] - h), "lat_max": float(self._lat[-1] + h), "lon_min": float(self._lon[0] - h), "lon_max": float(self._lon[-1] + h)},
            coordinate_system="geographic lat/lon degrees (WGS84), cell centres",
            lon_convention="east longitude 0..360 (contiguous across the antimeridian)",
            resolution_deg=c.resolution_deg, temporal_resolution=c.temporal_resolution,
            temporal_coverage={"start": str(self._dates[0].date()), "end": str(self._dates[-1].date()), "n_timestamps": int(len(self._dates))},
            latest_timestamp=str(self._dates[-1].date()),
            grid_shape=(len(self._lat), len(self._lon)), total_cells=int(self._ocean.size), valid_cells=int(self._ocean.sum()),
            mask_source=c.mask_source, seed=c.seed, generator_version=GENERATOR_VERSION,
            notes=["Generated data: do not attribute to any external source.",
                   "Ocean mask is a coarse polygon approximation; islands smaller than about one degree are omitted."],
        )

    def get_dataset(self, start=None, end=None, variables=("sst",), lon_convention: str = "360") -> xr.Dataset:
        unknown = [v for v in variables if v not in VARIABLES]
        if unknown:
            raise ValueError(f"unknown variables {unknown}; available: {sorted(VARIABLES)}")
        if lon_convention not in ("360", "180"):
            raise ValueError("lon_convention must be '360' or '180'")
        first, last = self._dates[0], self._dates[-1]
        if start is None and end is None:
            s = e = last                       # default: the latest available day only
        else:
            s = first if start is None else pd.Timestamp(start).normalize()
            e = last if end is None else pd.Timestamp(end).normalize()
        if s > e:
            raise ValueError("start must not be after end")
        if s < first or e > last:
            raise DateNotAvailable(f"requested {s.date()}..{e.date()} is outside the available coverage {first.date()}..{last.date()}")
        times = pd.date_range(s, e, freq="1D")
        nbytes = len(times) * self._ocean.size * 4 * len(variables)
        if nbytes > MAX_REQUEST_BYTES:
            raise ValueError(f"request would allocate about {nbytes / 1e9:.1f} GB; request a shorter date range")
        out = {v: np.empty((len(times),) + self._ocean.shape, dtype="float32") for v in variables}
        for i, day in enumerate(times):
            clim, anom = self.climatology_field(day.dayofyear), self.anomaly_field(day)
            fields = {"climatology": clim, "anomaly": anom, "sst": np.where(self._ocean, np.maximum(clim + anom, -1.8), np.nan).astype("float32")}
            for v in variables:
                out[v][i] = fields[v]
        ds = xr.Dataset({v: (("time", "lat", "lon"), out[v], dict(VARIABLES[v])) for v in variables},
                        coords={"time": times, "lat": ("lat", self._lat, {"units": "degrees_north"}), "lon": ("lon", self._lon, {"units": "degrees_east"})})
        ds.attrs.update(provider="temporary_pacific_generated", provider_type="generated_temporary", is_observational=0,
                        source="GENERATED development data, not an observation", lon_convention="east longitude 0..360", generator_version=GENERATOR_VERSION)
        if lon_convention == "180":
            ds = ds.assign_coords(lon=((ds.lon + 180) % 360) - 180).sortby("lon")
            ds.attrs["lon_convention"] = "-180..180 (axis has a gap: the domain does not include the Atlantic/Indian side)"
        return ds


def build_from_cfg(cfg) -> TemporaryPacificProvider:
    return TemporaryPacificProvider(PacificDomainConfig.from_cfg(cfg))


def profile(provider: TemporaryPacificProvider, n_days: int = 30) -> dict:
    """Approximate generation time and peak memory for the default configuration."""
    import tracemalloc

    tracemalloc.start()
    t0 = time.perf_counter()
    end = provider.latest_timestamp()
    ds = provider.get_dataset(end - pd.Timedelta(days=n_days - 1), end, ("sst",))
    dt = time.perf_counter() - t0
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    return {"days": n_days, "seconds": round(dt, 3), "seconds_per_day": round(dt / n_days, 4), "peak_mb": round(peak / 1e6, 1),
            "array_mb": round(ds["sst"].nbytes / 1e6, 1), "cells": provider.metadata().total_cells, "valid_cells": provider.metadata().valid_cells}
