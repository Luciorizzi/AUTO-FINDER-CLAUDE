-- Schema principal de AutoFinder
-- Tablas: listings, listing_snapshots, opportunity_alerts, run_logs

CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL DEFAULT 'mercadolibre',
    source_id TEXT NOT NULL UNIQUE,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    model_raw TEXT,
    model_normalized TEXT,
    brand TEXT,
    year INTEGER,
    km INTEGER,
    price REAL,
    currency TEXT DEFAULT 'ARS',
    location TEXT,
    seller_type TEXT,
    first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
    is_active INTEGER NOT NULL DEFAULT 1,
    -- Campos de normalizacion (Fase 3)
    is_valid_segment INTEGER,
    invalid_reason TEXT,
    duplicate_of INTEGER,
    normalized_at TEXT,
    -- Campos de calidad de precio (Fase 4v2)
    is_financing INTEGER NOT NULL DEFAULT 0,
    is_down_payment INTEGER NOT NULL DEFAULT 0,
    is_total_price_confident INTEGER NOT NULL DEFAULT 1,
    -- Metadata de search (auditoria de cobertura)
    search_query TEXT,
    search_position INTEGER,
    search_page INTEGER DEFAULT 1,
    preview_price REAL,
    preview_currency TEXT,
    extraction_timestamp TEXT,
    FOREIGN KEY (duplicate_of) REFERENCES listings(id)
);

CREATE TABLE IF NOT EXISTS listing_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL,
    price REAL,
    currency TEXT DEFAULT 'ARS',
    km INTEGER,
    captured_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (listing_id) REFERENCES listings(id)
);

CREATE TABLE IF NOT EXISTS opportunity_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL,
    fair_price REAL NOT NULL,
    gap_pct REAL NOT NULL,
    opportunity_level TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    comparables_count INTEGER NOT NULL,
    notified INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (listing_id) REFERENCES listings(id)
);

CREATE TABLE IF NOT EXISTS run_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    listings_found INTEGER DEFAULT 0,
    opportunities_found INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS pricing_analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL,
    analyzed_at TEXT NOT NULL DEFAULT (datetime('now')),
    -- Precios
    published_price REAL,
    fair_price REAL,
    gap_pct REAL,
    -- Clasificacion
    opportunity_level TEXT,
    anomaly_risk TEXT,
    anomaly_reasons TEXT,
    -- Comparables
    comparables_found INTEGER NOT NULL DEFAULT 0,
    comparables_used INTEGER NOT NULL DEFAULT 0,
    min_comparable_price REAL,
    max_comparable_price REAL,
    median_comparable_price REAL,
    p25_comparable_price REAL,
    -- Dominancia
    is_dominated INTEGER NOT NULL DEFAULT 0,
    dominated_by_listing_id INTEGER,
    dominance_reason TEXT,
    -- Comparables metadata
    comparable_level TEXT,
    currency_used TEXT,
    -- Estado
    pricing_status TEXT NOT NULL DEFAULT 'pending',
    notes TEXT,
    FOREIGN KEY (listing_id) REFERENCES listings(id)
);

-- Indices para queries frecuentes
CREATE INDEX IF NOT EXISTS idx_listings_model ON listings(model_normalized);
CREATE INDEX IF NOT EXISTS idx_listings_active ON listings(is_active);
CREATE INDEX IF NOT EXISTS idx_listings_source_id ON listings(source_id);
CREATE INDEX IF NOT EXISTS idx_listings_valid ON listings(is_valid_segment);
CREATE INDEX IF NOT EXISTS idx_listings_duplicate ON listings(duplicate_of);
CREATE INDEX IF NOT EXISTS idx_snapshots_listing ON listing_snapshots(listing_id);
CREATE INDEX IF NOT EXISTS idx_alerts_listing ON opportunity_alerts(listing_id);
CREATE INDEX IF NOT EXISTS idx_pricing_listing ON pricing_analyses(listing_id);
CREATE INDEX IF NOT EXISTS idx_pricing_status ON pricing_analyses(pricing_status);
