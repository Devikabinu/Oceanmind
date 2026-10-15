from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"

    DATABASE_URL: str = "postgresql+psycopg2://ocean_admin:change_me_locally@localhost:5432/ocean_platform"

    JWT_SECRET_KEY: str = "insecure-dev-secret-change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    FRONTEND_ORIGIN: str = "http://localhost:5173"

    # Where the ML pipeline writes its outputs (metrics, dashboard snapshot). Empty = <repo>/processed.
    PROCESSED_DIR: str = ""

    NOAA_OISST_BASE_URL: str = (
        "https://psl.noaa.gov/thredds/dodsC/Datasets/noaa.oisst.v2.highres"
    )

    COPERNICUS_MARINE_USERNAME: str = ""
    COPERNICUS_MARINE_PASSWORD: str = ""
    COPERNICUS_MARINE_DATASET_ID: str = "cmems_obs-sst_glo_phy_nrt_l4_P1D-m"

    OBIS_API_BASE_URL: str = "https://api.obis.org/v3"


@lru_cache
def get_settings() -> Settings:
    return Settings()
