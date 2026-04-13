"""Priorizacion y balanceo de resultados de busqueda.

Decide cuales resultados del search se visitan en detalle,
balanceando entre queries/modelos y priorizando por precio.

Estrategia `balanced_low_price` (Fase 2 v3):

1. Filtrar ya vistos (dedup global por source_id contra DB).
2. Detectar financiamiento/anticipo en el preview:
   - si `exclude_financing_previews=True`: descartar del lote.
   - si `deprioritize_financing_previews=True`: mantener pero con penalty.
3. Calcular `preview_priority_score` por resultado (dentro de cada query):
   - base 50
   - -100 si preview financiero (y no fue excluido)
   -  -30 si no tiene precio parseable
   - +0..+50 bonus inverso a la posicion relativa de precio dentro
     de la query (el mas barato obtiene +50, el mas caro +0)
4. Ordenar cada query por `preview_priority_score` descendente.
5. Garantizar `min_details_per_query` por query (si hay candidatos).
6. Distribuir el presupuesto restante round-robin entre queries,
   respetando `max_details_per_query`.
7. Marcar `selected_for_detail=True` en los elegidos.

Todo es auditable: cada SearchResult conserva el score final y la
razon de su posicion en el lote.
"""

from dataclasses import dataclass, field
from typing import Optional

from app.parsers.listing_parser import SearchResult
from app.utils.logger import get_logger

logger = get_logger(__name__)


# --- Constantes de scoring ---

_BASE_SCORE: float = 50.0
_FINANCING_PENALTY: float = 100.0
_NO_PRICE_PENALTY: float = 30.0
_PRICE_BONUS_MAX: float = 50.0

STRATEGY_BALANCED_LOW_PRICE: str = "balanced_low_price"


@dataclass
class PrioritizationStats:
    """Estadisticas del proceso de priorizacion."""
    total_candidates: int = 0
    total_selected: int = 0
    total_excluded_by_limit: int = 0
    total_financing_detected: int = 0
    total_financing_excluded: int = 0
    total_with_price: int = 0
    total_without_price: int = 0
    strategy: str = STRATEGY_BALANCED_LOW_PRICE
    by_query: dict[str, dict] = field(default_factory=dict)


def compute_preview_priority_score(
    result: SearchResult,
    min_price_in_query: Optional[float],
    max_price_in_query: Optional[float],
    *,
    deprioritize_financing: bool = True,
    enable_score: bool = True,
) -> float:
    """Calcula el score de priorizacion de un preview dentro de su query.

    Score mas alto = mayor prioridad para entrar al detalle.
    """
    if not enable_score:
        # Fallback: solo precio, minimo neutro
        if result.price_preview is not None and result.price_preview > 0:
            return -result.price_preview  # menor precio = score mas alto
        return float("-inf")

    score = _BASE_SCORE

    if result.is_financing_preview and deprioritize_financing:
        score -= _FINANCING_PENALTY

    has_price = result.price_preview is not None and result.price_preview > 0
    if not has_price:
        score -= _NO_PRICE_PENALTY
        return score

    # Bonus por posicion relativa de precio dentro de la query
    if min_price_in_query is not None and max_price_in_query is not None:
        if max_price_in_query > min_price_in_query:
            rel = (result.price_preview - min_price_in_query) / (
                max_price_in_query - min_price_in_query
            )
            score += _PRICE_BONUS_MAX * (1.0 - rel)
        else:
            # Todos cuestan lo mismo (o uno solo): bonus completo
            score += _PRICE_BONUS_MAX

    return score


def _query_price_range(
    results: list[SearchResult],
) -> tuple[Optional[float], Optional[float]]:
    """Retorna (min, max) de precios parseables en una query."""
    prices = [
        r.price_preview for r in results
        if r.price_preview is not None and r.price_preview > 0
    ]
    if not prices:
        return None, None
    return min(prices), max(prices)


