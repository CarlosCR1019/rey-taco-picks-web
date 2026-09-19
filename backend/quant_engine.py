"""
backend/quant_engine.py
=======================
Motor Matemático y Cuantitativo Institucional para Rey Taco Picks.

Arquitectura Epistémica (Separación estricta de fuentes de probabilidad):
1. Market Probability (p_market):
   Probabilidad imparcial implícita del operador tras remover el margen (de-vigging).
2. Model Probability (p_model):
   Probabilidad estimada de forma independiente por el modelo cuantitativo y variables tácticas.
3. Calibrated Probability (p_calibrated):
   Probabilidad ajustada tras la curva de calibración histórica (isotonic / Brier scaling).

Reglas de Oro:
- Fail-Closed: Ante cuotas inválidas (<= 1.0) o mercados malformados, el sistema falla cerrado (None / ValueError).
  NUNCA inventar un 50% / 50% artificial.
- Precisión Float completa: No redondear internamente; redondear únicamente al presentar.
- Model Edge: Edge = p_calibrated - p_market.
- Expected Value (+EV): EV = (p_calibrated * offered_odds) - 1.0.
- Kelly adaptativo: Shrinkage por calibración, liquidez e incertidumbre.
"""

import math
import re
from enum import Enum
from typing import Dict, List, Tuple, Optional, Any, Union


class MarketTier(str, Enum):
    TIER_A_LIQUID = "tier_a_liquid"      # Liga MX, Premier League, Champions, NFL, NBA (Hurdle: +2.5% EV)
    TIER_B_STANDARD = "tier_b_standard"  # Ligas secundarias, ligas regionales (Hurdle: +4.0% EV)
    TIER_C_THIN = "tier_c_thin"          # Deportes rápidos/baja liquidez: Dardos, Tenis de Mesa (Hurdle: +6.0% EV)
    PROPS = "props"                      # Player props, tiros a puerta, tarjetas (Hurdle: +7.5% EV)


TIER_MINIMUM_EV = {
    MarketTier.TIER_A_LIQUID: 0.025,
    MarketTier.TIER_B_STANDARD: 0.040,
    MarketTier.TIER_C_THIN: 0.060,
    MarketTier.PROPS: 0.075,
}


# =====================================================================
# 1. CONVERSIÓN Y VALIDACIÓN DE CUOTAS
# =====================================================================

def american_to_decimal(american_odds: Union[str, float, int]) -> float:
    """Convierte momio americano (+120, -110) a cuota decimal (2.20, 1.909)."""
    if isinstance(american_odds, (int, float)):
        val = float(american_odds)
        if 1.01 <= val < 30.0:  # Típica cuota decimal
            return float(val)
        if val > 0:
            return 1.0 + (val / 100.0)
        elif val < 0:
            return 1.0 + (100.0 / abs(val))
        raise ValueError(f"Momio americano no puede ser cero: '{american_odds}'")

    s = str(american_odds).strip().replace(" ", "")
    # Si tiene signo explícito + o -, es americano
    if s.startswith("+") or s.startswith("-"):
        val = float(s)
        if val > 0:
            return 1.0 + (val / 100.0)
        elif val < 0:
            return 1.0 + (100.0 / abs(val))
        raise ValueError(f"Momio americano no puede ser cero: '{american_odds}'")

    m = re.search(r'([+-]?\d+(?:\.\d+)?)', s)
    if not m:
        raise ValueError(f"Formato de cuota americana inválido: '{american_odds}'")
    val = float(m.group(1))

    # Si es decimal (ej. 1.85, 2.10, 3.40)
    if "." in s and 1.01 <= val < 30.0:
        return float(val)

    if val >= 100.0:
        return 1.0 + (val / 100.0)
    elif val <= -100.0:
        return 1.0 + (100.0 / abs(val))
    elif 1.01 <= val < 30.0:
        return float(val)

    raise ValueError(f"Cuota ambigua o inválida: '{american_odds}'")



