"""Putting a dataset's fields into the number scale the checkpoint was TRAINED with, and bringing its output back to degrees C.

The processed cubes hold z-scored channels (value - mean) / std, computed on the dataset's own training split. A checkpoint only makes sense on the scale it learned: the NE
Pacific weights were trained on cubes normalised with the NE Pacific statistics (SST mean 17.9, std 5.3), while the Pacific cubes are normalised with Pacific statistics
(mean 19.9, std 8.6). Feeding Pacific-scaled inputs straight into those weights would present the network with fields it never saw on that scale. When a checkpoint's
`checkpoint_origin.json` names the statistics it was trained with (`normalization_stats`), every use of the model - evaluation, the exported forecast and the explanation -
converts the dataset's channels to that scale first and converts the output with the same statistics. Without such a declaration the dataset's own statistics are used
(a model trained on this very dataset)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

SCALED = ("sst", "sst_anom", "sst_grad")       # channels with z-score statistics; day-of-year and mask channels are not rescaled


class ModelSpace:
    def __init__(self, root, out_subdir: str = "model", channels=None, target: str = "sst"):
        self.root = Path(root)
        own = json.loads((self.root / "stats.json").read_text())["channels"]
        self.own = own
        self.target = target
        self.trained_with = None
        self.source = "this dataset's own training statistics"
        origin = self.root / out_subdir / "checkpoint_origin.json"
        if origin.exists():
            declared = json.loads(origin.read_text()).get("normalization_stats")
            if declared:
                p = Path(declared)
                p = p if p.is_absolute() else self.root.parent / p
                self.trained_with = json.loads(p.read_text())["channels"]
                self.source = f"the statistics the weights were trained with ({declared})"
        self.names = list(channels) if channels is not None else None

    @property
    def output(self) -> dict:
        """mean/std that turn the model's normalised SST output into degC."""
        return (self.trained_with or self.own)[self.target]

    def convert(self, x: np.ndarray, names=None) -> np.ndarray:
        """x with channels on axis -3 (..., C, H, W), on the dataset's scale -> the checkpoint's scale. A copy; the input is untouched."""
        if self.trained_with is None:
            return x
        names = list(names if names is not None else self.names)
        out = np.array(x, dtype="float32", copy=True)
        for c, n in enumerate(names):
            if n in SCALED and n in self.own and n in self.trained_with:
                a, b = self.own[n], self.trained_with[n]
                out[..., c, :, :] = (x[..., c, :, :] * np.float32(a["std"]) + np.float32(a["mean"]) - np.float32(b["mean"])) / np.float32(b["std"])
        return out

    def to_degC(self, y: np.ndarray) -> np.ndarray:
        o = self.output
        return y * np.float32(o["std"]) + np.float32(o["mean"])
