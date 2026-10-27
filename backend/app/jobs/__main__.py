"""CLI: python -m app.jobs <sync-biodiversity|publish-outputs|all> [options]  (run from the backend directory)."""
import argparse
import logging
import sys

from sqlalchemy import select

from app.db.seed import seed_data_sources
from app.db.session import SessionLocal
from app.models.enums import UserRole
from app.models.user import User


def _user_id(db):
    user = db.execute(select(User).where(User.role == UserRole.ADMIN).limit(1)).scalar_one_or_none() or \
        db.execute(select(User).limit(1)).scalar_one_or_none()
    if user is None:
        sys.exit("No users exist yet: register one through the app first (jobs are recorded against a user).")
    return user.id


def main() -> int:
    ap = argparse.ArgumentParser(prog="python -m app.jobs")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync-biodiversity", help="load species catalogue + a sample of real OBIS records")
    s.add_argument("--species", default=None, help="comma-separated scientific names (default: the built-in watch list)")
    s.add_argument("--months", type=int, default=24)
    s.add_argument("--windows", type=int, default=8)
    s.add_argument("--per-window", type=int, default=120)
    s.add_argument("--region", default="ne_pacific", choices=["ne_pacific", "pacific"], help="study area: the original NE Pacific box or the whole Pacific basin")
    s.add_argument("--force", action="store_true", help="add a fresh sample even if the species already has stored records (may duplicate)")
    p = sub.add_parser("publish-outputs", help="write observations/anomalies/forecasts/risk/alerts derived from the ML export")
    p.add_argument("--days", type=int, default=14)
    d = sub.add_parser("publish-dataset-alerts", help="raise alerts from a dataset's precomputed heatwave events and risk areas (e.g. pacific)")
    d.add_argument("--dataset", default="pacific")
    sub.add_parser("sync-climate-indices", help="download the Oceanic Nino Index (NOAA CPC) and the PDO index (NOAA NCEI) used as labelled context in anomaly explanations")
    sub.add_parser("all")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING)
    db = SessionLocal()
    try:
        seed_data_sources(db)
        uid = _user_id(db)
        if args.cmd in ("sync-biodiversity", "all"):
            from app.jobs import sync_biodiversity
            kw = {}
            names = None
            if args.cmd == "sync-biodiversity":
                names = [n.strip() for n in args.species.split(",")] if args.species else None
                if names is None and args.region == "pacific":
                    from app.jobs.watchlist import PACIFIC_WATCHLIST
                    names = PACIFIC_WATCHLIST
                kw = dict(months=args.months, windows=args.windows, per_window=args.per_window, force=args.force, region=args.region)
            sync_biodiversity.run(db, uid, names, **kw)
            print("backfilled legacy rows:", sync_biodiversity.backfill_species_columns(db))
        if args.cmd in ("publish-outputs", "all"):
            from app.jobs import publish_outputs
            print(publish_outputs.publish(db, uid, days=getattr(args, "days", 14)))
        if args.cmd == "sync-climate-indices":
            from app.services import climate_indices
            print(climate_indices.sync())
        if args.cmd == "publish-dataset-alerts":
            from app.services import dataset_alerts
            print(dataset_alerts.generate(db, args.dataset))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
