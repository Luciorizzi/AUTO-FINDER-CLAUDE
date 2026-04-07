"""Modulo de navegador reutilizable basado en Playwright.

Gestiona el ciclo de vida del browser: iniciar, crear paginas, cerrar.
Soporta modo headless configurable por .env.
"""

from typing import Optional

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from app.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_TIMEOUT_MS = 30_000
DEFAULT_NAV_TIMEOUT_MS = 45_000

# User agent por defecto para evitar bloqueos de ML
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class BrowserManager:
    """Administra una instancia de Playwright + Chromium."""

    def __init__(
        self,
        headless: bool = True,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        user_agent: Optional[str] = None,
    ):
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.user_agent = user_agent or DEFAULT_USER_AGENT
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None

    def start(self) -> None:
        """Inicia Playwright y abre el navegador."""
        logger.info("Iniciando navegador (headless=%s)", self.headless)
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)

        self._context = self._browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="es-AR",
            user_agent=self.user_agent,
        )
        self._context.set_default_timeout(self.timeout_ms)
        self._context.set_default_navigation_timeout(DEFAULT_NAV_TIMEOUT_MS)
        logger.info("Navegador iniciado")

    def new_page(self) -> Page:
        """Crea una nueva pestaña."""
        if not self._context:
            raise RuntimeError("BrowserManager no iniciado. Llamar a start() primero.")
        return self._context.new_page()

    def close(self) -> None:
        """Cierra navegador y Playwright."""
        if self._context:
            self._context.close()
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        logger.info("Navegador cerrado")

    def __enter__(self) -> "BrowserManager":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