def prioritize_results(
    results_by_query: dict[str, list[SearchResult]],
    max_details_total: int = 120,
    max_details_per_query: int = 30,
    min_details_per_query: int = 5,
    prioritize_lowest_price: bool = True,
    already_seen_ids: Optional[set[str]] = None,
    *,
    deprioritize_financing: bool = True,
    exclude_financing: bool = False,
    enable_priority_score: bool = True,
    strategy: str = STRATEGY_BALANCED_LOW_PRICE,
) -> tuple[list[SearchResult], PrioritizationStats]:
    """Selecciona y prioriza resultados para visitar en detalle.

    Args:
        results_by_query: Resultados agrupados por query.
        max_details_total: Maximo total de detalles a visitar.
        max_details_per_query: Maximo por query individual.
        min_details_per_query: Minimo garantizado por query.
        prioritize_lowest_price: Si False, no ordena por precio.
        already_seen_ids: IDs ya en la DB para no re-visitar.
        deprioritize_financing: Penalizar previews con sennales financieras.
        exclude_financing: Excluir directamente previews financieros.
        enable_priority_score: Usar score numerico (True) o solo precio (False).
        strategy: Nombre de estrategia (audit). Default `balanced_low_price`.

    Returns:
        Tupla de (resultados seleccionados, estadisticas).
    """
    if already_seen_ids is None:
        already_seen_ids = set()

    stats = PrioritizationStats(strategy=strategy)
    queries = list(results_by_query.keys())
    num_queries = len(queries)

    if num_queries == 0:
        return [], stats

    # --- Paso 1: dedup + deteccion financiera + estadisticas ---
    candidates_by_query: dict[str, list[SearchResult]] = {}
    for query in queries:
        raw = results_by_query[query]
        raw_count = len(raw)
        financing_detected = 0
        financing_excluded = 0
        with_price = 0

        filtered: list[SearchResult] = []
        for r in raw:
            dedup_key = r.source_id or r.listing_url
            if dedup_key in already_seen_ids:
                continue

            if r.is_financing_preview:
                financing_detected += 1
                if exclude_financing:
                    financing_excluded += 1
                    continue

            if r.price_preview is not None and r.price_preview > 0:
                with_price += 1

            filtered.append(r)

        candidates_by_query[query] = filtered
        stats.total_candidates += len(filtered)
        stats.total_financing_detected += financing_detected
        stats.total_financing_excluded += financing_excluded
        stats.total_with_price += with_price
        stats.total_without_price += (len(filtered) - with_price)

        stats.by_query[query] = {
            "raw_count": raw_count,
            "after_dedup": len(filtered),
            "financing_detected": financing_detected,
            "financing_excluded": financing_excluded,
            "with_price": with_price,
            "without_price": len(filtered) - with_price,
            "selected": 0,
            "excluded_by_limit": 0,
        }

    # --- Paso 2: computar score y ordenar por query ---
    for query in queries:
        candidates = candidates_by_query[query]
        if not candidates:
            continue

        min_p, max_p = _query_price_range(candidates)
        for r in candidates:
            r.preview_priority_score = compute_preview_priority_score(
                r, min_p, max_p,
                deprioritize_financing=deprioritize_financing,
                enable_score=enable_priority_score,
            )

        if prioritize_lowest_price:
            # Score descendente (mayor primero); tie-break por precio asc
            candidates.sort(
                key=lambda r: (
                    -(r.preview_priority_score if r.preview_priority_score is not None else float("-inf")),
                    r.price_preview if r.price_preview is not None else float("inf"),
                    r.search_position,
                )
            )
            candidates_by_query[query] = candidates

    # --- Paso 3: asignacion balanceada ---
    # Fase A: minimo garantizado por query
    selected_by_query: dict[str, list[SearchResult]] = {q: [] for q in queries}
    remaining_budget = max_details_total

    for query in queries:
        candidates = candidates_by_query[query]
        take = min(
            min_details_per_query,
            max_details_per_query,
            len(candidates),
            remaining_budget,
        )
        if take > 0:
            selected_by_query[query] = candidates[:take]
            remaining_budget -= take

    # Fase B: distribuir presupuesto restante round-robin
    if remaining_budget > 0:
        remaining_candidates = {
            q: candidates_by_query[q][len(selected_by_query[q]):]
            for q in queries
        }
        for q in queries:
            cap = max_details_per_query - len(selected_by_query[q])
            remaining_candidates[q] = remaining_candidates[q][:cap]

        if sum(len(v) for v in remaining_candidates.values()) > 0:
            _distribute_round_robin(
                selected_by_query, remaining_candidates, remaining_budget, queries
            )

    # --- Paso 4: construir resultado final + marcar seleccionados ---
    selected: list[SearchResult] = []
    for query in queries:
        query_selected = selected_by_query[query]
        for r in query_selected:
            r.selected_for_detail = True
        stats.by_query[query]["selected"] = len(query_selected)
        stats.by_query[query]["excluded_by_limit"] = (
            stats.by_query[query]["after_dedup"] - len(query_selected)
        )
        stats.total_excluded_by_limit += stats.by_query[query]["excluded_by_limit"]
        selected.extend(query_selected)

    stats.total_selected = len(selected)

    # --- Logging ---
    logger.info(
        "Priorizacion [%s]: %d candidatos -> %d seleccionados "
        "(%d excluidos por limite | %d financieros detectados, %d financieros excluidos | "
        "%d con precio, %d sin precio)",
        stats.strategy,
        stats.total_candidates,
        stats.total_selected,
        stats.total_excluded_by_limit,
        stats.total_financing_detected,
        stats.total_financing_excluded,
        stats.total_with_price,
        stats.total_without_price,
    )
    for query in queries:
        qs = stats.by_query[query]
        logger.info(
            "  Query '%s': raw=%d nuevos=%d fin=%d exc_fin=%d precio=%d s/precio=%d "
            "seleccionados=%d excluidos_limite=%d",
            query, qs["raw_count"], qs["after_dedup"],
            qs["financing_detected"], qs["financing_excluded"],
            qs["with_price"], qs["without_price"],
            qs["selected"], qs["excluded_by_limit"],
        )

    return selected, stats


def _distribute_round_robin(
    selected: dict[str, list[SearchResult]],
    remaining: dict[str, list[SearchResult]],
    budget: int,
    queries: list[str],
) -> None:
    """Distribuye presupuesto restante en round-robin entre queries."""
    allocated = 0
    keep_going = True

    while allocated < budget and keep_going:
        keep_going = False
        for query in queries:
            if allocated >= budget:
                break
            if remaining[query]:
                selected[query].append(remaining[query].pop(0))
                allocated += 1
                keep_going = True
