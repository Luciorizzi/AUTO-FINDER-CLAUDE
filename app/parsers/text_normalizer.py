"""Utilidades de limpieza y normalizacion de texto.

Funciones puras para limpiar strings extraidos del HTML.
"""

import re
import unicodedata
from typing import Optional


def clean_text(text: Optional[str]) -> Optional[str]:
    """Limpia espacios extra y caracteres invisibles."""
    if not text:
        return None
    cleaned = re.sub(r"\s+", " ", text.strip())
    return cleaned if cleaned else None


def normalize_text(text: Optional[str]) -> str:
    """Normaliza texto para matching: lowercase, sin tildes, sin chars especiales.

    Ejemplos:
        "Volkswagen Gol Trend 1.6" -> "volkswagen gol trend 1.6"
        "Clio Mío Confort" -> "clio mio confort"
        "FORD KA FLY" -> "ford ka fly"
    """
    if not text:
        return ""
    # Lowercase
    result = text.lower().strip()
    # Remover tildes/acentos
    result = unicodedata.normalize("NFD", result)
    result = "".join(c for c in result if unicodedata.category(c) != "Mn")
    # Remover caracteres especiales excepto letras, numeros, espacios y puntos
    result = re.sub(r"[^a-z0-9\s.]", " ", result)
    # Colapsar espacios
    result = re.sub(r"\s+", " ", result).strip()
    return result


def extract_number(text: Optional[str]) -> Optional[int]:
    """Extrae el primer numero entero de un texto.

    Ejemplos:
        "123.456 km" -> 123456
        "2013" -> 2013
        "$ 3.500.000" -> 3500000
    """
    if not text:
        return None
    cleaned = text.replace(".", "").replace(",", "")
    match = re.search(r"\d+", cleaned)
    return int(match.group()) if match else None


def parse_price(text: Optional[str]) -> Optional[float]:
    """Parsea un precio desde texto a float.

    Maneja formatos argentinos:
        "3.500.000" -> 3500000.0
        "$ 3.500.000" -> 3500000.0
        "U$S 15.000" -> 15000.0
        "3.500.000,50" -> 3500000.50
    """
    if not text:
        return None
    cleaned = re.sub(r"[^\d.,]", "", text)
    if not cleaned:
        return None

    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "," in cleaned:
        parts = cleaned.split(",")
        if len(parts[-1]) == 2:
            cleaned = "".join(parts[:-1]) + "." + parts[-1]
        else:
            cleaned = cleaned.replace(",", "")
    else:
        parts = cleaned.split(".")
        if len(parts) == 2 and len(parts[-1]) == 2:
            pass  # Dejar como decimal
        else:
            cleaned = cleaned.replace(".", "")

    try:
        return float(cleaned)
    except ValueError:
        return None


def detect_currency(text: Optional[str]) -> str:
    """Detecta moneda a partir de texto. Default ARS."""
    if not text:
        return "ARS"
    text_upper = text.upper()
    if "U$S" in text_upper or "USD" in text_upper or "US$" in text_upper:
        return "USD"
    return "ARS"


def parse_km(text: Optional[str]) -> Optional[int]:
    """Parsea kilometraje desde distintas variantes de texto.

    Ejemplos:
        "75.000 km" -> 75000
        "75000 km" -> 75000
        "75 mil km" -> 75000
        "75mil" -> 75000
        "75000" -> 75000
    """
    if not text:
        return None

    cleaned = text.lower().strip()

    # Patron "XX mil" o "XXmil" (ej: "97 mil km", "97mil")
    mil_match = re.search(r"(\d+)\s*mil\b", cleaned)
    if mil_match:
        return int(mil_match.group(1)) * 1000

    return extract_number(text)


def parse_year(text: Optional[str]) -> Optional[int]:
    """Extrae un año valido (1990-2030) de un texto."""
    if not text:
        return None
    matches = re.findall(r"\b(19\d{2}|20[0-3]\d)\b", text)
    if matches:
        return int(matches[0])
    return None
