"""Lazy PyTorch datasets over the memory-mapped per-split cubes written by `build`."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch.utils.data import Dataset


class _Base(Dataset):
    def __init__(self, root, split):
        self.root = Path(root)
        self.split = split
        self.meta = json.loads((self.root / "meta.json").read_text())
        self.names = self.meta["channels"]
        self.land_mask = np.load(self.root / "land_mask.npy")
        self._cube = None

    @property
    def cube(self):  # opened lazily so DataLoader workers each get their own memmap
        if self._cube is None:
            self._cube = np.load(self.root / "cubes" / f"{self.split}.npy", mmap_mode="r")
        return self._cube

    def _idx(self, chans):
        missing = [c for c in chans if c not in self.names]
        if missing:
            raise KeyError(f"unknown channels {missing}; available: {self.names}")
        return [self.names.index(c) for c in chans]


class ForecastDataset(_Base):
    """x: (T, C, H, W) normalised inputs; y: (n_horizons, H, W) normalised target SST;
    y_mask: 1 where the target SST was observed/filled; ocean: (H, W) 1 on ocean cells."""

    def __init__(self, root, split, channels=None):
        super().__init__(root, split)
        m = self.meta
        self.index = pd.read_parquet(self.root / "forecast" / f"windows_{split}.parquet")
        self.starts = self.index["start_idx"].to_numpy()
        self.lookback = m["lookback_days"]
        self.horizons = np.asarray(m["horizons"])
        self.channels = list(channels or m["forecast_channels"])
        self.ch = self._idx(self.channels)
        self.t_ch = self._idx([m["target_channel"]])[0]
        self.m_ch = self._idx([f"mask_{m['target_channel']}"])[0]

    def __len__(self):
        return len(self.starts)

    def __getitem__(self, i):
        s = int(self.starts[i])
        x = np.asarray(self.cube[s:s + self.lookback][:, self.ch])
        tgt = s + self.lookback - 1 + self.horizons
        return {
            "x": torch.from_numpy(x),
            "y": torch.from_numpy(np.asarray(self.cube[tgt, self.t_ch])),
            "y_mask": torch.from_numpy(np.asarray(self.cube[tgt, self.m_ch])),
            "ocean": torch.from_numpy((~self.land_mask).astype("float32")),
            "start_date": str(self.index["start_date"].iloc[i].date()),
            "n_nrt_days": int(self.index["n_nrt_days"].iloc[i]),
        }


class AnomalyDataset(_Base):
    """Patches for the autoencoder. x: (days*C, ph, pw) with the mask channels included;
    ocean: (ph, pw). patch_size=None uses the whole grid as one patch."""

    def __init__(self, root, split, channels=None):
        super().__init__(root, split)
        a = self.meta["anomaly"]
        self.index = pd.read_parquet(self.root / "anomaly" / f"index_{split}.parquet")
        self.starts = self.index["start_idx"].to_numpy()
        self.days = a["days"]
        self.channels = list(channels or a["channels"])
        self.ch = self._idx(self.channels)
        H, W = self.land_mask.shape
        ph, pw = a["patch_size"] or (H, W)
        stride = a["stride"] or max(ph, pw)
        ii = list(range(0, H - ph + 1, stride))
        jj = list(range(0, W - pw + 1, stride))
        if ii[-1] != H - ph:
            ii.append(H - ph)
        if jj[-1] != W - pw:
            jj.append(W - pw)
        ocean = ~self.land_mask
        self.patch = (ph, pw)
        self.pos = [(i, j) for i in ii for j in jj if ocean[i:i + ph, j:j + pw].mean() >= a["min_ocean_frac"]]
        self.ocean = ocean

    def __len__(self):
        return len(self.starts) * len(self.pos)

    def __getitem__(self, k):
        d, p = divmod(k, len(self.pos))
        s, (i, j) = int(self.starts[d]), self.pos[p]
        ph, pw = self.patch
        x = np.asarray(self.cube[s:s + self.days, :, i:i + ph, j:j + pw][:, self.ch])
        return {
            "x": torch.from_numpy(x.reshape(-1, ph, pw)),
            "ocean": torch.from_numpy(self.ocean[i:i + ph, j:j + pw].astype("float32")),
            "start_date": str(self.index["start_date"].iloc[d].date()),
            "row": i, "col": j,
        }
