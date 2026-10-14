"""Strictly temporal train/val/test splits."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

ORDER = ("train", "val", "test")


@dataclass
class Split:
    name: str
    start: pd.Timestamp
    end: pd.Timestamp
    lo: int
    hi: int

    @property
    def n(self):
        return max(self.hi - self.lo, 0)

    @property
    def sl(self):
        return slice(self.lo, self.hi)


def resolve_splits(cfg, times: pd.DatetimeIndex) -> dict:
    out = {}
    for name in ORDER:
        s, e = cfg.splits[name]
        s = times[0] if s is None else pd.Timestamp(s)
        e = times[-1] if e is None else pd.Timestamp(e)
        if s > e:
            raise ValueError(f"split '{name}' start {s.date()} is after end {e.date()}")
        lo, hi = times.searchsorted(s, "left"), times.searchsorted(e, "right")
        out[name] = Split(name, s, e, int(lo), int(hi))
    if out["train"].n == 0:
        raise ValueError("train split contains no dates")
    check_disjoint(out)
    return out


def check_disjoint(splits: dict):
    prev = None
    for name in ORDER:
        sp = splits[name]
        if prev is not None and sp.start <= prev.end:
            raise ValueError(f"split '{sp.name}' ({sp.start.date()}) overlaps or precedes '{prev.name}' (ends {prev.end.date()})")
        prev = sp
    seen = set()
    for sp in splits.values():
        idx = set(range(sp.lo, sp.hi))
        if idx & seen:
            raise ValueError("splits share dates")
        seen |= idx


def print_sizes(splits: dict):
    print("Split sizes (days):")
    for sp in splits.values():
        rng = f"{sp.start.date()} .. {sp.end.date()}" if sp.n else "(empty)"
        print(f"  {sp.name:<5} {sp.n:>6}  {rng}")
