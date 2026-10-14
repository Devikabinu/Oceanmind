"""OceanMind preprocessing: raw Zarr/Parquet -> model-ready datasets (ConvLSTM forecasting, autoencoder anomaly detection)."""
from .config import load_config
from .inference import build_latest_window
from .pipeline import build

__all__ = ["load_config", "build", "build_latest_window"]
