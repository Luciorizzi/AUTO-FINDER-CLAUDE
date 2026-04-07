"""Selectores CSS centralizados para Mercado Libre.

Mantener todos los selectores aca para que si ML cambia el layout,
solo haya que tocar un archivo.

Ultima verificacion: 2026-04-01
"""


# --- Pagina de resultados de busqueda ---

SEARCH = {
    # Contenedor de cada resultado individual
    "result_item": "li.ui-search-layout__item",
    # Link + titulo principal dentro de un resultado (poly-card)
    "result_link": "a.poly-component__title",
    # Precio dentro del resultado
    "result_price_amount": "span.andes-money-amount__fraction",
    # Moneda
    "result_price_currency": "span.andes-money-amount__currency-symbol",
    # Ubicacion en resultados
    "result_location": "span.poly-component__location",
    # Atributos (año, km) en resultados
    "result_attrs": "li.poly-attributes_list__item",
}


# --- Pagina de detalle de publicacion ---

DETAIL = {
    # Titulo principal
    "title": "h1.ui-pdp-title",
    # Precio
    "price_amount": "span.andes-money-amount__fraction",
    "price_currency": "span.andes-money-amount__currency-symbol",
    # Subtitulo (contiene año | km | fecha publicacion)
    "subtitle": "span.ui-pdp-subtitle",
    # Tabla de especificaciones (marca, modelo, año, km, puertas, etc)
    "specs_row": "tr.andes-table__row",
    "specs_header": "th",
    "specs_data": "td",
    # Ubicacion (nota: ML a veces muestra avisos en el mismo selector)
    "location": "p.ui-pdp-media__title",
    # Tipo de vendedor
    "seller_info": "[class*=seller]",
}


# --- Selectores alternativos (fallback) ---
# ML cambia el layout seguido, estos son fallbacks comunes

SEARCH_FALLBACK = {
    "result_link": [
        "a.poly-component__title",
        "a.ui-search-link__title-card",
        "a.ui-search-item__group__element",
    ],
    "result_location": [
        "span.poly-component__location",
        "span.ui-search-item__group__element--location",
    ],
    "result_attrs": [
        "li.poly-attributes_list__item",
        "li.ui-search-card-attributes__attribute",
    ],
}


DETAIL_FALLBACK = {
    "title": [
        "h1.ui-pdp-title",
        "h1[class*='title']",
    ],
    "price_amount": [
        "span.andes-money-amount__fraction",
        "span.price-tag-fraction",
    ],
}
