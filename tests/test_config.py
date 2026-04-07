"""Tests de carga de configuracion."""

from app.config import (
    CONFIGS_DIR,
    PROJECT_ROOT,
    load_env,
    load_model_aliases,
    load_segment_rules,
    load_thresholds,
    load_risk_config,
    get_database_path,
)


def test_project_root_exists():
    assert PROJECT_ROOT.exists()


def test_configs_dir_exists():
    assert CONFIGS_DIR.exists()


def test_load_env():
    env = load_env()
    assert env.log_level in ("DEBUG", "INFO", "WARNING", "ERROR")
    assert env.database_path != ""


def test_load_segment_rules():
    segment = load_segment_rules()
    assert segment.name == "hatchbacks_basicos"
    assert segment.year_min == 2010
    assert segment.year_max == 2015
    assert segment.km_max == 110000
    assert segment.km_comparable_delta == 15000
    assert len(segment.models) == 5
    assert "Gol Trend" in segment.models


def test_load_thresholds():
    thresholds = load_thresholds()
    assert thresholds.strong_gap == -12
    assert thresholds.medium_gap == -8
    assert thresholds.alert_high_risk is False


def test_load_risk_config():
    risk = load_risk_config()
    assert risk.low_min_comparables == 8
    assert risk.medium_min_comparables == 5


def test_load_model_aliases():
    aliases = load_model_aliases()
    assert "Gol Trend" in aliases.aliases
    assert "Clio Mio" in aliases.aliases
    assert "gol trend" in aliases.aliases["Gol Trend"]


def test_database_path_is_absolute():
    db_path = get_database_path()
    assert db_path.is_absolute()
