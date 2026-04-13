"""Pipeline de pricing por comparables (v2 + Fase 4.2).

Fase 4 v2:
- Comparables solo de la misma moneda (ARS con ARS, USD con USD)
- Exclusion de publicaciones de anticipo/financiacion
- Comparables por niveles A/B (anio pesa fuerte)
- Regla de dominancia para evitar oportunidades falsas

Fase 4.2:
- Ranking local dentro del microgrupo comparable
- Freshness scoring / boost por antiguedad
- Senales historicas de precio desde listing_snapshots
- Score final de prioridad operativa separado del opportunity_level
- Niveles operativos: urgent_review / high_priority / medium_priority / low_priority

Flujo por cada listing:
1. Detectar y persistir flags de financiamiento
2. Buscar comparables (mismo modelo, misma moneda, niveles A/B)
3. Filtrar outliers de precio (IQR)
4. Calcular fair price (mediana)
5. Calcular gap porcentual
6. Verificar dominancia
7. Clasificar oportunidad economica (con degradacion por dominancia)
8. Evaluar riesgo de anomalia
9. Calcular ranking local dentro del microgrupo
10. Calcular freshness bucket + boost
11. Calcular senales historicas de precio
12. Calcular final_priority_score + final_priority_level
13. Persistir resultado completo
"""

import sqlite3
from collections import Counter
from dataclasses import dataclass, field