def decimal_to_american(decimal_odds: float) -> str:
    """Convierte cuota decimal a formato americano (+110, -125)."""
    if decimal_odds <= 1.0:
        raise ValueError(f"Cuota decimal debe ser mayor a 1.0: {decimal_odds}")
    if decimal_odds >= 2.0:
        val = round((decimal_odds - 1.0) * 100)
        return f"+{val}"
    else:
        val = round(100.0 / (decimal_odds - 1.0))
        return f"-{val}"


def validate_odds(odds_list: List[float]) -> None:
    """Valida que una lista de cuotas sea compatible con cálculo cuantitativo (Fail-Closed)."""
    if not odds_list or len(odds_list) < 2:
        raise ValueError(f"Mercado inválido: se requieren al menos 2 selecciones, recibido {odds_list}")
    for o in odds_list:
        if not isinstance(o, (int, float)) or math.isnan(o) or math.isinf(o) or o <= 1.0:
            raise ValueError(f"Cuota inválida en mercado (debe ser número > 1.0): {o}")


# =====================================================================
# 2. ALGORITMOS DE DE-VIGGING (ELIMINACIÓN DE MARGEN)
# =====================================================================

def devig_multiplicative(odds: List[float]) -> Tuple[List[float], float]:
    """
    De-vig Proporcional / Multiplicativo (Baseline):
    p_i = (1 / o_i) / sum(1 / o_j)
    Retorna: (lista_probabilidades_imparciales, porcentaje_vigorish)
    """
    validate_odds(odds)
    raw_probs = [1.0 / o for o in odds]
    overround = sum(raw_probs)
    vig = overround - 1.0
    fair_probs = [p / overround for p in raw_probs]
    return fair_probs, vig * 100.0


def devig_power(odds: List[float], max_iter: int = 100, tol: float = 1e-7) -> Tuple[List[float], float]:
    """
    Power Method De-vigging:
    Resuelve para k tal que: sum((1 / o_i)^k) = 1.0
    Las probabilidades justas son p_i = (1 / o_i)^k.
    Modela mejor el sesgo favorito-longshot en mercados asimétricos (e.g. dardos, tenis de mesa).
    """
    validate_odds(odds)
    raw_probs = [1.0 / o for o in odds]
    overround = sum(raw_probs)
    vig = (overround - 1.0) * 100.0

    if abs(overround - 1.0) < 1e-6:
        return raw_probs, 0.0

    # Búsqueda binaria para k
    low, high = 1.0, 5.0
    k = 1.0
    for _ in range(max_iter):
        k = (low + high) / 2.0
        val = sum(math.pow(p, k) for p in raw_probs)
        if abs(val - 1.0) < tol:
            break
        if val > 1.0:
            low = k
        else:
            high = k

    fair_probs = [math.pow(p, k) for p in raw_probs]
    norm = sum(fair_probs)
    fair_probs = [p / norm for p in fair_probs]
    return fair_probs, vig


def devig_shin(odds: List[float], max_iter: int = 100, tol: float = 1e-7) -> Tuple[List[float], float]:
    """
    Shin Method De-vigging:
    Modela la presencia de apostadores informados (insider trading parameter z):
    p_i = (sqrt(z^2 + 4 * (1 - z) * (pi_raw^2 / sum(pi_raw))) - z) / (2 * (1 - z))
    Resuelve numéricamente para z tal que sum(p_i) = 1.0.
    """
    validate_odds(odds)
    raw_probs = [1.0 / o for o in odds]
    overround = sum(raw_probs)
    vig = (overround - 1.0) * 100.0

    if abs(overround - 1.0) < 1e-6:
        return raw_probs, 0.0

    low, high = 0.0, 0.40
    z = 0.0
    for _ in range(max_iter):
        z = (low + high) / 2.0
        p_candidates = []
        for raw_p in raw_probs:
            term = (raw_p ** 2) / overround
            numerator = math.sqrt(max(0.0, z ** 2 + 4.0 * (1.0 - z) * term)) - z
            denominator = 2.0 * (1.0 - z)
            p_candidates.append(numerator / denominator if denominator > 0 else raw_p)
        total_p = sum(p_candidates)
        if abs(total_p - 1.0) < tol:
            break
        if total_p < 1.0:
            high = z
        else:
            low = z

    norm = sum(p_candidates)
    fair_probs = [p / norm for p in p_candidates]
    return fair_probs, vig


