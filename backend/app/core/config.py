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
    # Output of `python -m oceanmind_preprocess build --config config.pacific.yaml` (Pacific-wide processed data). Empty = <repo>/processed_pacific.
    PROCESSED_PACIFIC_DIR: str = ""
    # Which processed environmental dataset the environmental endpoints use when the request names none: "ne_pacific" (stored NOAA OISST study
    # region, the original behaviour) or "pacific" (Pacific-wide processed provider data).
    ENVIRONMENT_DEFAULT_DATASET: str = "ne_pacific"

    NOAA_OISST_BASE_URL: str = (
        "https://psl.noaa.gov/thredds/dodsC/Datasets/noaa.oisst.v2.highres"
    )

    OBIS_API_BASE_URL: str = "https://api.obis.org/v3"

    # Optional AI wording of the physical interpretation. Off by default: nothing is sent anywhere unless these are set in the backend .env. The key stays on the backend.
    AI_PROVIDER: str = "none"          # none | anthropic | openai_compatible
    AI_API_KEY: str = ""
    AI_MODEL: str = ""
    AI_BASE_URL: str = ""              # required for openai_compatible; optional for anthropic (proxy or compatible endpoint)
    AI_TIMEOUT_S: float = 25.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
