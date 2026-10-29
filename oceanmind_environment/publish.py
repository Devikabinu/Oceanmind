"""Versioned publication of a processed dataset.

A refresh never writes into the dataset the application is serving. It builds the new generation (cubes, climatology, anomalies, forecast, marine heatwaves) in a sibling
`<name>.staging` directory, checks it, and then replaces the live directory in one rename: `live -> live.prev`, `staging -> live`. A reader therefore sees either the whole old
generation or the whole new one, never cubes of one day beside a forecast of another. If anything fails before the swap the live directory is untouched; if the swap itself
fails the previous generation is put back. A crash between the two renames is repaired by `recover()` on the next start."""
from __future__ import annotations

import shutil
import time
from pathlib import Path


class PublishError(RuntimeError):
    pass


def staging_dir(live: Path) -> Path:
    return live.with_name(live.name + ".staging")


def previous_dir(live: Path) -> Path:
    return live.with_name(live.name + ".prev")


def recover(live: Path) -> str | None:
    """Repair an interrupted swap: a missing live directory with a previous generation beside it gets that generation back. Returns what was done."""
    live, prev = Path(live), previous_dir(Path(live))
    if not live.exists() and prev.exists():
        prev.rename(live)
        return "restored the previous generation after an interrupted publication"
    return None


def carry_over(live: Path, staging: Path) -> list[str]:
    """Top-level entries the live dataset has and the new build does not produce (side files written by other jobs, e.g. figures or the SST-history cache) are kept."""
    kept = []
    if not live.exists():
        return kept
    for e in live.iterdir():
        if not (staging / e.name).exists():
            (shutil.copytree if e.is_dir() else shutil.copy2)(e, staging / e.name)
            kept.append(e.name)
    return kept


def swap(live: Path, staging: Path, attempts: int = 3, wait_s: float = 5.0) -> Path:
    """Make `staging` the live directory. Returns the previous generation's directory (kept until `finalize`). Raises PublishError, leaving the live directory as it was."""
    live, staging = Path(live), Path(staging)
    prev = previous_dir(live)
    if not staging.exists():
        raise PublishError(f"nothing to publish: {staging} does not exist")
    if prev.exists():
        shutil.rmtree(prev, ignore_errors=True)
    moved = False
    last: Exception | None = None
    for k in range(attempts):
        try:
            if live.exists():
                live.rename(prev)
                moved = True
            staging.rename(live)
            return prev
        except OSError as exc:                                  # on Windows a directory with open files cannot be renamed
            last = exc
            if moved and not live.exists() and prev.exists():
                prev.rename(live)
                moved = False
            if k + 1 < attempts:
                time.sleep(wait_s)
    raise PublishError(f"could not replace {live.name} (its files are in use): {last}")


def finalize(prev: Path) -> None:
    shutil.rmtree(prev, ignore_errors=True)


def rollback(live: Path) -> bool:
    """Put the previous generation back (used when a check after the swap fails)."""
    live, prev = Path(live), previous_dir(Path(live))
    if not prev.exists():
        return False
    broken = live.with_name(live.name + ".broken")
    shutil.rmtree(broken, ignore_errors=True)
    if live.exists():
        live.rename(broken)
    prev.rename(live)
    shutil.rmtree(broken, ignore_errors=True)
    return True