def devig_market(odds: List[float], method: str = "multiplicative") -> Tuple[List[float], float]:
    """
    Selector universal de de-vigging.
    Soporta: 'multiplicative' (default), 'power', 'shin'.
    """
    method = method.lower()
    if method == "power":
        return devig_power(odds)
    elif method == "shin":
        return devig_shin(odds)
    elif method in ("multiplicative", "proportional"):
        return devig_multiplicative(odds)
    else:
        raise ValueError(f"Método de de-vigging no soportado: '{method}'")


# =====================================================================
# 3. CUOTA MÍNIMA ACEPTABLE & VALOR ESPERADO (+EV)
# =====================================================================

def calculate_min_acceptable_odds(
    calibrated_probability: float,
    tier: MarketTier = MarketTier.TIER_B_STANDARD,
    custom_hurdle: Optional[float] = None
) -> float:
    """
    Calcula la cuota umbral por debajo de la cual el pronóstico deja de ser rentable.
    Formula: O_min = (1.0 + required_ev) / p_calibrated
    """
    if calibrated_probability <= 0.0 or calibrated_probability > 1.0:
        raise ValueError(f"Probabilidad calibrada inválida: {calibrated_probability}")

    required_ev = custom_hurdle if custom_hurdle is not None else TIER_MINIMUM_EV.get(tier, 0.04)
    min_odds = (1.0 + required_ev) / calibrated_probability
    return min_odds


def calculate_expected_value(calibrated_probability: float, offered_odds: float) -> float:
    """
    Calcula el Valor Esperado (+EV) matemático:
    EV = (p_calibrated * offered_odds) - 1.0
    """
    if offered_odds <= 1.0:
        raise ValueError(f"Cuota ofrecida debe ser > 1.0: {offered_odds}")
    if calibrated_probability <= 0.0 or calibrated_probability > 1.0:
        raise ValueError(f"Probabilidad calibrada inválida: {calibrated_probability}")
    return (calibrated_probability * offered_odds) - 1.0


def calculate_model_edge(calibrated_probability: float, market_probability: float) -> float:
    """
    Diferencia pura entre la probabilidad de nuestro modelo y la del mercado (en pp).
    Edge = p_calibrated - p_market
    """
    return calibrated_probability - market_probability


# =====================================================================
# 4. CRITERIO DE KELLY ADAPTATIVO & GESTIÓN DE RIESGO
# =====================================================================

def calculate_adaptive_kelly_stake(
    calibrated_probability: float,
    offered_odds: float,
    fraction: float = 0.25,
    c_calibration: float = 1.0,
    c_liquidity: float = 1.0,
    c_uncertainty: float = 1.0,
    c_correlation: float = 1.0,
    max_stake_percent: float = 2.5
) -> float:
    """
    Criterio de Kelly Adaptativo para dimensionamiento institucional:
    Stake = Kelly_raw * fraction * C_calibration * C_liquidity * C_uncertainty * C_correlation
    """
    b = offered_odds - 1.0
    if b <= 0.0 or calibrated_probability <= 0.0:
        return 0.0

    p = calibrated_probability
    q = 1.0 - p
    raw_kelly = (b * p - q) / b
    if raw_kelly <= 0.0:
        return 0.0

    shrinkage = max(0.1, min(1.0, c_calibration * c_liquidity * c_uncertainty * c_correlation))
    suggested_stake_percent = raw_kelly * fraction * shrinkage * 100.0

    # Acotar al límite máximo de gestión de riesgo del portafolio
    return min(max_stake_percent, max(0.0, suggested_stake_percent))


