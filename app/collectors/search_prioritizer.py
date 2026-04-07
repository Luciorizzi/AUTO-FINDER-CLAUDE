"""Priorizacion y balanceo de resultados de busqueda.

Decide cuales resultados del search se visitan en detalle,
balanceando entre queries/modelos y priorizando por precio.
"""

from dataclasses import dataclass, field
from typing import Optional

from app.parsers.listing_parser import SearchResult
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class PrioritizationStats:
    """Estadisticas del proceso de priorizacion."""
    total_candidates: int = 0
    total_selected: int = 0
    total_excluded_by_limit: int = 0
    by_query: dict[str, dict] = field(default_factory=dict)


def prioritize_results(
    results_by_query: dict[str, list[SearchResult]],
    max_details_total: int = 120,
    max_details_per_query: int = 30,
    min_details_per_query: int = 5,
    prioritize_lowest_price: bool = True,
    already_seen_ids: Optional[set[str]] = None,
) -> tuple[list[SearchResult], PrioritizationStats]:
    """Selecciona y prioriza resultados para visitar en detalle.

    Estrategia:
    1. Filtra resultados ya vistos (dedup global por source_id).
    2. Garantiza un minimo de resultados por query (si hay disponibles).
    3. Dentro de cada query, prioriza por menor precio (si habilitado).
    4. Resultados sin precio parseable van al final de cada query.
    5. Distribuye el presupuesto restante proporcionalmente.

    Args:
        results_by_query: Resultados agrupados por query.
        max_details_total: Maximo total de detalles a visitar.
        max_details_per_query: Maximo por query individual.
        min_details_per_query: Minimo garantizado por query.
        prioritize_lowest_price: Ordenar por menor precio dentro de cada query.
        already_seen_ids: IDs ya en la DB para no re-visitar.

    Returns:
        Tupla de (resultados seleccionados, estadisticas).
    """
    if already_seen_ids is None:
        already_seen_ids = set()

    stats = PrioritizationStats()
    queries = list(results_by_query.keys())
    num_queries = len(queries)

    if num_queries == 0:
        return [], stats

    # --- Paso 1: Filtrar ya vistos y preparar candidatos por query ---
    candidates_by_query: dict[str, list[SearchResult]] = {}
    for query in queries:
        raw = results_by_query[query]
        filtered = [
            r for r in raw
            if (r.source_id or r.listing_url) not in already_seen_ids
        ]
        candidates_by_query[query] = filtered
        stats.total_candidates += len(filtered)

        stats.by_query[query] = {
            "raw_count": len(raw),
            "after_dedup": len(filtered),
            "selected": 0,
            "excluded_by_limit": 0,
        }

    # --- Paso 2: Ordenar candidatos dentro de cada query ---
    for query in queries:
        candidates = candidates_by_query[query]
        if prioritize_lowest_price:
            candidates.sort(key=_price_sort_key)
            candidates_by_query[query] = candidates

    # --- Paso 3: Asignacion balanceada ---
    # Fase A: garantizar minimo por query
    selected_by_query: dict[str, list[SearchResult]] = {q: [] for q in queries}
    remaining_budget = max_details_total

    for query in queries:
        candidates = candidates_by_query[query]
        take = min(min_details_per_query, max_details_per_query, len(candidates), remaining_budget)
        if take > 0:
            selected_by_query[query] = candidates[:take]
            remaining_budget -= take

    # Fase B: distribuir presupuesto restante proporcionalmente
    if remaining_budget > 0:
        # Candidatos no tomados aun, por query
        remaining_candidates = {
            q: candidates_by_query[q][len(selected_by_query[q]):]
            for q in queries
        }
        # Aplicar cap per-query
        for q in queries:
            cap = max_details_per_query - len(selected_by_query[q])
            remaining_candidates[q] = remaining_candidates[q][:cap]

        # Repartir round-robin
        total_remaining = sum(len(v) for v in remaining_candidates.values())
        if total_remaining > 0:
            _distribute_round_robin(
                selected_by_query, remaining_candidates, remaining_budget, queries
            )

    # --- Paso 4: Construir resultado final ---
    selected: list[SearchResult] = []
    for query in queries:
        query_selected = selected_by_query[query]
        stats.by_query[query]["selected"] = len(query_selected)
        stats.by_query[query]["excluded_by_limit"] = (
            stats.by_query[query]["after_dedup"] - len(query_selected)
        )
        stats.total_excluded_by_limit += stats.by_query[query]["excluded_by_limit"]
        selected.extend(query_selected)

    stats.total_selected = len(selected)

    # --- Logging ---
    logger.info(
        "Priorizacion: %d candidatos -> %d seleccionados (%d excluidos por limite)",
        stats.total_candidates, stats.total_selected, stats.total_excluded_by_limit,
    )
    for query in queries:
        qs = stats.by_query[query]
        logger.info(
            "  Query '%s': %d encontrados, %d nuevos, %d seleccionados, %d excluidos",
            query, qs["raw_count"], qs["after_dedup"], qs["selected"], qs["excluded_by_limit"],
        )

    return selected, stats


def _price_sort_key(result: SearchResult) -> tuple[int, float]:
    """Key para ordenar: precio parseable primero (menor a mayor), sin precio al final."""
    if result.price_preview is not None and result.price_preview > 0:
        return (0, result.price_preview)
    return (1, float("inf"))


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
