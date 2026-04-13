# AutoFinder - Car Opportunity Bot

Bot local que detecta oportunidades de compra de autos usados en publicaciones de Mercado Libre Argentina. Compara precios contra el mercado usando medianas de comparables y alerta por Telegram cuando encuentra autos subvaluados.

## Stack

- **Python 3.11+**
- **Playwright** - scraping de Mercado Libre (Chromium headless)
- **SQLite** - base de datos local
- **Pydantic** - validacion de configuracion
- **PyYAML** - archivos de reglas de negocio
- **python-dotenv** - variables de entorno
- **pytest** - tests

## Segmento inicial

| Parametro | Valor |
|---|---|
| Modelos | Gol Trend, Clio Mio, Fiat Punto, Ford Ka, Chevrolet Celta |
| Anios | 2010 - 2015 |
| Km maximo | 110.000 |
| Delta km comparables | 15.000 |
| Gap fuerte | <= -12% |
| Gap medio | <= -8% |

## Estructura del proyecto

```
autofinder/
├── app/
│   ├── main.py                        # Smoke test del sistema
│   ├── config.py                      # Carga de .env y configs YAML
│   ├── collectors/
│   │   ├── browser.py                 # Playwright browser manager
│   │   ├── selectors.py               # Selectores CSS centralizados
│   │   ├── mercadolibre_search.py     # Busqueda en ML
│   │   ├── mercadolibre_detail.py     # Extraccion de detalle
│   │   └── search_prioritizer.py      # Priorizacion y balance de resultados
│   ├── parsers/
│   │   ├── listing_parser.py          # Parser de datos de publicaciones
│   │   ├── text_normalizer.py         # Limpieza de texto, precios, km
│   │   └── model_mapper.py            # Mapping de modelos por aliases
│   ├── filters/
│   │   ├── segment_filter.py          # Validacion contra reglas del segmento
│   │   ├── duplicate_filter.py        # Deteccion heuristica de duplicados
│   │   └── financing_detector.py      # Deteccion de anticipo/financiamiento
│   ├── pricing/
│   │   ├── comparable_finder.py       # Busqueda de comparables en SQLite
│   │   ├── outlier_filter.py          # Filtro IQR de precios extremos
│   │   ├── fair_price.py              # Calculo de fair price por mediana
│   │   ├── opportunity_score.py       # Gap y clasificacion de oportunidad
│   │   └── dominance_checker.py      # Regla de dominancia
│   ├── risk/
│   │   └── anomaly_detector.py        # Clasificacion de riesgo de anomalia
│   ├── pipeline/
│   │   ├── normalize_listings.py      # Pipeline de normalizacion
│   │   └── run_pricing.py             # Pipeline de pricing
│   ├── notifications/                 # (Fase 5) Alertas Telegram
│   ├── storage/
│   │   ├── schema.sql                 # DDL de tablas
│   │   ├── database.py                # Conexion SQLite
│   │   └── repositories.py            # Operaciones sobre tablas
│   └── utils/
│       └── logger.py                  # Logger reutilizable
├── configs/
│   ├── segment_rules.yaml             # Reglas de segmento
│   ├── thresholds.yaml                # Umbrales de oportunidad, riesgo y pricing
│   ├── model_aliases.yaml             # Aliases para normalizar modelos
│   └── scraping.yaml                  # Queries y config de scraping
├── data/                              # DB y exports (gitignored)
├── scripts/
│   ├── init_db.py                     # Inicializar base de datos
│   ├── run_once.py                    # Ejecutar un ciclo de scraping
│   ├── process_normalization.py       # Ejecutar normalizacion
│   ├── run_pricing.py                 # Ejecutar pricing
│   └── setup_local_env.ps1            # Setup automatico (Windows)
├── tests/
│   ├── conftest.py                    # Fixtures compartidos
│   ├── test_config.py                 # Tests de configuracion
│   ├── test_database.py               # Tests de base de datos
│   ├── test_parsers.py                # Tests de parsing de texto
│   ├── test_model_mapper.py           # Tests de mapping de modelos
│   ├── test_filters.py                # Tests de filtros de segmento y dedup
│   ├── test_pricing.py                # Tests de pricing, gap, riesgo
│   └── test_repositories.py           # Tests de persistencia
├── .env.example
├── requirements.txt
└── CLAUDE.md
```

## Instalacion local

