"""Deteccion de publicaciones de anticipo, financiacion o cuotas.

Estas publicaciones muestran un precio parcial (anticipo o cuota)
que no representa el valor total del auto. No deben usarse como
comparables para calcular fair price.

Heuristica: busca palabras clave en el titulo normalizado.
Limitaciones conocidas:
- Solo analiza titulo, no descripcion (no siempre disponible).
- Puede haber falsos positivos si el titulo menciona "financiacion"
  en contexto distinto (ej: "acepto financiacion bancaria").
- Priorizamos evitar contaminar el fair price, asi que preferimos
  falso positivo (excluir un auto valido) a falso negativo.
"""

import re
from dataclasses import dataclass

from app.parsers.text_normalizer import normalize_text
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Patrones que indican precio parcial (anticipo, cuota, financiado)
# Se buscan en texto normalizado (lowercase, sin tildes)
_FINANCING_PATTERNS = [
    r"\banticipo\b",
    r"\bcuota[s]?\b",
    r"\bfinanciado\b",
    r"\bfinanciacion\b",
    r"\bfinanciamiento\b",
    r"\bentrega\s+y\s+cuotas\b",
    r"\bcredito\b",
    r"\bsolo\s+con\s+dni\b",
    r"\bsaldo\s+financiado\b",
    r"\bplan\s+de\s+ahorro\b",
    r"\bpermuta\b",
]

# Compilar una sola vez
_FINANCING_RE = re.compile("|".join(_FINANCING_PATTERNS))


@dataclass
class FinancingResult:
    """Resultado de la deteccion de financiamiento."""
    is_financing: bool = False
    is_down_payment: bool = False
    is_total_price_confident: bool = True
    matched_pattern: str = ""


def detect_financing(title: str | None) -> FinancingResult:
    """Detecta si un titulo indica precio parcial.

    Args:
        title: Titulo de la publicacion (texto crudo o normalizado).

    Returns:
        FinancingResult con flags de financiamiento.
    """
    result = FinancingResult()

    if not title:
        return result

    normalized = normalize_text(title)
    match = _FINANCING_RE.search(normalized)

    if not match:
        return result

    matched = match.group()
    result.matched_pattern = matched
    result.is_total_price_confident = False

    # Distinguir anticipo de financiacion generica
    if "anticipo" in matched or "entrega" in matched:
        result.is_down_payment = True
        result.is_financing = True
    else:
        result.is_financing = True

    logger.debug("Financiamiento detectado en '%s': patron='%s'", title[:60], matched)

    return result
