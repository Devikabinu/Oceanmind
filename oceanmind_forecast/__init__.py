"""Forecast baselines and a reusable evaluation API (shared with the future ConvLSTM)."""
from .baselines import climatology_forecast, persistence_forecast
from .evaluate import (evaluate_baselines, evaluate_predictions, load_split_truth, skill_vs_reference)
from .metrics import calculate_metrics

__all__ = ["persistence_forecast", "climatology_forecast", "calculate_metrics", "evaluate_predictions",
           "evaluate_baselines", "load_split_truth", "skill_vs_reference"]