### Opcion 1: Setup automatico (Windows PowerShell)

```powershell
.\scripts\setup_local_env.ps1
```

### Opcion 2: Manual

```bash
# 1. Crear virtual environment
python -m venv .venv

# 2. Activar (Windows PowerShell)
.\.venv\Scripts\Activate.ps1

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Instalar navegador de Playwright
playwright install chromium

# 5. Crear archivo .env
copy .env.example .env

# 6. Inicializar base de datos
python -m scripts.init_db

# 7. Smoke test
python -m app.main
```

## Comandos principales

```bash
# Inicializar DB
python -m scripts.init_db

# Smoke test (verifica config + DB)
python -m app.main

# Ejecutar una corrida de scraping
python -m scripts.run_once

# Normalizar listings scrapeados
python -m scripts.process_normalization

# Ejecutar pricing y deteccion de oportunidades
python -m scripts.run_pricing

# Tests (185 tests)
pytest tests/ -v
```

## Como funciona la captura de resultados (Fase 2 v3)

### Estrategia: `balanced_low_price`

El bot no toma "los primeros N resultados globales" del search. La seleccion es una estrategia balanceada con foco en precio y deteccion temprana de financiamiento:

1. **Busqueda por query**: cada query del segmento (ej: "gol trend 2010 2015") se ejecuta en ML y se extraen hasta `ML_MAX_RESULTS_PER_QUERY` resultados.
2. **Dedup global**: se descartan listings que ya estan en la DB (no se re-visitan).
3. **Deteccion de financiamiento en preview**: se analiza el titulo del search contra patrones conocidos (anticipo, cuotas, financiado, credito, solo con dni, etc.). Los previews financieros se marcan con `is_financing_preview=True`:
   - Con `EXCLUDE_FINANCING_PREVIEWS=true` → se excluyen del lote directamente.
   - Con `DEPRIORITIZE_FINANCING_PREVIEWS=true` → quedan al final de la cola (penalty de -100 en score).
4. **Score de priorizacion por preview** (`preview_priority_score`):
   - Base: 50 puntos
   - Penalidad por financiamiento: -100 (si no fue excluido y `deprioritize=true`)
   - Penalidad por precio no parseable: -30
   - Bonus por precio relativo dentro de la query: 0 a +50 (el mas barato de la query obtiene +50, el mas caro +0)
   - Score mas alto = mayor prioridad para entrar al detalle
5. **Ordenamiento por score**: cada query se ordena por score descendente (con tie-break por precio asc y posicion en search).
6. **Minimo garantizado por query**: cada query recibe al menos `MIN_DETAILS_PER_QUERY` slots.
7. **Cap por query**: ninguna query puede exceder `ML_MAX_DETAILS_PER_QUERY`.
8. **Reparto round-robin**: el presupuesto restante se reparte entre queries que aun tengan cupo.

### Por que importa

Un preview con titulo "Gol Trend anticipo y cuotas $500.000" puede parecer baratisimo, pero el precio no es real. Sin deteccion temprana, estos avisos consumen cupo que podria usarse para un aviso genuinamente barato. La Fase 2 v3 resuelve esto antes de gastar tiempo en el detalle.

### Metadata de search persistida

Por cada listing nuevo se guarda en la tabla `listings`:

| Columna | Descripcion |
|---|---|
| `search_query` | Query exacta que descubrio el listing |
| `search_position` | Posicion en la pagina de resultados (1-based) |
| `search_page` | Pagina de resultados (1 por ahora) |
| `preview_price` | Precio visto en el search (puede diferir del detalle) |
| `preview_currency` | Moneda detectada en el preview |
| `preview_financing_flag` | 1 si el titulo del preview tiene seniales de financiamiento |
| `preview_priority_score` | Score numerico que determino la prioridad de seleccion |
| `selected_for_detail` | 1 si fue seleccionado para visitar el detalle |
| `extraction_timestamp` | Cuando se extrajo |

Esto permite **auditar por que un aviso entro o no entro al lote de detalle**.

### Auditoria de cobertura y seleccion