from app.config import (
    ComparableLevelsConfig,
    DominanceConfig,
    EnvSettings,
    PriorityConfig,
    PricingConfig,
    RiskConfig,
    ThresholdsConfig,
)
from app.filters.financing_detector import detect_financing
from app.pricing.comparable_finder import find_comparables
from app.pricing.dominance_checker import check_dominance
from app.pricing.fair_price import calculate_fair_price
from app.pricing.freshness import compute_freshness
from app.pricing.local_rank import compute_local_rank
from app.pricing.opportunity_score import classify_opportunity
from app.pricing.price_history import compute_price_history
from app.pricing.priority_score import compute_priority_score
from app.risk.anomaly_detector import assess_anomaly_risk
from app.storage.repositories import (
    get_listings_for_pricing,
    save_pricing_analysis,
    update_financing_flags,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class PricingSummary:
    """Resumen de una corrida de pricing."""
    total_read: int = 0
    total_analyzed: int = 0
    total_skipped_financing: int = 0
    total_enough_data: int = 0
    total_insufficient_data: int = 0
    total_no_data: int = 0
    total_strong: int = 0
    total_medium: int = 0
    total_not_opportunity: int = 0
    total_dominated: int = 0
    total_high_risk: int = 0
    # Fase 4.2: prioridad operativa
    total_urgent_review: int = 0
    total_high_priority: int = 0
    total_medium_priority: int = 0
    total_low_priority: int = 0
    total_top_local_1: int = 0
    total_markdown: int = 0
    total_errors: int = 0
    models_analyzed: dict[str, int] = field(default_factory=dict)


def run_pricing_batch(
    conn: sqlite3.Connection,
    thresholds: ThresholdsConfig,
    risk_config: RiskConfig,
    pricing_config: PricingConfig,
    comp_levels: ComparableLevelsConfig,
    dominance_config: DominanceConfig,
    priority_config: PriorityConfig,
    env: EnvSettings,
) -> PricingSummary:
    """Ejecuta el pipeline de pricing sobre listings pendientes."""
    summary = PricingSummary()

    listings = get_listings_for_pricing(conn, limit=env.pricing_batch_size)
    summary.total_read = len(listings)

    if not listings:
        logger.info("No hay listings pendientes de pricing")
        return summary

    logger.info("Procesando pricing para %d listings", len(listings))

    model_counter: Counter = Counter()

    for listing in listings:
        listing_id = listing["id"]
        model = listing.get("model_normalized", "unknown")
        currency = listing.get("currency") or "ARS"

        try:
            # 1. Detectar financiamiento
            fin_result = detect_financing(listing.get("title"))
            if env.enable_financing_filter:
                update_financing_flags(
                    conn, listing_id,
                    is_financing=fin_result.is_financing,
                    is_down_payment=fin_result.is_down_payment,
                    is_total_price_confident=fin_result.is_total_price_confident,
                )

            # Si es financiamiento, no analizar pricing
            if env.enable_financing_filter and not fin_result.is_total_price_confident:
                summary.total_skipped_financing += 1
                save_pricing_analysis(
                    conn=conn, listing_id=listing_id,
                    published_price=listing["price"], fair_price=None,
                    gap_pct=None, opportunity_level="not_opportunity",
                    anomaly_risk="alto", anomaly_reasons="financing_listing",
                    comparables_found=0, comparables_used=0,
                    min_comparable_price=None, max_comparable_price=None,
                    median_comparable_price=None, p25_comparable_price=None,
                    pricing_status="skipped_financing",
                    currency_used=currency,
                    final_priority_level="low_priority",
                    final_priority_score=0.0,
                )
                summary.total_analyzed += 1
                summary.total_low_priority += 1
                continue

            # 2. Buscar comparables con niveles A/B
            comp_result = find_comparables(
                conn=conn,
                listing_id=listing_id,
                model_normalized=model,
                km=listing["km"],
                year=listing.get("year", 0),
                currency=currency,
                level_a_max_year_diff=comp_levels.level_a_max_year_diff,
                level_a_max_km_diff=comp_levels.level_a_max_km_diff,
                level_b_max_year_diff=comp_levels.level_b_max_year_diff,
                level_b_max_km_diff=comp_levels.level_b_max_km_diff,
                min_comparables_level_a=comp_levels.min_comparables_level_a,
            )

            comparable_prices = [c["price"] for c in comp_result.comparables]

            # 3+4. Calcular fair price
            fp_result = calculate_fair_price(
                comparable_prices=comparable_prices,
                min_comparables=pricing_config.min_comparables,
                enable_outlier_filtering=env.enable_outlier_filtering,
                iqr_factor=pricing_config.iqr_factor,
            )

            # 5+6. Dominancia
            is_dominated = False
            dom_result = None
            if env.enable_dominance_rule and comp_result.comparables:
                dom_result = check_dominance(
                    listing_id=listing_id,
                    year=listing.get("year", 0),
                    km=listing["km"],
                    price=listing["price"],
                    comparables=comp_result.comparables,
                    price_tolerance_pct=dominance_config.price_tolerance_pct,
                    min_km_advantage=dominance_config.min_km_advantage,
                )
                is_dominated = dom_result.is_dominated

            # 7. Clasificar oportunidad (con dominancia)
            opp_result = classify_opportunity(
                published_price=listing["price"],
                fair_price=fp_result.fair_price,
                strong_gap=thresholds.strong_gap,
                medium_gap=thresholds.medium_gap,
                is_dominated=is_dominated,
            )

            # 8. Evaluar riesgo
            anomaly = assess_anomaly_risk(
                comparables_found=fp_result.comparables_found,
                comparables_used=fp_result.comparables_used,
                gap_pct=opp_result.gap_pct,
                cv=fp_result.cv,
                pricing_status=fp_result.pricing_status,
                published_price=listing["price"],
                km=listing["km"],
                low_min_comparables=risk_config.low_min_comparables,
                medium_min_comparables=risk_config.medium_min_comparables,
                extreme_gap_pct=pricing_config.extreme_gap_pct,
                max_cv=pricing_config.max_cv,
            )

            # --- Fase 4.2 ---

            # 9. Ranking local dentro del microgrupo
            local_rank = compute_local_rank(
                target_price=listing["price"],
                comparables=comp_result.comparables,
                target_year=listing.get("year"),
                target_km=listing.get("km"),
                local_group_max_year_diff=priority_config.local_group_max_year_diff,
                local_group_max_km_diff=priority_config.local_group_max_km_diff,
                local_min_group_size=priority_config.local_min_group_size,
            )

            # 10. Freshness
            freshness = compute_freshness(
                first_seen_at=listing.get("first_seen_at"),
                boost_1d=priority_config.freshness_1d_boost,
                boost_3d=priority_config.freshness_3d_boost,
                boost_7d=priority_config.freshness_7d_boost,
            )

            # 11. Historial de precio
            history = compute_price_history(
                conn=conn,
                listing_id=listing_id,
                current_price=listing.get("price"),
            )

            # days_on_market: preferir freshness, sino historia
            days_on_market = freshness.days_on_market
            if days_on_market is None:
                days_on_market = history.history_days_on_market

            # 12. Priority score final
            priority = compute_priority_score(
                gap_pct=opp_result.gap_pct,
                is_top_local_price_1=local_rank.is_top_local_price_1,
                is_top_local_price_3=local_rank.is_top_local_price_3,
                freshness_boost=freshness.boost,
                markdown_pct=history.markdown_pct,
                is_dominated=is_dominated,
                anomaly_risk=anomaly.risk_level,
                price_edge_cap=priority_config.price_edge_cap,
                local_top1_bonus=priority_config.local_top1_bonus,
                local_top3_bonus=priority_config.local_top3_bonus,
                markdown_significant_pct=priority_config.markdown_significant_pct,
                markdown_bonus=priority_config.markdown_bonus,
                dominance_penalty=priority_config.dominance_penalty,
                anomaly_high_penalty=priority_config.anomaly_high_penalty,
                urgent_review_threshold=priority_config.urgent_review_threshold,
                high_priority_threshold=priority_config.high_priority_threshold,
                medium_priority_threshold=priority_config.medium_priority_threshold,
            )

            # 13. Persistir
            anomaly_reasons_str = ",".join(anomaly.reasons) if anomaly.reasons else None

            save_pricing_analysis(
                conn=conn,
                listing_id=listing_id,
                published_price=listing["price"],
                fair_price=fp_result.fair_price,
                gap_pct=opp_result.gap_pct,
                opportunity_level=opp_result.opportunity_level,
                anomaly_risk=anomaly.risk_level,
                anomaly_reasons=anomaly_reasons_str,
                comparables_found=fp_result.comparables_found,
                comparables_used=fp_result.comparables_used,
                min_comparable_price=fp_result.min_price,
                max_comparable_price=fp_result.max_price,
                median_comparable_price=fp_result.median_price,
                p25_comparable_price=fp_result.p25_price,
                pricing_status=fp_result.pricing_status,
                is_dominated=is_dominated,
                dominated_by_listing_id=dom_result.dominated_by_id if dom_result else None,
                dominance_reason=dom_result.dominance_reason if dom_result else None,
                comparable_level=comp_result.level_used,
                currency_used=currency,
                # Local rank
                local_price_rank=local_rank.local_price_rank,
                local_group_size=local_rank.local_group_size,
                local_price_percentile=local_rank.local_price_percentile,
                is_top_local_price_1=local_rank.is_top_local_price_1,
                is_top_local_price_3=local_rank.is_top_local_price_3,
                # Freshness
                freshness_bucket=freshness.bucket,
                freshness_boost=freshness.boost,
                days_on_market=days_on_market,
                # Price history
                initial_price=history.initial_price,
                current_price=history.current_price,
                price_change_count=history.price_change_count,
                markdown_abs=history.markdown_abs,
                markdown_pct=history.markdown_pct,
                markdown_bonus=priority.markdown_bonus,
                # Priority score breakdown
                price_edge_score=priority.price_edge_score,
                local_rank_bonus=priority.local_rank_bonus,
                dominance_penalty=priority.dominance_penalty,
                anomaly_penalty=priority.anomaly_penalty,
                final_priority_score=priority.final_priority_score,
                final_priority_level=priority.final_priority_level,
            )

            # Contadores
            summary.total_analyzed += 1
            model_counter[model] += 1

            if fp_result.pricing_status == "enough_data":
                summary.total_enough_data += 1
            elif fp_result.pricing_status == "insufficient_data":
                summary.total_insufficient_data += 1
            elif fp_result.pricing_status == "no_data":
                summary.total_no_data += 1

            if opp_result.opportunity_level == "strong_opportunity":
                summary.total_strong += 1
            elif opp_result.opportunity_level == "medium_opportunity":
                summary.total_medium += 1
            else:
                summary.total_not_opportunity += 1

            if is_dominated:
                summary.total_dominated += 1

            if anomaly.risk_level == "alto":
                summary.total_high_risk += 1

            # Fase 4.2 counters
            if priority.final_priority_level == "urgent_review":
                summary.total_urgent_review += 1
            elif priority.final_priority_level == "high_priority":
                summary.total_high_priority += 1
            elif priority.final_priority_level == "medium_priority":
                summary.total_medium_priority += 1
            else:
                summary.total_low_priority += 1

            if local_rank.is_top_local_price_1:
                summary.total_top_local_1 += 1
            if history.has_markdown and history.markdown_pct is not None \
                    and history.markdown_pct <= -priority_config.markdown_significant_pct:
                summary.total_markdown += 1

        except Exception as e:
            logger.error("Error en pricing de listing id=%d: %s", listing_id, e)
            summary.total_errors += 1
            try:
                save_pricing_analysis(
                    conn=conn, listing_id=listing_id,
                    published_price=listing.get("price"), fair_price=None,
                    gap_pct=None, opportunity_level=None,
                    anomaly_risk="alto", anomaly_reasons="processing_error",
                    comparables_found=0, comparables_used=0,
                    min_comparable_price=None, max_comparable_price=None,
                    median_comparable_price=None, p25_comparable_price=None,
                    pricing_status="error", notes=str(e)[:200],
                    final_priority_level="low_priority",
                    final_priority_score=0.0,
                )
            except Exception:
                logger.error("No se pudo persistir error para listing id=%d", listing_id)

    summary.models_analyzed = dict(model_counter)
    return summary
