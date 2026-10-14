"""NOAA OISST v2.1 downloader (final + near-real-time). Thin wrapper around oceanmind_preprocess.ingest.

    python download_sst.py check
    python download_sst.py smoke [--days 7]
    python download_sst.py historical [--start 2000-01-01 --end 2023-12-31]
    python download_sst.py nrt [--recent-days 14]
    python download_sst.py status
"""
import sys

from oceanmind_preprocess.ingest import main

if __name__ == "__main__":
    sys.exit(main())
