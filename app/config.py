"""Configuracion central del proyecto.

Carga variables de entorno (.env) y archivos YAML de configs/.
Expone modelos Pydantic validados para uso en toda la app.
"""

from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


# Rutas base
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIGS_DIR = PROJECT_ROOT / "configs"

# Cargar .env desde la raiz del proyecto
load_dotenv(PROJECT_ROOT / ".env")


# --- Modelos de entorno ---

class EnvSettings(BaseSettings):
    """Variables de entorno cargadas desde .env."""
    database_path: str = "data/autofinder.db"
    log_level: str = "INFO"

    # Scraping
    headless: bool = True
    scrape_delay_seconds: float = 2.0
    ml_max_results_per_query: int = 48
    ml_max_detail_pages_per_run: int = 120
    ml_max_details_per_query: int = 30
    min_details_per_query: int = 5
    prioritize_lowest_price_first: bool = True
    enable_search_position_capture: bool = True
    browser_timeout_ms: int = 30000
    user_agent: str = ""

    # Pricing
    pricing_batch_size: int = 200
    enable_outlier_filtering: bool = True
    enable_financing_filter: bool = True
    enable_dominance_rule: bool = True

    # Normalizacion
    normalization_batch_size: int = 200
    enable_heuristic_dedup: bool = True
    duplicate_price_tolerance_pct: float = 5.0
    duplicate_mileage_tolerance: int = 2000
    allow_ambiguous_models: bool = False

    # Telegram (Fase 4+)
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
    )


# --- Modelos de configs YAML ---

class SegmentConfig(BaseModel):
    name: str
    year_min: int
    year_max: int
    km_max: int
    km_comparable_delta: int
    models: list[str]


class ThresholdsConfig(BaseModel):
    strong_gap: float
    medium_gap: float
    alert_high_risk: bool = False


class RiskConfig(BaseModel):
    low_min_comparables: int = 8
    medium_min_comparables: int = 5


class PricingConfig(BaseModel):
    """Parametros del motor de pricing."""
    min_comparables: int = 3
    extreme_gap_pct: float = -30.0
    iqr_factor: float = 1.5
    max_cv: float = 0.40


class ComparableLevelsConfig(BaseModel):
    """Niveles de comparables: A (estricto) y B (ampliado)."""
    level_a_max_year_diff: int = 1
    level_a_max_km_diff: int = 15000
    level_b_max_year_diff: int = 2
    level_b_max_km_diff: int = 20000
    min_comparables_level_a: int = 3


class DominanceConfig(BaseModel):
    """Parametros de la regla de dominancia."""
    price_tolerance_pct: float = 5.0
    min_km_advantage: int = 3000


class PriorityConfig(BaseModel):
    """Parametros del motor de priorizacion operativa (Fase 4.2).

    Separa la oportunidad estadistica (gap contra mediana) de la
    prioridad operativa (que aviso conviene mirar primero).
    """
    # Freshness boosts
    freshness_1d_boost: float = 25.0
    freshness_3d_boost: float = 15.0
    freshness_7d_boost: float = 5.0
    # Local rank bonuses
    local_top1_bonus: float = 30.0
    local_top3_bonus: float = 15.0
    # Microgrupo local (year/km delta)
    local_group_max_year_diff: int = 1
    local_group_max_km_diff: int = 15000
    local_min_group_size: int = 3
    # Penalties
    dominance_penalty: float = 40.0
    anomaly_high_penalty: float = 25.0
    # Markdown (rebaja)
    markdown_significant_pct: float = 3.0
    markdown_bonus: float = 20.0
    # Price edge cap
    price_edge_cap: float = 40.0
    # Umbrales de final_priority_level
    urgent_review_threshold: float = 70.0
    high_priority_threshold: float = 45.0
    medium_priority_threshold: float = 20.0


class ModelAliasesConfig(BaseModel):
    """Mapeo de modelo normalizado -> lista de aliases."""
    aliases: dict[str, list[str]]
    ambiguous: dict[str, list[str]] = {}


class ScrapingConfig(BaseModel):
    """Configuracion de scraping desde YAML."""
    search_queries: list[str]
    base_url: str = "https://autos.mercadolibre.com.ar"


# --- Funciones de carga ---

def _load_yaml(filename: str) -> dict[str, Any]:
    """Carga un archivo YAML desde configs/."""
    filepath = CONFIGS_DIR / filename
    if not filepath.exists():
        raise FileNotFoundError(f"Config no encontrado: {filepath}")
    with open(filepath, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_env() -> EnvSettings:
    """Carga y valida variables de entorno."""
    return EnvSettings()


def load_segment_rules() -> SegmentConfig:
    """Carga reglas de segmento desde YAML."""
    data = _load_yaml("segment_rules.yaml")
    return SegmentConfig(**data["segment"])


def load_thresholds() -> ThresholdsConfig:
    """Carga umbrales de oportunidad desde YAML."""
    data = _load_yaml("thresholds.yaml")
    return ThresholdsConfig(**data["thresholds"])


def load_risk_config() -> RiskConfig:
    """Carga criterios de riesgo desde YAML."""
    data = _load_yaml("thresholds.yaml")
    return RiskConfig(**data.get("risk", {}))


def load_pricing_config() -> PricingConfig:
    """Carga parametros de pricing desde YAML."""
    data = _load_yaml("thresholds.yaml")
    return PricingConfig(**data.get("pricing", {}))


def load_comparable_levels() -> ComparableLevelsConfig:
    """Carga niveles de comparables desde YAML."""
    data = _load_yaml("thresholds.yaml")
    return ComparableLevelsConfig(**data.get("comparable_levels", {}))


def load_dominance_config() -> DominanceConfig:
    """Carga parametros de dominancia desde YAML."""
    data = _load_yaml("thresholds.yaml")
    return DominanceConfig(**data.get("dominance", {}))


def load_priority_config() -> PriorityConfig:
    """Carga parametros de priorizacion operativa desde YAML."""
    data = _load_yaml("thresholds.yaml")
    return PriorityConfig(**data.get("priority", {}))


def load_model_aliases() -> ModelAliasesConfig:
    """Carga aliases de modelos desde YAML."""
    data = _load_yaml("model_aliases.yaml")
    return ModelAliasesConfig(
        aliases=data["aliases"],
        ambiguous=data.get("ambiguous", {}),
    )


def load_scraping_config() -> ScrapingConfig:
    """Carga configuracion de scraping desde YAML."""
    data = _load_yaml("scraping.yaml")
    return ScrapingConfig(**data["scraping"])


def get_database_path() -> Path:
    """Retorna la ruta absoluta a la base de datos SQLite."""
    env = load_env()
    db_path = Path(env.database_path)
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path
    return db_path
