"""python -m oceanmind_environment [info|sync] [--config config.yaml]
  info  print the provider metadata (and a quick profile for the generated stand-in provider)
  sync  download and validate NOAA OISST for the configured domain and refresh the processed store (cached, resumable)"""
import argparse
import json
import logging

from oceanmind_preprocess.config import load_config

ap = argparse.ArgumentParser(prog="oceanmind_environment")
ap.add_argument("command", nargs="?", default="info", choices=["info", "sync"])
ap.add_argument("--config", default="config.yaml")
ap.add_argument("--days", type=int, default=30)
args = ap.parse_args()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
if args.command == "sync":
    from .noaa_oisst import sync
    from oceanmind_preprocess.config import Cfg, _read_yaml
    from pathlib import Path
    path = Path(args.config).resolve()
    raw = _read_yaml(path)
    raw["config_path"] = str(path)
    print(json.dumps(sync(raw), indent=2))
else:
    cfg = load_config(args.config)
    from .factory import build_provider
    provider = build_provider(cfg)
    print(json.dumps(provider.metadata().to_dict(), indent=2, default=str))
