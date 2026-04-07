# Proyecto: Car Opportunity Bot

## Objetivo
Construir un sistema local, gratuito y mantenible que detecte oportunidades de compra en publicaciones de autos usados de Mercado Libre dentro de un segmento muy acotado, usando reglas de pricing por comparables y alertas por Telegram.

## Contexto del negocio
El proyecto apunta a reemplazar parte de la búsqueda manual que hacen agencieros para detectar autos que están publicados por debajo de su precio de mercado.

El foco inicial NO es hacer un scraper masivo ni una app visual compleja. El foco es construir un motor confiable de detección de oportunidades.

## Alcance del MVP
Fuente inicial:
- Mercado Libre

Segmento:
- Hatchbacks básicos entre 2010 y 2015
- Modelos permitidos:
  - Gol Trend
  - Clio / Clio Mio
  - Fiat Punto
  - Ford Ka
  - Chevrolet Celta

Restricciones:
- kilometraje máximo: 110000 km
- comparación solo con autos del mismo modelo normalizado
- comparación solo con autos con diferencia máxima de 15000 km
- cantidad de dueños no se usa como criterio excluyente
- frecuencia de ejecución: cada 30 minutos
- entorno local
- stack gratuito

## Principios de diseño
1. Priorizar robustez, simplicidad e interpretabilidad.
2. No sobreingenierizar el MVP.
3. Evitar frontend complejo en las primeras fases.
4. Mantener módulos desacoplados.
5. Toda lógica sensible de negocio debe poder configurarse por archivos YAML o variables de entorno.
6. El sistema debe ser fácil de extender a nuevas fuentes o nuevos segmentos más adelante.
7. El proyecto debe ser entendible por un humano sin depender de magia implícita.

## Regla principal de oportunidad
Un auto se considera oportunidad si:
- pertenece al segmento permitido
- tiene año entre 2010 y 2015
- tiene hasta 110000 km
- el modelo fue reconocido y normalizado correctamente
- existen comparables suficientes del mismo modelo normalizado
- los comparables tienen diferencia máxima de 15000 km
- el precio publicado está por debajo del fair price estimado por un umbral configurable
- el riesgo de anomalía no es alto

## Pricing
- fair price = mediana de precios de comparables válidos
- gap_pct = ((precio_publicado - fair_price) / fair_price) * 100

Umbrales iniciales:
- oportunidad fuerte: gap <= -12
- oportunidad media: gap <= -8
- no alertar si gap > -8

## Riesgo de anomalía
Debe existir una clasificación simple:
- bajo
- medio
- alto

Criterio inicial sugerido:
- bajo: 8 o más comparables válidos y sin inconsistencias fuertes
- medio: entre 5 y 7 comparables o alguna inconsistencia menor
- alto: menos de 5 comparables, datos dudosos, o gap extremo sospechoso

No se debe alertar si el riesgo es alto.

## Requerimientos técnicos
Lenguaje:
- Python 3.11+

Librerías esperadas:
- playwright
- pydantic
- python-dotenv
- PyYAML
- requests
- sqlite3 estándar
- pandas opcional si realmente aporta
- pytest

Base de datos:
- SQLite

Notificaciones:
- Telegram Bot API

Scheduler:
- script local + Task Scheduler de Windows

## Restricciones importantes
1. No introducir Docker en esta primera fase salvo que sea estrictamente necesario.
2. No introducir frontend web en la primera fase.
3. No introducir machine learning avanzado en la primera fase.
4. No usar OCR.
5. No asumir que el HTML de Mercado Libre será estable.
6. No hardcodear reglas del negocio dentro de múltiples archivos si pueden centralizarse en configs YAML.
7. No mezclar scraping, parsing, pricing y notificaciones en un solo archivo.
8. No crear una arquitectura enterprise innecesaria.
9. No usar dependencias raras si la librería estándar alcanza.

## Estándares de código
- Código claro y modular.
- Tipado con type hints.
- Docstrings breves donde aporten.
- Manejo explícito de errores.
- Logging consistente.
- Evitar funciones gigantes.
- Evitar archivos monolíticos.
- Mantener nombres descriptivos.
- Crear tests para piezas críticas.
- No dejar TODOs vacíos sin contexto.

## Estructura objetivo del proyecto
car_opportunity_bot/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── scheduler.py
│   ├── collectors/
│   ├── parsers/
│   ├── filters/
│   ├── pricing/
│   ├── risk/
│   ├── notifications/
│   ├── storage/
│   └── utils/
├── configs/
│   ├── segment_rules.yaml
│   ├── thresholds.yaml
│   └── model_aliases.yaml
├── data/
│   ├── raw/
│   ├── processed/
│   └── exports/
├── scripts/
│   ├── run_once.py
│   ├── init_db.py
│   └── setup_local_env.ps1
├── tests/
├── .env.example
├── requirements.txt
├── README.md
└── CLAUDE.md

## Fase actual
Estamos en el arranque del proyecto.

La tarea actual es implementar Fase 0 y Fase 1:
- estructura inicial del repositorio
- configuración
- logging
- base de datos SQLite
- archivos de configuración YAML
- scripts de inicialización
- documentación mínima
- base lista para que luego se conecte el scraper

NO implementar todavía:
- scraper real
- parser HTML real
- Telegram real
- scheduler recurrente real
- lógica de pricing completa

## Entregables esperados en esta fase
1. Estructura de carpetas completa.
2. requirements.txt razonable y sin exceso.
3. .env.example claro.
4. README.md útil con pasos de uso.
5. config.py para cargar env y rutas.
6. logger.py reutilizable.
7. schema.sql con tablas base.
8. database.py para conexión SQLite.
9. repositories.py con operaciones mínimas.
10. scripts/init_db.py funcional.
11. configs YAML iniciales.
12. tests básicos de carga de config y DB.
13. main.py con smoke test del sistema.

## Criterios de calidad de la entrega
- Debe correr localmente sin depender de servicios pagos.
- Debe ser fácil de leer y extender.
- Debe dejar listo el proyecto para que la siguiente fase implemente scraping.
- Si falta una decisión menor, tomar una decisión razonable y documentarla.
- No pedir confirmación por cada detalle; avanzar con criterio técnico.

## Forma de trabajar
Cuando implementes:
1. Primero crear archivos y estructura.
2. Después completar contenido mínimo funcional.
3. Después revisar consistencia de imports, rutas y ejecución.
4. Después proponer los siguientes pasos.

## Qué espero de vos
Quiero que actúes como lead engineer práctico:
- tomá decisiones razonables
- evitá complejidad innecesaria
- dejá el proyecto ordenado
- explicá brevemente las decisiones importantes
- entregá código y archivos listos para usar