```sql
-- Que queries trajeron que y con que score
SELECT search_query, count(*) as listings,
       avg(preview_priority_score) as avg_score,
       sum(preview_financing_flag) as financieros,
       sum(selected_for_detail) as seleccionados
FROM listings
WHERE search_query IS NOT NULL
GROUP BY search_query;

-- Avisos que NO fueron seleccionados (para ver que se perdio)
SELECT source_id, title, preview_price, preview_priority_score, preview_financing_flag
FROM listings
WHERE selected_for_detail = 0
ORDER BY preview_priority_score DESC;
```

### Variables de configuracion

| Variable | Default | Descripcion |
|---|---|---|
| `ML_MAX_RESULTS_PER_QUERY` | 48 | Resultados a extraer por query |
| `ML_MAX_DETAIL_PAGES_PER_RUN` | 120 | Maximo total de detalles por corrida |
| `ML_MAX_DETAILS_PER_QUERY` | 30 | Cap por query |
| `MIN_DETAILS_PER_QUERY` | 5 | Minimo garantizado por query |
| `PRIORITIZE_LOWEST_PRICE_FIRST` | true | Ordenar por menor precio |
| `DEPRIORITIZE_FINANCING_PREVIEWS` | true | Penalizar financieros en score |
| `EXCLUDE_FINANCING_PREVIEWS` | false | Excluir financieros del lote |
| `ENABLE_PREVIEW_PRIORITY_SCORE` | true | Calcular score numerico |
| `SEARCH_SELECTION_STRATEGY` | balanced_low_price | Estrategia de seleccion |

## Como funciona el pricing (Fase 4 v2)

### Tratamiento de moneda

Los comparables se buscan **solo dentro de la misma moneda**. Un listing en ARS se compara solo con otros en ARS; uno en USD solo con otros en USD. No se hace conversion de moneda porque el tipo de cambio en el mercado de autos usados no es lineal ni estable.

### Exclusion de publicaciones de financiamiento

Antes de analizar pricing, cada listing se evalua contra patrones de financiamiento:

- **Anticipo**: "anticipo", "entrega y cuotas", "solo con dni"
- **Cuotas**: "cuota", "cuotas", "financiado", "financiacion", "credito"
- **Plan**: "plan de ahorro", "saldo financiado"

Si el titulo indica que el precio publicado es un anticipo o cuota (no precio total), el listing se marca como `is_total_price_confident = false` y se **excluye del pricing**. Tambien se excluye como comparable de otros listings.

### Busqueda de comparables por niveles

Los comparables se clasifican en dos niveles de similitud:

| Nivel | Anio | Km | Uso |
|---|---|---|---|
| **A** (estricto) | ±1 anio | ±15.000 km | Preferido si hay >= 3 comparables |
| **B** (relajado) | ±2 anios | ±20.000 km | Fallback si nivel A tiene < 3 |

El sistema intenta usar **solo nivel A**. Si no hay suficientes, combina A + B. Esto le da mas peso al anio del auto (un 2013 con 80k km no es lo mismo que un 2011 con 80k km).

### Fair price

El **fair price** es la **mediana** de los precios de comparables validos:

1. Se buscan listings del **mismo modelo normalizado y misma moneda**
2. Se excluyen listings de **financiamiento/anticipo**
3. Se clasifican por **nivel A o B** segun diferencia de anio y km
4. Se excluyen **outliers** usando IQR (Interquartile Range)
5. Se calcula la **mediana** de los precios restantes

### Gap porcentual

```
gap_pct = ((precio_publicado - fair_price) / fair_price) * 100
```

Un gap **negativo** significa que el auto esta publicado **por debajo** del mercado.

### Regla de dominancia

Un listing es **dominado** cuando existe otro comparable que es objetivamente mejor en todos los aspectos:

- **Mismo anio o mas nuevo**
- **Menos km** (con margen minimo de 3.000 km de ventaja)
- **Precio igual o menor** (con tolerancia de 5%)

Si un listing esta dominado, se degrada a `not_opportunity` aunque su gap sea favorable. Esto evita falsos positivos como: un Gol Trend 2011 con 95k km a US$8.000 no es oportunidad si hay un 2012 con 85k km a US$7.500.

### Clasificacion de oportunidad

| Nivel | Condicion | Significado |
|---|---|---|
| `strong_opportunity` | gap <= -12% y no dominado | Precio significativamente debajo del mercado |
| `medium_opportunity` | gap <= -8% y no dominado | Precio algo debajo del mercado |
| `not_opportunity` | gap > -8% o dominado | Precio a valor de mercado, por encima, o dominado |

### Riesgo de anomalia

