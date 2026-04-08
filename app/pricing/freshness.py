"""Calculo de freshness (antiguedad del aviso) y boost de prioridad.

Un aviso recientemente publicado es mas urgente de mirar porque las
oportunidades tienden a durar poco. Este modulo clasifica cada listing
en un bucket de frescura y devuelve un boost para el ranking operativo.

Reglas:
- 0 a 1 dia     -> bucket "0-1d",  boost alto
- 1 a 3 dias    -> bucket "1-3d",  boost medio
- 3 a 7 dias    -> bucket "3-7d",  boost bajo
- mas de 7 dias -> bucket ">7d",   sin boost

La frescura por si sola NO convierte un auto en oportunidad. Solo sube
el ranking de autos que ya son atractivos por precio. Autos viejos
no se castigan: simplemente no reciben bonus.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

BUCKET_0_1D = "0-1d"
BUCKET_1_3D = "1-3d"
BUCKET_3_7D = "3-7d"
BUCKET_OLD = ">7d"
BUCKET_UNKNOWN = "unknown"


@dataclass
class FreshnessResult:
    """Resultado del calculo de freshness."""
    bucket: str = BUCKET_UNKNOWN
    days_on_market: Optional[int] = None
    boost: float = 0.0


def _parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    """Parsea un timestamp ISO o del formato SQLite 'YYYY-MM-DD HH:MM:SS'.

    Retorna None si el valor es invalido o None. Siempre retorna datetimes
    aware (con tz=UTC) para poder restar entre si.
    """
    if not value:
        return None
    try:
        # ISO con tz
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            # Formato SQLite datetime('now') -> "YYYY-MM-DD HH:MM:SS"
            dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            logger.debug("No se pudo parsear timestamp: %s", value)
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def compute_freshness(
    first_seen_at: Optional[str],
    boost_1d: float = 25.0,
    boost_3d: float = 15.0,
    boost_7d: float = 5.0,
    now: Optional[datetime] = None,
) -> FreshnessResult:
    """Clasifica un listing en un bucket de frescura y calcula el boost.

    Args:
        first_seen_at: Timestamp ISO/SQLite de cuando se vio por primera vez.
        boost_1d/3d/7d: Boosts por bucket.
        now: Timestamp actual (para tests reproducibles).

    Returns:
        FreshnessResult con bucket, days_on_market y boost.
    """
    dt = _parse_timestamp(first_seen_at)
    if dt is None:
        return FreshnessResult(bucket=BUCKET_UNKNOWN, days_on_market=None, boost=0.0)

    current = now or datetime.now(timezone.utc)
    delta_days = (current - dt).total_seconds() / 86400.0
    days_int = max(0, int(delta_days))

    if delta_days <= 1.0:
        return FreshnessResult(bucket=BUCKET_0_1D, days_on_market=days_int, boost=boost_1d)
    if delta_days <= 3.0:
        return FreshnessResult(bucket=BUCKET_1_3D, days_on_market=days_int, boost=boost_3d)
    if delta_days <= 7.0:
        return FreshnessResult(bucket=BUCKET_3_7D, days_on_market=days_int, boost=boost_7d)
    return FreshnessResult(bucket=BUCKET_OLD, days_on_market=days_int, boost=0.0)