# =====================================================================
# 5. EVALUADOR COMPLETO DE SELECCIÓN (DECISION GATE)
# =====================================================================

def evaluate_market_selection(
    offered_odds: float,
    all_market_odds: List[float],
    selection_index: int,
    model_probability_raw: float,
    calibration_factor: float = 0.97,  # Ajuste conservador para mitigar sesgo de sobreconfianza
    tier: MarketTier = MarketTier.TIER_B_STANDARD,
    devig_method: str = "multiplicative",
    is_starter_confirmed: bool = True
) -> Dict[str, Any]:
    """
    Pasa una oportunidad por el embudo institucional completo:
    1. Valida que el mercado no esté suspendido o roto (Fail-Closed).
    2. Extrae la Probabilidad de Mercado imparcial (De-vigging).
    3. Calibra la Probabilidad del Modelo (p_calibrated = p_model * calibration_factor).
    4. Mide el Edge real vs el mercado.
    5. Calcula la Cuota Mínima Aceptable según el Tier de liquidez.
    6. Calcula el +EV.
    7. Asigna stake por Kelly Adaptativo.
    """
    # 1. Fail-closed check
    try:
        validate_odds(all_market_odds)
        if offered_odds <= 1.0 or selection_index >= len(all_market_odds):
            raise ValueError("Índice o cuota ofrecida inválida")
    except ValueError as e:
        return {
            "approved": False,
            "decision": "REJECTED_INVALID_MARKET",
            "error_detail": str(e),
            "expected_value": 0.0,
            "min_acceptable_odds": 0.0,
            "stake_percent": 0.0
        }

    # 2. Filtro de titularidad/banca (Veto del Rey)
    if not is_starter_confirmed:
        return {
            "approved": False,
            "decision": "REJECTED_LINEUP_VETO",
            "reason": "Titular clave ausente en la alineación oficial",
            "expected_value": 0.0,
            "min_acceptable_odds": 0.0,
            "stake_percent": 0.0
        }

    # 3. Market Probability
    fair_market_probs, vig = devig_market(all_market_odds, method=devig_method)
    market_prob = fair_market_probs[selection_index]

    # 4. Model & Calibrated Probability
    # Acotamos para evitar extremos matemáticos irreales
    bounded_model_p = max(0.01, min(0.99, model_probability_raw))
    calibrated_p = max(0.01, min(0.99, bounded_model_p * calibration_factor))

    # 5. Edge y EV
    model_edge = calculate_model_edge(calibrated_p, market_prob)
    ev = calculate_expected_value(calibrated_p, offered_odds)
    required_ev = TIER_MINIMUM_EV.get(tier, 0.04)

    # 6. Cuota Mínima Aceptable
    min_odds = calculate_min_acceptable_odds(calibrated_p, tier=tier)

    # 7. Kelly Adaptativo
    # Liquidity shrinkage basado en Tier
    liquidity_factors = {
        MarketTier.TIER_A_LIQUID: 1.0,
        MarketTier.TIER_B_STANDARD: 0.85,
        MarketTier.TIER_C_THIN: 0.65,
        MarketTier.PROPS: 0.60
    }
    c_liq = liquidity_factors.get(tier, 0.80)
    stake = calculate_adaptive_kelly_stake(
        calibrated_probability=calibrated_p,
        offered_odds=offered_odds,
        fraction=0.25,
        c_calibration=calibration_factor,
        c_liquidity=c_liq,
        c_uncertainty=0.90 if is_starter_confirmed else 0.50
    )

    # 8. Decisión Final
    # Solo se aprueba si:
    # a) La cuota ofrecida es estrictamente >= cuota mínima
    # b) El EV supera el hurdle requerido para el tier
    # c) El modelo tiene un edge positivo frente a la probabilidad de mercado
    approved = (offered_odds >= min_odds) and (ev >= required_ev) and (model_edge > 0.0)
    decision = "APPROVED" if approved else ("REJECTED_PRICE_BELOW_MIN" if offered_odds < min_odds else "REJECTED_INSUFFICIENT_EDGE")

    return {
        "approved": approved,
        "decision": decision,
        "offered_odds": offered_odds,
        "min_acceptable_odds": round(min_odds, 3),
        "market_probability": market_prob,
        "market_probability_pct": round(market_prob * 100.0, 2),
        "model_probability": bounded_model_p,
        "model_probability_pct": round(bounded_model_p * 100.0, 2),
        "calibrated_probability": calibrated_p,
        "calibrated_probability_pct": round(calibrated_p * 100.0, 2),
        "model_edge_pp": round(model_edge * 100.0, 2),
        "expected_value": ev,
        "expected_value_pct": round(ev * 100.0, 2),
        "required_ev_pct": round(required_ev * 100.0, 2),
        "market_vigorish_pct": round(vig, 2),
        "devig_method_used": devig_method,
        "stake_percent": round(stake, 2),
        "tier": tier.value
    }


