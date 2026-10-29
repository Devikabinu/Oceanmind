"""The application must not name data providers it does not use, and must not label the active NOAA dataset as generated or synthetic."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP = {".venv", "node_modules", "__pycache__", "dist", ".git", "logs", "data", "processed", "processed_pacific", "tests", "__tests__"}


def source_files(*roots, suffixes=(".py", ".ts", ".tsx", ".md", ".yaml", ".yml", ".txt", ".example", ".json")):
    for r in roots:
        base = ROOT / r
        files = [base] if base.is_file() else base.rglob("*")
        for f in files:
            if f.is_file() and f.suffix in suffixes and not (set(f.relative_to(ROOT).parts) & SKIP) and f.name != "package-lock.json":
                yield f


def test_no_copernicus_in_active_code_config_docs_or_requirements():
    hits = [str(f.relative_to(ROOT)) for f in source_files("backend/app", "backend/requirements.txt", "backend/requirements-local.txt", "frontend/src", "oceanmind_environment",
                                                         "oceanmind_model", "oceanmind_preprocess", "docs", "README.md", "config.yaml", "config.pacific.yaml", ".env.example")
            if re.search("copernicus", f.read_text(encoding="utf-8", errors="ignore"), re.I)]
    assert hits == []
    assert not (ROOT / "backend/app/ingestion/copernicus_adapter.py").exists()


def test_the_active_dataset_is_never_called_generated_in_user_facing_text():
    text = " ".join(f.read_text(encoding="utf-8", errors="ignore") for f in source_files("frontend/src/components", "frontend/src/pages"))
    for phrase in ("synthetic data", "fabricated", "demo data", "generated data", "placeholder data"):
        assert phrase not in text.lower(), phrase


def test_users_never_see_the_word_medium_for_a_risk_level():
    text = " ".join(f.read_text(encoding="utf-8", errors="ignore") for f in source_files("frontend/src/components", "frontend/src/pages"))
    assert not re.search(r">\s*Medium\b|label: \"Medium|>MEDIUM<", text)
