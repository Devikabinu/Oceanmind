import logging

from sqlalchemy.orm import Session

from app.models.data_source import DataSource
from app.models.enums import DataSourceStatus
from app.repositories.data_source_repository import DataSourceRepository

logger = logging.getLogger("ocean_platform")

DEFAULT_DATA_SOURCES = [
    DataSource(
        name="NOAA OISST v2.1",
        provider="NOAA Physical Sciences Laboratory",
        dataset="Optimum Interpolation Sea Surface Temperature (OISST) v2.1, 0.25deg daily",
        version="2.1",
        description=(
            "NOAA 0.25-degree Daily Optimum Interpolation Sea Surface Temperature. "
            "Provides gridded daily SST, SST anomaly, estimation error, and sea-ice "
            "concentration on a global 0.25deg lat/lon grid."
        ),
        source_url="https://psl.noaa.gov/data/gridded/data.noaa.oisst.v2.highres.html",
        status=DataSourceStatus.ACTIVE,
    ),
    DataSource(
        name="Copernicus Marine SST",
        provider="Copernicus Marine Service (CMEMS)",
        dataset="Global Ocean OSTIA Sea Surface Temperature and Sea Ice Analysis / GMPE Multi-Product Ensemble",
        version="latest",
        description=(
            "Copernicus Marine Global Ocean Multi-Product Ensemble (GMPE) sea surface "
            "temperature, used here as a secondary SST source for cross-validation "
            "against NOAA OISST."
        ),
        source_url="https://data.marine.copernicus.eu/products?facets=mainVariables%7ESea+surface+temperature",
        status=DataSourceStatus.ACTIVE,
    ),
    DataSource(
        name="OBIS",
        provider="Ocean Biodiversity Information System",
        dataset="OBIS marine species occurrence records",
        version="v3 API",
        description=(
            "Global marine species occurrence records (scientific name, coordinates, "
            "event date, depth range, occurrence status) queried as geographic and "
            "temporal subsets rather than a full bulk download."
        ),
        source_url="https://obis.org",
        status=DataSourceStatus.ACTIVE,
    ),
]


def seed_data_sources(db: Session) -> None:
    repo = DataSourceRepository(db)
    for source in DEFAULT_DATA_SOURCES:
        if repo.get_by_name(source.name) is not None:
            continue
        repo.create(
            DataSource(
                name=source.name,
                provider=source.provider,
                dataset=source.dataset,
                version=source.version,
                description=source.description,
                source_url=source.source_url,
                status=source.status,
            )
        )
        logger.info("Seeded data source: %s", source.name)
