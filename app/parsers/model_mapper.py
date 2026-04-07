"""Model mapper: identifica el modelo normalizado de un vehiculo.

Reglas de matching (en orden de prioridad):
1. Aliases exactos (subcadena en titulo normalizado)
   - Se prioriza el alias mas largo (mas especifico)
   - Ej: "volkswagen gol trend" matchea antes que "gol"
2. Brand + alias: si el titulo tiene la marca, se refuerza el match
3. Aliases ambiguos: solo si allow_ambiguous=True
   - Palabras cortas como "clio", "gol", "ka" pueden ser ambiguas

El mapper NO intenta adivinar modelos que no estan en la config.
Si no hay match claro, retorna None.
"""

from dataclasses import dataclass
from typing import Optional

from app.config import ModelAliasesConfig
from app.parsers.text_normalizer import normalize_text
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Mapping de modelo normalizado a su marca esperada
MODEL_BRANDS: dict[str, str] = {
    "Gol Trend": "volkswagen",
    "Clio Mio": "renault",
    "Fiat Punto": "fiat",
    "Ford Ka": "ford",
    "Chevrolet Celta": "chevrolet",
}


@dataclass
class ModelMatch:
    """Resultado del mapping de modelo."""
    model_normalized: Optional[str] = None
    brand: Optional[str] = None
    confidence: str = "none"  # "high", "medium", "low", "none"
    matched_alias: str = ""


class ModelMapper:
    """Mapea titulos de publicaciones al modelo normalizado del segmento."""

    def __init__(self, config: ModelAliasesConfig, allow_ambiguous: bool = False):
        self.allow_ambiguous = allow_ambiguous
        # Construir indice de aliases ordenados por largo (mas largo primero)
        self._exact_index: list[tuple[str, str, str]] = []  # (alias_norm, model, alias_orig)
        self._ambiguous_index: list[tuple[str, str, str]] = []

        for model, aliases in config.aliases.items():
            for alias in aliases:
                alias_norm = normalize_text(alias)
                if alias_norm:
                    self._exact_index.append((alias_norm, model, alias))

        for model, aliases in config.ambiguous.items():
            for alias in aliases:
                alias_norm = normalize_text(alias)
                if alias_norm:
                    self._ambiguous_index.append((alias_norm, model, alias))

        # Ordenar por largo descendente para priorizar matches mas especificos
        self._exact_index.sort(key=lambda x: len(x[0]), reverse=True)
        self._ambiguous_index.sort(key=lambda x: len(x[0]), reverse=True)

    def match(
        self,
        title: Optional[str] = None,
        model_raw: Optional[str] = None,
        brand: Optional[str] = None,
    ) -> ModelMatch:
        """Identifica el modelo normalizado a partir de los datos disponibles.

        Args:
            title: Titulo de la publicacion.
            model_raw: Modelo crudo (puede ser igual al titulo).
            brand: Marca si se extrajo por separado (ej: de la tabla de specs).
        """
        # Construir texto combinado para buscar
        parts = [title or "", model_raw or ""]
        combined = normalize_text(" ".join(parts))

        if not combined:
            return ModelMatch()

        brand_norm = normalize_text(brand) if brand else ""

        # 1. Buscar en aliases exactos (confianza alta)
        for alias_norm, model, alias_orig in self._exact_index:
            if alias_norm in combined:
                return ModelMatch(
                    model_normalized=model,
                    brand=MODEL_BRANDS.get(model),
                    confidence="high",
                    matched_alias=alias_orig,
                )

        # 2. Buscar en aliases ambiguos con evidencia de brand (confianza media)
        if brand_norm:
            for alias_norm, model, alias_orig in self._ambiguous_index:
                expected_brand = normalize_text(MODEL_BRANDS.get(model, ""))
                if alias_norm in combined and expected_brand in brand_norm:
                    return ModelMatch(
                        model_normalized=model,
                        brand=MODEL_BRANDS.get(model),
                        confidence="medium",
                        matched_alias=alias_orig,
                    )

        # 3. Buscar brand en el titulo combinado + alias ambiguo
        for alias_norm, model, alias_orig in self._ambiguous_index:
            expected_brand = normalize_text(MODEL_BRANDS.get(model, ""))
            if alias_norm in combined and expected_brand and expected_brand in combined:
                return ModelMatch(
                    model_normalized=model,
                    brand=MODEL_BRANDS.get(model),
                    confidence="medium",
                    matched_alias=alias_orig,
                )

        # 4. Aliases ambiguos sin evidencia de brand (solo si allow_ambiguous)
        if self.allow_ambiguous:
            for alias_norm, model, alias_orig in self._ambiguous_index:
                if alias_norm in combined:
                    return ModelMatch(
                        model_normalized=model,
                        brand=MODEL_BRANDS.get(model),
                        confidence="low",
                        matched_alias=alias_orig,
                    )

        return ModelMatch()