Evalua si el resultado del pricing es confiable:

| Nivel | Significado |
|---|---|
| `bajo` | 8+ comparables, sin inconsistencias |
| `medio` | 5-7 comparables o alguna inconsistencia menor |
| `alto` | < 5 comparables, gap extremo, datos faltantes |

Razones posibles: `insufficient_comparables`, `extreme_gap`, `wide_price_dispersion`, `missing_key_fields`, `too_few_after_outlier`.

### Filtro de outliers (IQR)

Se usa IQR porque es simple, robusto y no asume distribucion normal. Un precio es outlier si:

```
precio < Q1 - 1.5 * IQR
precio > Q3 + 1.5 * IQR
```

El factor 1.5 es configurable en `configs/thresholds.yaml`.

## Configuracion

### Variables de entorno (.env)

| Variable | Default | Descripcion |
|---|---|---|
| `DATABASE_PATH` | `data/autofinder.db` | Ruta a la DB SQLite |
| `LOG_LEVEL` | `INFO` | Nivel de logging |
| `HEADLESS` | `true` | Navegador sin ventana visible |
| `ML_MAX_RESULTS_PER_QUERY` | `48` | Max resultados a extraer por query del search |
| `ML_MAX_DETAIL_PAGES_PER_RUN` | `120` | Max paginas de detalle por corrida (presupuesto total) |
| `ML_MAX_DETAILS_PER_QUERY` | `30` | Max detalles a visitar por query (balance) |
| `MIN_DETAILS_PER_QUERY` | `5` | Minimo garantizado de detalles por query |
| `PRIORITIZE_LOWEST_PRICE_FIRST` | `true` | Priorizar menor precio dentro de cada query |
| `ENABLE_SEARCH_POSITION_CAPTURE` | `true` | Capturar metadata de search para auditoria |
| `SCRAPE_DELAY_SECONDS` | `2` | Pausa entre requests |
| `BROWSER_TIMEOUT_MS` | `30000` | Timeout del navegador |
| `USER_AGENT` | *(vacio)* | User agent personalizado |
| `PRICING_BATCH_SIZE` | `200` | Listings a analizar por lote |
| `ENABLE_OUTLIER_FILTERING` | `true` | Filtro IQR de outliers |
| `ENABLE_FINANCING_FILTER` | `true` | Deteccion y exclusion de financiamiento |
| `ENABLE_DOMINANCE_RULE` | `true` | Regla de dominancia |
| `NORMALIZATION_BATCH_SIZE` | `200` | Listings a normalizar por lote |
| `ENABLE_HEURISTIC_DEDUP` | `true` | Deteccion de duplicados |
| `ALLOW_AMBIGUOUS_MODELS` | `false` | Matching de modelos ambiguos |

### Parametros de alertas (.env)

| Variable | Default | Descripcion |
|---|---|---|
| `TELEGRAM_ENABLED` | `true` | Activar/desactivar envío real |
| `TELEGRAM_BOT_TOKEN` | `` | Token del bot (@BotFather) |
| `TELEGRAM_CHAT_ID` | `` | ID del chat destino |
| `ALERT_PRIORITY_LEVELS` | `urgent_review,high_priority` | Niveles que disparan alerta |
| `ALERT_CHANNEL` | `telegram` | Canal de envío |
| `ALERT_RESEND_ON_PRICE_CHANGE` | `true` | Reenviar si baja el precio |
| `ALERT_RESEND_ON_PRIORITY_UPGRADE` | `true` | Reenviar si sube de prioridad |
| `ALERT_RESEND_ON_OPPORTUNITY_UPGRADE` | `true` | Reenviar si sube de oportunidad |
| `ALERT_DRY_RUN` | `false` | Simular sin enviar a Telegram |

### Parametros de pricing (configs/thresholds.yaml)

| Parametro | Default | Descripcion |
|---|---|---|
| `min_comparables` | `3` | Minimo para analisis confiable |
| `extreme_gap_pct` | `-30` | Gap sospechoso que levanta alerta |
| `iqr_factor` | `1.5` | Factor IQR para filtro de outliers |
| `max_cv` | `0.40` | CV maximo antes de alertar dispersion |

### Parametros de comparables (configs/thresholds.yaml)

