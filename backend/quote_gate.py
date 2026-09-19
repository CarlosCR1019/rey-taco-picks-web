"""
backend/quote_gate.py
=====================
Motor de Control de Latencia y Validación de Cuota en Dos Fases (Two-Phase Quote Gate).

Misión:
Evitar que el suscriptor reciba un pronóstico cuya cuota ya colapsó en el operador
durante la ventana de cálculo, renderizado y entrega (fetch -> model -> dispatch).

Flujo:
1. Fase A (Descubrimiento): El modelo cuantitativo aprueba una cuota O_A >= O_min.
2. Ventana de Procesamiento: Renderizado de copy / video / formato.
3. Fase B (Pre-Dispatch Gate): Consulta la cuota en vivo O_B milisegundos antes del envío.
   Condición: O_B >= O_min * (1 + s_latency)
   - Si O_B < O_min: Aborta inmediatamente el despacho y emite evento PRICE_EXPIRED al Ledger.
   - Si O_B >= O_min: Autoriza la publicación y emite evento PICK_PUBLISHED.
"""

import time
import logging
from typing import Dict, Any, Tuple, Optional, Callable
from pathlib import Path

from backend.audit_ledger import (
    record_price_expired,
    record_pick_published,
    AUDIT_LEDGER_PATH
)

logger = logging.getLogger("QuoteGate")

# TTL máximo de frescura por categoría deportiva (en segundos)
DEFAULT_MAX_QUOTE_AGE_SECONDS = {
    "futbol": 8.0,
    "soccer": 8.0,
    "nfl": 6.0,
    "nba": 5.0,
    "mlb": 5.0,
    "tenis": 3.0,
    "tennis": 3.0,
    "table_tennis": 2.0,
    "dardos": 2.0,
    "darts": 2.0,
    "esports": 2.0,
}


class TwoPhaseQuoteGate:
    """Validador de frescura y salvaguarda de precio pre-despacho."""

    def __init__(
        self,
        default_latency_buffer: float = 0.005,  # 0.5% de buffer adicional para amortiguar latencia de red
        ledger_path: Path = AUDIT_LEDGER_PATH
    ):
        self.latency_buffer = default_latency_buffer
        self.ledger_path = ledger_path

    def get_max_quote_age(self, sport: str) -> float:
        """Determina la vida útil máxima de una cuota antes de considerarla obsoleta (stale)."""
        clean_sport = sport.strip().lower().replace(" ", "_")
        return DEFAULT_MAX_QUOTE_AGE_SECONDS.get(clean_sport, 6.0)

    def validate_and_gate_dispatch(
        self,
        ticket_id: str,
        sport: str,
        initial_odds: float,
        min_acceptable_odds: float,
        live_odds_fetcher: Callable[[], Optional[float]],
        observed_at_epoch: Optional[float] = None,
        channel: str = "TELEGRAM_FREE"
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Ejecuta la Fase B previa al despacho.
        Retorna: (is_approved, status_code, details_dict)
        """
        now = time.time()
        max_age = self.get_max_quote_age(sport)

        # 1. Chequeo de TTL si se proveyó observed_at_epoch
        if observed_at_epoch:
            age = now - observed_at_epoch
            if age > max_age:
                logger.warning(f"⏳ [QUOTE GATE] Cuota para ticket {ticket_id} superó TTL ({age:.2f}s > {max_age}s).")

        # 2. Consulta en vivo en tiempo real (Fase B)
        try:
            live_odds = live_odds_fetcher()
        except Exception as e:
            logger.error(f"Error consultando cuota en vivo para ticket {ticket_id}: {e}")
            live_odds = None

        if live_odds is None or live_odds <= 1.0:
            # Si el mercado cerró, se suspendió o el book retiró la línea: ABORTAR
            logger.warning(f"🚫 [QUOTE GATE] Mercado suspendido o cerrado para ticket {ticket_id}.")
            record_price_expired(
                ticket_id=ticket_id,
                stale_odds=initial_odds,
                current_live_odds=0.0,
                min_acceptable_odds=min_acceptable_odds,
                ledger_path=self.ledger_path
            )
            return False, "MARKET_SUSPENDED", {
                "ticket_id": ticket_id,
                "initial_odds": initial_odds,
                "min_acceptable_odds": min_acceptable_odds,
                "reason": "MERCADO_SUSPENDIDO_O_NO_DISPONIBLE"
            }

        # 3. Comprobar umbral de precio mínimo con buffer de latencia
        required_live_odds = min_acceptable_odds * (1.0 + self.latency_buffer)

        if live_odds < required_live_odds:
            logger.warning(
                f"🚨 [QUOTE GATE] Cuota expirada para {ticket_id}: Inicial {initial_odds} -> En vivo {live_odds} "
                f"(Mínimo requerido {required_live_odds:.3f}). ABORTANDO DESPACHO."
            )
            record_price_expired(
                ticket_id=ticket_id,
                stale_odds=initial_odds,
                current_live_odds=live_odds,
                min_acceptable_odds=min_acceptable_odds,
                ledger_path=self.ledger_path
            )
            return False, "PRICE_EXPIRED", {
                "ticket_id": ticket_id,
                "initial_odds": initial_odds,
                "live_odds": live_odds,
                "min_acceptable_odds": min_acceptable_odds,
                "drop_percent": round(((live_odds - initial_odds) / initial_odds) * 100.0, 2),
                "reason": "CUOTA_CAYO_POR_DEBAJO_DEL_MINIMO_ACEPTABLE"
            }

        # 4. Aprobado con precio vigente: sellar evento en el Ledger y permitir despacho
        logger.info(f"✅ [QUOTE GATE] Cuota validada para {ticket_id}: En vivo {live_odds} >= {min_acceptable_odds}. Autorizado.")
        record_pick_published(ticket_id=ticket_id, channel=channel, ledger_path=self.ledger_path)

        return True, "DISPATCH_AUTHORIZED", {
            "ticket_id": ticket_id,
            "live_odds": live_odds,
            "min_acceptable_odds": min_acceptable_odds,
            "channel": channel
        }
