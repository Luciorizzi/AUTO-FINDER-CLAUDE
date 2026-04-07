"""Logger reutilizable para todo el proyecto.

Uso:
    from app.utils.logger import get_logger
    logger = get_logger(__name__)
    logger.info("Mensaje")
"""

import logging
import sys
from typing import Optional


_CONFIGURED = False


def setup_logging(level: str = "INFO") -> None:
    """Configura el logging global una sola vez."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    numeric_level = getattr(logging, level.upper(), logging.INFO)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    root_logger.addHandler(handler)

    _CONFIGURED = True


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Retorna un logger con el nombre dado."""
    return logging.getLogger(name)