| Parametro | Default | Descripcion |
|---|---|---|
| `level_a_max_year_diff` | `1` | Diferencia maxima de anio (nivel A) |
| `level_a_max_km_diff` | `15000` | Diferencia maxima de km (nivel A) |
| `level_b_max_year_diff` | `2` | Diferencia maxima de anio (nivel B) |
| `level_b_max_km_diff` | `20000` | Diferencia maxima de km (nivel B) |
| `min_comparables_level_a` | `3` | Minimo para usar solo nivel A |

### Parametros de dominancia (configs/thresholds.yaml)

| Parametro | Default | Descripcion |
|---|---|---|
| `price_tolerance_pct` | `5.0` | Tolerancia de precio para dominar (%) |
| `min_km_advantage` | `3000` | Ventaja minima de km para dominar |

## Tablas SQLite

| Tabla | Uso |
|---|---|
| `listings` | Publicaciones unicas con datos normalizados |
| `listing_snapshots` | Historico de precio/km por corrida |
| `pricing_analyses` | Resultados de pricing por listing |
| `opportunity_alerts` | Oportunidades detectadas (legacy) |
| `sent_alerts` | Historial de alertas enviadas por Telegram (Fase 5) |
| `run_logs` | Registro de cada ejecucion del bot |

## Priorizacion operativa (Fase 4.2)

La Fase 4 v2 responde a la pregunta **"este auto esta barato vs el mercado?"** mediante `opportunity_level`. La Fase 4.2 agrega una capa distinta: **"cual conviene mirar primero?"** mediante `final_priority_level`.

Son dos conceptos separados y ambos se persisten:

| Campo | Pregunta que responde | Valores |
|---|---|---|
| `opportunity_level` | Esta barato vs fair price? | `strong_opportunity` / `medium_opportunity` / `not_opportunity` |
| `final_priority_level` | Conviene mirarlo ya? | `urgent_review` / `high_priority` / `medium_priority` / `low_priority` |

Un auto puede ser `medium_opportunity` pero `urgent_review` si es el mas barato de su microgrupo real + recien publicado. Inversamente, un `strong_opportunity` dominado por otro comparable cae a `medium_priority`.

### Senales que alimentan el score

1. **Price edge** (`price_edge_score`): magnitud del descuento (`-gap_pct`), capada en `price_edge_cap` (default 40).
2. **Local rank** (`local_rank_bonus`): ranking dentro del **microgrupo estricto** (mismo modelo, anio ±1, km ±15000, misma moneda). Si el microgrupo tiene al menos `local_min_group_size` listings:
   - top 1 del microgrupo → `local_top1_bonus` (default 30)
   - top 3 del microgrupo → `local_top3_bonus` (default 15)
3. **Freshness boost** (`freshness_boost`): segun `first_seen_at`:
   - 0-1 dias → `freshness_1d_boost` (default 25)
   - 1-3 dias → `freshness_3d_boost` (default 15)
   - 3-7 dias → `freshness_7d_boost` (default 5)
   - \>7 dias → 0
4. **Markdown bonus** (`markdown_bonus`): si `listing_snapshots` muestra una rebaja de al menos `markdown_significant_pct` (default 3%) vs el precio inicial, suma `markdown_bonus` (default 20).
5. **Dominance penalty** (`-dominance_penalty`): si esta dominado por otro comparable, resta `dominance_penalty` (default 40).
6. **Anomaly penalty** (`-anomaly_high_penalty`): si `anomaly_risk == "alto"`, resta `anomaly_high_penalty` (default 25).

### Formula

```
final_priority_score =
    price_edge_score
  + local_rank_bonus
  + freshness_boost
  + markdown_bonus
  - dominance_penalty
  - anomaly_penalty
```

### Mapeo a nivel

```
score >= urgent_review_threshold  (default 70) → urgent_review
score >= high_priority_threshold  (default 45) → high_priority
score >= medium_priority_threshold(default 20) → medium_priority
else                                           → low_priority
```

### Gates de seguridad (criticos)

- Un listing **dominado NUNCA** puede ser `urgent_review`. Se degrada a `high_priority`.
- Un listing con `anomaly_risk == "alto"` **NUNCA** puede ser `urgent_review`. Se degrada a `high_priority`.
- Un dominado con score borderline en `high_priority` se degrada un escalon mas a `medium_priority`.

La idea es que `urgent_review` sea una bandera operativa confiable: si esta en la lista, hay que mirarlo ahora.

