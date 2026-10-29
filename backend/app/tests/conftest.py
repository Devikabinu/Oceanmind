import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg2://ocean_admin:change_me_locally@localhost:5432/ocean_platform_test",
)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.db.base import Base
from app.main import app

TEST_DATABASE_URL = os.environ["DATABASE_URL"]

engine = create_engine(TEST_DATABASE_URL, future=True)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@pytest.fixture(scope="session", autouse=True)
def _setup_database():
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def _clean_tables():
    yield
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


@pytest.fixture
def db_session():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_session):
    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def outputs(tmp_path, monkeypatch):
    """A tiny synthetic ML-export directory (test data only) wired in as the processed/ directory."""
    from app.services import environment
    from app.tests._outputs import build

    build(tmp_path)
    monkeypatch.setattr(environment, "processed_dir", lambda: tmp_path)
    environment.clear_cache()
    yield tmp_path
    environment.clear_cache()


@pytest.fixture(autouse=True)
def _no_live_external_data(tmp_path, monkeypatch):
    """No test reaches OBIS or NOAA ERDDAP: the live services are switched off and their caches point into the test's own folder."""
    from app.services import obis_service, ocean_context, physical_drivers
    monkeypatch.setattr(obis_service, "ENABLED", False)
    monkeypatch.setattr(ocean_context, "ENABLED", False)
    monkeypatch.setattr(physical_drivers, "ENABLED", False)
    monkeypatch.setattr(physical_drivers, "cache_dir", lambda: tmp_path / "physical_cache")
    physical_drivers.clear_state()
    from app.core.config import get_settings
    from app.services import physical_interpretation
    monkeypatch.setattr(get_settings(), "AI_PROVIDER", "none", raising=False)                  # no test reaches an AI provider; the cache points into the test's folder
    monkeypatch.setattr(physical_interpretation, "_cache_dir", lambda: tmp_path / "physical_ai")
    physical_interpretation.clear_state()
    monkeypatch.setattr(obis_service, "cache_dir", lambda: tmp_path / "obis_cache")
    monkeypatch.setattr(ocean_context, "cache_dir", lambda: tmp_path / "context_cache")
    obis_service.clear_state()
    ocean_context.clear_state()
    yield
    obis_service.clear_state()
    ocean_context.clear_state()


@pytest.fixture(autouse=True)
def _no_real_climate_indices(tmp_path, monkeypatch):
    """Tests never depend on the climate-index file a developer may have downloaded."""
    from app.services import climate_indices

    monkeypatch.setattr(climate_indices, "index_file", lambda: tmp_path / "no_indices.json")
    climate_indices._load_cached.cache_clear()