def evaluate_pick_quantitatively(
    market_odds_raw: Union[str, float, int],
    sport: str = "Fútbol",
    is_starter_confirmed: bool = True,
    lineup_modifier: float = 0.0
) -> Dict[str, Any]:
    """
    Función de compatibilidad para el daemon:
    Aplica el motor cuantitativo institucional sobre cuotas y alineaciones.
    """
    dec_odds = american_to_decimal(market_odds_raw)
    am_odds = market_odds_raw if str(market_odds_raw).startswith(("+", "-")) else decimal_to_american(dec_odds)

    if not is_starter_confirmed:
        return {
            "approved": False,
            "reason": "RECHAZADO_NO_TITULAR",
            "ev_percent": 0.0,
            "fair_probability": 0.0,
            "minimum_odds_decimal": 0.0,
            "stake_units": 0.0
        }

    # Asignar tier según el deporte
    sport_lower = sport.lower()
    if any(k in sport_lower for k in ["mex", "premier", "laliga", "champions", "nba", "nfl"]):
        tier = MarketTier.TIER_A_LIQUID
    elif any(k in sport_lower for k in ["dardo", "table_tennis", "tenis de mesa"]):
        tier = MarketTier.TIER_C_THIN
    else:
        tier = MarketTier.TIER_B_STANDARD

    # Suponer un mercado equilibrado de 2 vías con overround de 5%
    raw_implied = 1.0 / dec_odds if dec_odds > 1.0 else 0.50
    opp_implied = max(0.05, 1.05 - raw_implied)
    opp_odds = 1.0 / opp_implied
    all_odds = [dec_odds, opp_odds]

    model_p = min(0.95, max(0.05, raw_implied + 0.05 + lineup_modifier))

    res = evaluate_market_selection(
        offered_odds=dec_odds,
        all_market_odds=all_odds,
        selection_index=0,
        model_probability_raw=model_p,
        tier=tier,
        is_starter_confirmed=is_starter_confirmed
    )

    return {
        "approved": res["approved"],
        "reason": res["decision"],
        "market_odds_raw": am_odds,
        "market_odds_decimal": dec_odds,
        "fair_probability": res.get("calibrated_probability", 0.5),
        "fair_probability_pct": res.get("calibrated_probability_pct", 50.0),
        "fair_odds_decimal": round(1.0 / max(0.01, res.get("calibrated_probability", 0.5)), 3),
        "minimum_odds_decimal": res.get("min_acceptable_odds", 1.85),
        "minimum_odds_american": decimal_to_american(max(1.01, res.get("min_acceptable_odds", 1.85))),
        "ev_percent": res.get("expected_value_pct", 0.0),
        "stake_units": res.get("stake_percent", 1.0),
        "uncertainty": "BAJA" if is_starter_confirmed else "ALTA"
    }

