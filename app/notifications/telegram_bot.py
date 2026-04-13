"""Integración con Telegram Bot API.

Envía mensajes de texto a un chat de Telegram usando la Bot API.
Usa `requests` (ya en el proyecto) sin dependencias extra.

Comportamiento ante errores:
- Loguea el error pero NUNCA rompe el pipeline.
- Retorna un resultado con status y error para persistir.
"""

from dataclasses import dataclass
from typing import Optional

import requests

from app.utils.logger import get_logger

logger = get_logger(__name__)

_TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"
_TIMEOUT_SECONDS = 15


@dataclass
class TelegramSendResult:
    """Resultado de un intento de envío a Telegram."""
    success: bool
    status_code: Optional[int] = None
    error: Optional[str] = None
    message_id: Optional[int] = None


def send_telegram_message(
    bot_token: str,
    chat_id: str,
    text: str,
    *,
    parse_mode: str = "HTML",
    disable_web_page_preview: bool = False,
) -> TelegramSendResult:
    """Envía un mensaje de texto a Telegram.

    Args:
        bot_token: Token del bot de Telegram.
        chat_id: ID del chat destino.
        text: Texto del mensaje (puede ser HTML).
        parse_mode: Modo de parseo (HTML o Markdown).
        disable_web_page_preview: Deshabilitar preview de links.

    Returns:
        TelegramSendResult con el estado del envío.
    """
    if not bot_token or not chat_id:
        return TelegramSendResult(
            success=False,
            error="bot_token o chat_id vacío",
        )

    url = _TELEGRAM_API_URL.format(token=bot_token)
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_web_page_preview,
    }

    try:
        response = requests.post(url, json=payload, timeout=_TIMEOUT_SECONDS)
        data = response.json()

        if response.status_code == 200 and data.get("ok"):
            msg_id = data.get("result", {}).get("message_id")
            logger.debug("Telegram OK: message_id=%s", msg_id)
            return TelegramSendResult(
                success=True,
                status_code=200,
                message_id=msg_id,
            )

        error_desc = data.get("description", response.text[:200])
        logger.warning(
            "Telegram error HTTP %d: %s", response.status_code, error_desc
        )
        return TelegramSendResult(
            success=False,
            status_code=response.status_code,
            error=error_desc,
        )

    except requests.Timeout:
        logger.warning("Telegram timeout (%ds)", _TIMEOUT_SECONDS)
        return TelegramSendResult(success=False, error="timeout")
    except requests.ConnectionError as e:
        logger.warning("Telegram connection error: %s", e)
        return TelegramSendResult(success=False, error=f"connection_error: {e}")
    except Exception as e:
        logger.error("Telegram error inesperado: %s", e, exc_info=True)
        return TelegramSendResult(success=False, error=f"unexpected: {e}")