### Historial de precio

`price_history.py` lee `listing_snapshots` para calcular:
- `initial_price` / `current_price`
- `price_change_count` (cantidad de cambios detectados entre snapshots)
- `markdown_abs` / `markdown_pct`
- `days_on_market` (fallback si no hay `first_seen_at`)

Esto permite detectar vendedores que rebajan activamente el precio, que historicamente son mejores candidatos.

### Persistencia

Todo el desglose se guarda en `pricing_analyses`:
- `local_price_rank`, `local_group_size`, `local_price_percentile`, `is_top_local_price_1/3`
- `freshness_bucket`, `freshness_boost`, `days_on_market`
- `initial_price`, `current_price`, `price_change_count`, `markdown_abs`, `markdown_pct`
- `price_edge_score`, `local_rank_bonus`, `dominance_penalty`, `anomaly_penalty`
- `final_priority_score`, `final_priority_level`

Esto permite auditar **por que** cada listing termino en un nivel dado.

## Alertas por Telegram (Fase 5)

### Como configurar

1. Crear un bot con [@BotFather](https://t.me/BotFather) y obtener el token.
2. Obtener tu `chat_id` (enviar un mensaje al bot y usar `https://api.telegram.org/bot<TOKEN>/getUpdates`).
3. Configurar en `.env`:
   ```
   TELEGRAM_ENABLED=true
   TELEGRAM_BOT_TOKEN=tu_token_aqui
   TELEGRAM_CHAT_ID=tu_chat_id_aqui
   ```
4. Ejecutar: `python -m scripts.run_alerts`

### Reglas de envio

Solo se alertan listings que cumplan **todas** estas condiciones:
- `is_active = 1` (no deslistado)
- `is_valid_segment = 1` (pasa filtros de segmento)
- `duplicate_of IS NULL` (no es duplicado)
- `is_financing = 0` (no es anticipo/cuotas)
- `pricing_status = 'enough_data'` (tiene pricing confiable)
- `final_priority_level` en los niveles configurados (default: `urgent_review`, `high_priority`)

### Deduplicacion

El sistema NO reenvía el mismo auto si no cambió nada relevante.

**Fingerprint**: combinación de `listing_id + price + opportunity_level + final_priority_level`.

Regla:
- Si el fingerprint no cambió → no reenviar (`duplicate`)
- Si el precio bajó → reenviar (`price_drop`)
- Si subió de prioridad (ej: high → urgent) → reenviar (`priority_upgrade`)
- Si subió de oportunidad (ej: medium → strong) → reenviar (`opportunity_upgrade`)
- Si no hay historial previo → enviar (`new_match`)

Cada regla de reenvío es desactivable via `.env`.

### Modo dry_run

Con `ALERT_DRY_RUN=true` o `python -m scripts.run_alerts --dry-run`:
- No se envía nada a Telegram
- Se loguea qué se habría enviado
- Se persiste el intento como `is_dry_run=1` en `sent_alerts`
- Útil para validar la lógica antes de activar envío real

### Formato del mensaje

```
🚗 AUTO FINDER — 🆕 Nuevo match

Gol Trend 1.6 Pack I 2015
Precio: 4.000.000 ARS
Año: 2015  |  Km: 95.000

🟢 Opportunity: strong_opportunity
🔴 Priority: urgent_review
Score: 74.5
Fair price: 4.600.000 ARS
Gap: -13.0%
Freshness: 0-1d

https://auto.mercadolibre.com.ar/MLA-123
```

### Tabla sent_alerts

| Columna | Descripcion |
|---|---|
| `listing_id` | Listing alertado |
| `sent_at` | Timestamp del envío |
| `channel` | Canal (`telegram`) |
| `telegram_chat_id` | Chat destino |
| `message_fingerprint` | Hash para dedup |
| `sent_price` / `sent_currency` | Estado al momento del envío |
| `sent_opportunity_level` | Oportunidad al momento |
| `sent_final_priority_level` | Prioridad al momento |
| `sent_final_priority_score` | Score al momento |
| `send_status` | `sent` / `failed` / `pending` |
| `send_error` | Detalle del error si falló |
| `alert_reason` | `new_match` / `price_drop` / `priority_upgrade` / `opportunity_upgrade` |
| `is_dry_run` | 1 si fue simulación |

### Auditoria de alertas

```sql
-- Historial de alertas por listing
SELECT l.title, sa.alert_reason, sa.sent_price, sa.sent_final_priority_level,
       sa.send_status, sa.sent_at
FROM sent_alerts sa
JOIN listings l ON l.id = sa.listing_id
ORDER BY sa.sent_at DESC;

-- Resumen de alertas por razón
SELECT alert_reason, send_status, count(*) as total
FROM sent_alerts
GROUP BY alert_reason, send_status;
```

## Limitaciones actuales (Captura v3 + Fase 4 v2 + Fase 4.2 + Fase 5)

- Los selectores CSS pueden dejar de funcionar si ML cambia su HTML.
- No se implementa paginacion de resultados (solo primera pagina por query). El balance entre queries mejora la cobertura, pero no reemplaza paginar.
- La priorizacion por precio depende de que el preview tenga precio parseable. Listings con precio en formato raro caen al final (penalty de -30 en score, pero no se excluyen).
- La deteccion de financiamiento en preview usa los mismos patrones regex que `financing_detector.py`. Solo analiza el titulo del search. Si el titulo no menciona "anticipo" o "cuotas", el financiamiento pasa desapercibido hasta el detalle.
- El `preview_priority_score` usa pesos fijos (base 50, penalty 100/30, bonus hasta 50). Si el balance resulta inadecuado, hay que ajustar las constantes en `search_prioritizer.py`.
- `search_query` y `search_position` se persisten solo la **primera vez** que entra un listing. Si el mismo listing aparece en otra query mas tarde, no se sobreescribe.
- El minimo por query no se "fuerza": si una query trae menos resultados que `MIN_DETAILS_PER_QUERY`, se toman los que haya y listo.
- El pricing necesita volumen: con pocos listings scrapeados, los resultados son limitados.
- No hay scheduler automatico todavia.
- **Fase 5**: las alertas dependen de que el pricing se haya ejecutado antes (`run_pricing`). Si no hay `pricing_analyses`, no hay elegibles.
- **Fase 5**: el fingerprint no incluye `fair_price` ni `gap_pct`, asi que un cambio en los comparables (que mueva el fair price) sin cambio de precio/level no dispara reenvio. Esto es intencional para reducir ruido.
- **Fase 5**: si Telegram falla (timeout, API error), el listing queda como `send_status='failed'` pero no se reintenta automaticamente. En la proxima corrida se evaluara de nuevo.
- **Fase 5**: no hay rate limiting contra la API de Telegram. Con lotes chicos (<50 alertas) no es problema, pero con volumen alto podria pegarse al limite de 30 msgs/seg.
- **Fase 5**: solo soporta un canal (Telegram) y un chat destino. No soporta multiples chats ni otros canales.
- No se cruzan comparables entre modelos distintos.
- La confianza del match de modelo no se usa como peso en el pricing.
- No hay migracion automatica de DB; si cambia el schema hay que recrear.
- No hay conversion ARS/USD: si un modelo solo tiene listings en una moneda, los de la otra quedan sin comparables.
- La deteccion de financiamiento es por regex sobre el titulo; publicaciones que no mencionan "anticipo" o "cuotas" en el titulo pueden pasar desapercibidas.
- La dominancia es conservadora: requiere ventaja en TODOS los ejes (anio, km, precio). Un auto puede ser mejor en dos de tres y no dominar.
- No se pondera la distancia de km entre comparables (un comparable a 1.000 km de diferencia pesa igual que uno a 14.000 km).
- **Fase 4.2**: `local_rank` necesita al menos `local_min_group_size` comparables dentro del microgrupo estricto. Con pocos datos, el bonus de ranking local no se activa.
- **Fase 4.2**: `freshness` depende de `first_seen_at`, que solo es fiable si la captura corre con regularidad. Un listing detectado hoy por primera vez pero publicado hace semanas parece "fresco".
- **Fase 4.2**: `markdown` requiere al menos 2 snapshots del mismo listing. En la primera corrida ningun listing tiene historial.
- **Fase 4.2**: los pesos del score son constantes configurables, no aprendidos. Si el balance resulta mal calibrado en la practica, hay que ajustar `configs/thresholds.yaml` a mano.
- **Fase 4.2**: el microgrupo local usa los comparables ya encontrados por `find_comparables`, que puede haber devuelto nivel B. Si el nivel A tiene menos de `local_min_group_size`, el ranking no se computa aunque haya candidatos del nivel B cerca.

## Decisiones de diseno

- **Mediana sobre promedio**: la mediana es mas robusta ante outliers y muestras chicas.
- **IQR para outliers**: simple, no asume normalidad, funciona con 5-15 datos.
- **Tabla `pricing_analyses` separada**: permite re-analizar sin perder historial.
- **Pipeline idempotente**: solo procesa listings no analizados o re-normalizados.
- **Riesgo por score acumulativo**: cada señal suma puntos, el total define el nivel.
- **Selectores centralizados** en `selectors.py` con fallbacks.
- **Queries en YAML** y no hardcodeadas.
- **Snapshots por corrida** para trackear cambios de precio.
- **Tabla `sent_alerts` separada de `opportunity_alerts`**: `opportunity_alerts` trackea detección, `sent_alerts` trackea envíos con dedup, errores, dry_run. Responsabilidades distintas.
- **Fingerprint sin `fair_price`**: los cambios en comparables (que mueven fair_price/gap) sin cambio de precio/level no disparan reenvío. Reduce ruido en la práctica.
- **Telegram via `requests`**: la Bot API es HTTP puro, no necesita SDK adicional. `requests` ya está en el proyecto.

## Fases

### Fase 0+1: Base tecnica ✅
- Estructura, config, logging, DB, tests basicos

### Fase 2: Scraping + Persistencia ✅ (v3)
- Browser manager, busqueda en ML, extraccion de detalle
- Parsing de precio/km/anio, persistencia con snapshots
- **v2**: priorizacion por menor precio dentro de cada query
- **v2**: balance entre queries con minimo garantizado y cap por query
- **v2**: dedup contra DB para no re-visitar listings
- **v2**: persistencia de metadata de search (query, posicion, preview)
- **v3**: deteccion temprana de financiamiento/anticipo en el preview del search
- **v3**: score numerico auditable (`preview_priority_score`) para decidir que visitar
- **v3**: penalizacion/exclusion configurable de previews financieros
- **v3**: persistencia de `preview_financing_flag`, `preview_priority_score`, `selected_for_detail`
- **v3**: logging detallado de financieros detectados/excluidos y previews con/sin precio

### Fase 3: Normalizacion ✅
- Model mapper con aliases exactos y ambiguos
- Filtros de segmento con motivos de rechazo
- Deduplicacion heuristica conservadora
- Pipeline reproducible de normalizacion

### Fase 4: Pricing + Oportunidades (v2) ✅
- Comparables por niveles A/B con peso en el anio
- Aislamiento de moneda (ARS con ARS, USD con USD)
- Deteccion y exclusion de publicaciones de financiamiento/anticipo
- Regla de dominancia para evitar falsos positivos
- Fair price por mediana con filtro IQR de outliers
- Gap porcentual y clasificacion de oportunidad
- Evaluacion de riesgo de anomalia
- Persistencia de analisis con flags de dominancia, nivel de comparable, moneda

### Fase 4.2: Priorizacion operativa ✅
- Separacion de `opportunity_level` vs `final_priority_level`
- Freshness scoring por buckets (0-1d, 1-3d, 3-7d, >7d)
- Ranking local dentro del microgrupo estricto (anio ±1, km ±15000)
- Historial de precio desde snapshots (markdown, days_on_market)
- Score final auditable con desglose por componente
- Gates de seguridad: dominados y riesgo alto nunca son urgent_review
- Niveles operativos: urgent_review / high_priority / medium_priority / low_priority

### Fase 5: Alertas Telegram ✅
- Integración con Telegram Bot API via `requests`
- Envio de alertas solo para `urgent_review` y `high_priority` (configurable)
- Deduplicacion por fingerprint: no reenvía si no cambió nada relevante
- Reenvío automático por baja de precio, subida de prioridad o de oportunidad
- Persistencia completa en tabla `sent_alerts` (canal, fingerprint, razón, estado)
- Modo `dry_run` para pruebas sin enviar a Telegram
- Mensajes concisos y legibles en móvil con toda la info operativa
- Tests completos con mocks de Telegram
- No rompe el pipeline si Telegram falla

### Pendiente
- Scheduler automatico (Task Scheduler Windows)
- Pipeline integrado scraping -> normalizacion -> pricing -> alertas en un solo comando
