"""Playdoit Deep Markets Extractor.

Parses official Altenar GetEventDetails JSON payloads directly from Playdoit,
extracting verified, high-value betting markets:
1. Corners (Tiros de Esquina: Total de Córners Over/Under, 1ª Mitad Córners, Córners 1X2)
2. BTTS (Ambos Equipos Anotan: Sí / No)
3. Totals (Total de Goles / Puntos / Carreras Over/Under)
4. Double Chance (Doble Oportunidad: 1X, 12, X2)
5. First Half Lines (Goles 1er Tiempo, 1X2 1er Tiempo)

Never fabricates odds or selections. Returns clean, normalized dictionaries
ready for pick evaluation and publication.
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Set, Union


def decimal_to_american(decimal_price: float) -> str:
    """Convierte cuota decimal a formato momio americano (+150 / -110)."""
    if not math.isfinite(decimal_price) or decimal_price < 1.01:
        return "+100"
    if decimal_price >= 2.0:
        val = int(round((decimal_price - 1.0) * 100.0))
        return f"+{val}"
    else:
        val = int(round(100.0 / (decimal_price - 1.0)))
        return f"-{val}"


def _flatten_selection_ids(val: Any) -> List[int]:
    """Extrae todos los IDs numéricos de una estructura potencialmente anidada."""
    if isinstance(val, int):
        return [val] if val > 0 else []
    if isinstance(val, str) and val.strip().isdigit():
        n = int(val.strip())
        return [n] if n > 0 else []
    if isinstance(val, (list, tuple)):
        result = []
        for item in val:
            result.extend(_flatten_selection_ids(item))
        return result
    return []


def _index_odds(payload: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    """Indexa las selecciones de cuotas disponibles por su ID numérico."""
    odds_list = payload.get("odds", [])
    if not isinstance(odds_list, list):
        return {}
    indexed = {}
    for o in odds_list:
        if isinstance(o, dict) and o.get("id") is not None:
            try:
                oid = int(o["id"])
                # Filtrar cuotas suspendidas si oddStatus != 0
                if o.get("oddStatus") in (None, 0):
                    indexed[oid] = o
            except (ValueError, TypeError):
                continue
    return indexed


def _parse_float(val: Any) -> Optional[float]:
    if val is None or val == "" or str(val).lower() == "none":
        return None
    try:
        f = float(val)
        return f if math.isfinite(f) else None
    except (ValueError, TypeError):
        return None


def extract_corners_markets(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extrae los mercados de Tiros de Esquina (Corners).
    Incluye Total Tiros de Esquina (TypeId 166), 1ª Mitad (TypeId 177), y líneas alternas.
    """
    odds_by_id = _index_odds(payload)
    markets = payload.get("markets", [])
    if not isinstance(markets, list):
        return []

    results = []
    seen_keys: Set[str] = set()

    for m in markets:
        if not isinstance(m, dict):
            continue
        m_name = str(m.get("name") or "").strip()
        m_type = m.get("typeId")
        lower_name = m_name.lower()

        is_corner_market = (
            m_type in (166, 177, 162, 169, 182, 21185)
            or any(kw in lower_name for kw in ["córner", "corner", "esquina"])
        )
        if not is_corner_market:
            continue

        raw_ids = _flatten_selection_ids(
            m.get("desktopOddIds") or m.get("mobileOddIds") or m.get("oddIds") or []
        )
        if not raw_ids:
            continue

        is_half_time = "1ª" in m_name or "1er" in lower_name or "mitad" in lower_name or m_type == 177
        scope = "first_half" if is_half_time else "full_game"

        # Agrupar cuotas por línea
        lines_map: Dict[float, Dict[str, Any]] = {}
        h2h_corners: List[Dict[str, Any]] = []

        for oid in raw_ids:
            odd = odds_by_id.get(oid)
            if not odd:
                continue
            price = _parse_float(odd.get("price"))
            if not price or price < 1.01:
                continue

            odd_name = str(odd.get("name") or "").strip()
            odd_type = odd.get("typeId")
            odd_sv = _parse_float(odd.get("sv") or m.get("sv"))

            # Determinar tipo de selección
            is_over = odd_type == 12 or "más" in odd_name.lower() or "over" in odd_name.lower()
            is_under = odd_type == 13 or "menos" in odd_name.lower() or "under" in odd_name.lower()

            if is_over or is_under:
                line_val = odd_sv
                if line_val is None:
                    # Extraer del nombre (ej. 'Más de 8.5')
                    m_line = re.search(r'\b(\d+(?:\.\d+)?)\b', odd_name)
                    if m_line:
                        line_val = float(m_line.group(1))

                if line_val is not None:
                    entry = lines_map.setdefault(line_val, {"line": line_val, "over": None, "under": None})
                    sel_dict = {
                        "selection_id": oid,
                        "name": odd_name,
                        "price_decimal": round(price, 4),
                        "price_american": decimal_to_american(price),
                    }
                    if is_over:
                        entry["over"] = sel_dict
                    else:
                        entry["under"] = sel_dict
            else:
                h2h_corners.append({
                    "selection_id": oid,
                    "name": odd_name,
                    "price_decimal": round(price, 4),
                    "price_american": decimal_to_american(price),
                })

        # Procesar líneas Over/Under encontradas
        for line_val, pair in sorted(lines_map.items()):
            if pair["over"] or pair["under"]:
                key = f"corners_{scope}_{line_val}"
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                results.append({
                    "market_key": "corners",
                    "scope": scope,
                    "market_name": f"Total Tiros de Esquina ({'1ª Mitad' if is_half_time else 'Partido Completo'})",
                    "line": line_val,
                    "over": pair["over"],
                    "under": pair["under"],
                    "selections": [s for s in [pair["over"], pair["under"]] if s],
                })

        # 1X2 Córners si aplica
        if m_type == 162 and h2h_corners:
            key = f"corners_1x2_{scope}"
            if key not in seen_keys:
                seen_keys.add(key)
                results.append({
                    "market_key": "corners_1x2",
                    "scope": scope,
                    "market_name": "Tiros de esquina 1X2",
                    "line": None,
                    "selections": h2h_corners,
                })

    return results


def extract_btts_markets(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extrae los mercados de Ambos Equipos Anotan (BTTS: Sí / No).
    """
    odds_by_id = _index_odds(payload)
    markets = payload.get("markets", [])
    if not isinstance(markets, list):
        return []

    results = []
    seen_keys: Set[str] = set()

    for m in markets:
        if not isinstance(m, dict):
            continue
        m_name = str(m.get("name") or "").strip()
        m_type = m.get("typeId")
        lower_name = m_name.lower()

        is_btts = (
            m_type == 29
            or "ambos equipos marcan" in lower_name
            or "ambos equipos anotarán" in lower_name
            or "ambos anotan" in lower_name
        )
        if not is_btts:
            continue

        raw_ids = _flatten_selection_ids(
            m.get("desktopOddIds") or m.get("mobileOddIds") or m.get("oddIds") or []
        )
        if not raw_ids:
            continue

        is_half_time = "1ª" in m_name or "1er" in lower_name or "mitad" in lower_name
        scope = "first_half" if is_half_time else "full_game"
        key = f"btts_{scope}"
        if key in seen_keys:
            continue

        yes_sel = None
        no_sel = None

        for oid in raw_ids:
            odd = odds_by_id.get(oid)
            if not odd:
                continue
            price = _parse_float(odd.get("price"))
            if not price or price < 1.01:
                continue

            odd_name = str(odd.get("name") or "").strip()
            odd_type = odd.get("typeId")

            sel_dict = {
                "selection_id": oid,
                "name": odd_name,
                "price_decimal": round(price, 4),
                "price_american": decimal_to_american(price),
            }

            if odd_type == 74 or odd_name.lower() in ("sí", "si", "yes"):
                yes_sel = sel_dict
            elif odd_type == 76 or odd_name.lower() in ("no",):
                no_sel = sel_dict

        if yes_sel or no_sel:
            seen_keys.add(key)
            results.append({
                "market_key": "btts",
                "scope": scope,
                "market_name": f"Ambos Equipos Anotan ({'1ª Mitad' if is_half_time else 'Partido Completo'})",
                "line": None,
                "yes": yes_sel,
                "no": no_sel,
                "selections": [s for s in [yes_sel, no_sel] if s],
            })

    return results


def extract_totals_markets(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extrae los mercados de Totales (Over/Under Total Goles, Puntos, Carreras).
    """
    odds_by_id = _index_odds(payload)
    markets = payload.get("markets", [])
    if not isinstance(markets, list):
        return []

    results = []
    seen_keys: Set[str] = set()

    for m in markets:
        if not isinstance(m, dict):
            continue
        m_name = str(m.get("name") or "").strip()
        m_type = m.get("typeId")
        lower_name = m_name.lower()

        # Mercados de total limpio en múltiples deportes (fútbol, tenis, béisbol, básquetbol, fútbol americano)
        is_total = (
            m_type in (18, 68, 189, 252)
            or (
                any(kw in lower_name for kw in ("total", "total juegos", "total de carreras", "total de puntos", "total de goles"))
                and "córner" not in lower_name
                and "esquina" not in lower_name
                and "tarjeta" not in lower_name
            )
        )
        if not is_total:
            continue

        raw_ids = _flatten_selection_ids(
            m.get("desktopOddIds") or m.get("mobileOddIds") or m.get("oddIds") or []
        )
        if not raw_ids:
            continue

        is_half_time = "1ª" in m_name or "1er" in lower_name or "mitad" in lower_name or m_type == 68
        scope = "first_half" if is_half_time else "full_game"

        sport_id = payload.get("sportId") or payload.get("sport", {}).get("id") or payload.get("champ", {}).get("sportId")
        try:
            sid_num = int(sport_id) if sport_id is not None else None
        except (ValueError, TypeError):
            sid_num = None

        if "juego" in lower_name:
            display_category = "Total de Juegos"
        elif "carrera" in lower_name or sid_num == 76:
            display_category = "Total de Carreras"
        elif "punto" in lower_name or sid_num in (75, 67) or m.get("sv") and _parse_float(m.get("sv")) and _parse_float(m.get("sv")) >= 15.0:
            display_category = "Total de Puntos"
        else:
            display_category = "Total de Goles"

        lines_map: Dict[float, Dict[str, Any]] = {}

        for oid in raw_ids:
            odd = odds_by_id.get(oid)
            if not odd:
                continue
            price = _parse_float(odd.get("price"))
            if not price or price < 1.01:
                continue

            odd_name = str(odd.get("name") or "").strip()
            odd_type = odd.get("typeId")
            odd_sv = _parse_float(odd.get("sv") or m.get("sv"))

            is_over = odd_type == 12 or "más" in odd_name.lower() or "over" in odd_name.lower()
            is_under = odd_type == 13 or "menos" in odd_name.lower() or "under" in odd_name.lower()

            if not (is_over or is_under):
                continue

            line_val = odd_sv
            if line_val is None:
                m_line = re.search(r'\b(\d+(?:\.\d+)?)\b', odd_name)
                if m_line:
                    line_val = float(m_line.group(1))

            if line_val is not None:
                entry = lines_map.setdefault(line_val, {"line": line_val, "over": None, "under": None})
                sel_dict = {
                    "selection_id": oid,
                    "name": odd_name,
                    "price_decimal": round(price, 4),
                    "price_american": decimal_to_american(price),
                }
                if is_over:
                    entry["over"] = sel_dict
                else:
                    entry["under"] = sel_dict

        for line_val, pair in sorted(lines_map.items()):
            if pair["over"] or pair["under"]:
                key = f"totals_{scope}_{line_val}"
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                results.append({
                    "market_key": "totals",
                    "scope": scope,
                    "market_name": f"{display_category} ({'1ª Mitad' if is_half_time else 'Partido Completo'})",
                    "line": line_val,
                    "over": pair["over"],
                    "under": pair["under"],
                    "selections": [s for s in [pair["over"], pair["under"]] if s],
                })

    return results


def extract_moneyline_markets(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extrae los mercados de Ganador / Moneyline (Fútbol 1X2, Tenis Ganador, Béisbol Ganador, etc.).
    """
    odds_by_id = _index_odds(payload)
    markets = payload.get("markets", [])
    if not isinstance(markets, list):
        return []

    results = []
    seen_keys: Set[str] = set()

    for m in markets:
        if not isinstance(m, dict):
            continue
        m_name = str(m.get("name") or "").strip()
        m_type = m.get("typeId")
        lower_name = m_name.lower()

        is_ml = (
            m_type in (1, 60, 186, 218, 251)
            or lower_name in (
                "ganador", "ganador del partido", "ganador (incl. extra innings)",
                "ganador (incl. prórroga)", "resultado final (tiempo regular)", "1x2", "moneyline"
            )
        )
        if not is_ml:
            continue

        raw_ids = _flatten_selection_ids(
            m.get("desktopOddIds") or m.get("mobileOddIds") or m.get("oddIds") or []
        )
        if not raw_ids:
            continue

        is_half_time = "1ª" in m_name or "1er" in lower_name or "mitad" in lower_name
        scope = "first_half" if is_half_time else "full_game"
        key = f"moneyline_{scope}_{m_type}"
        if key in seen_keys:
            continue

        selections = []
        for oid in raw_ids:
            odd = odds_by_id.get(oid)
            if not odd:
                continue
            price = _parse_float(odd.get("price"))
            if not price or price < 1.01:
                continue
            odd_name = str(odd.get("name") or "").strip()
            selections.append({
                "selection_id": oid,
                "name": odd_name,
                "price_decimal": round(price, 4),
                "price_american": decimal_to_american(price),
            })

        if selections:
            seen_keys.add(key)
            results.append({
                "market_key": "moneyline",
                "scope": scope,
                "market_name": f"{m_name} ({'1ª Mitad' if is_half_time else 'Partido Completo'})",
                "line": None,
                "selections": selections,
            })

    return results


def extract_double_chance_markets(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extrae los mercados de Doble Oportunidad (1X, 12, X2).
    """
    odds_by_id = _index_odds(payload)
    markets = payload.get("markets", [])
    if not isinstance(markets, list):
        return []

    results = []
    seen_keys: Set[str] = set()

    for m in markets:
        if not isinstance(m, dict):
            continue
        m_name = str(m.get("name") or "").strip()
        m_type = m.get("typeId")
        lower_name = m_name.lower()

        is_dc = (
            m_type in (10, 63, 85)
            or "doble oportunidad" in lower_name
        )
        if not is_dc:
            continue

        raw_ids = _flatten_selection_ids(
            m.get("desktopOddIds") or m.get("mobileOddIds") or m.get("oddIds") or []
        )
        if not raw_ids:
            continue

        is_half_time = "1ª" in m_name or "1er" in lower_name or "mitad" in lower_name or m_type == 63
        scope = "first_half" if is_half_time else "full_game"
        key = f"double_chance_{scope}"
        if key in seen_keys:
            continue

        selections = []
        for oid in raw_ids:
            odd = odds_by_id.get(oid)
            if not odd:
                continue
            price = _parse_float(odd.get("price"))
            if not price or price < 1.01:
                continue

            odd_name = str(odd.get("name") or "").strip()
            odd_type = odd.get("typeId")

            # Mapeo de etiqueta estándar (1X, 12, X2)
            code = "DC"
            if odd_type == 9:
                code = "1X"
            elif odd_type == 10:
                code = "12"
            elif odd_type == 11:
                code = "X2"

            selections.append({
                "selection_id": oid,
                "code": code,
                "name": odd_name,
                "price_decimal": round(price, 4),
                "price_american": decimal_to_american(price),
            })

        if selections:
            seen_keys.add(key)
            results.append({
                "market_key": "double_chance",
                "scope": scope,
                "market_name": f"Doble Oportunidad ({'1ª Mitad' if is_half_time else 'Partido Completo'})",
                "line": None,
                "selections": selections,
            })

    return results


def extract_spread_markets(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extrae los mercados de Hándicap / Spread / Runline en multideporte
    (Fútbol Americano NFL/NCAAF, Básquetbol NBA, Béisbol MLB Runline, Fútbol Hándicap).
    """
    odds_by_id = _index_odds(payload)
    markets = payload.get("markets", [])
    if not isinstance(markets, list):
        return []

    results = []
    seen_keys: Set[str] = set()

    for m in markets:
        if not isinstance(m, dict):
            continue
        m_name = str(m.get("name") or "").strip()
        m_type = m.get("typeId")
        lower_name = m_name.lower()

        is_spread = (
            m_type in (2, 61, 66, 219, 223, 231, 253, 303, 614)
            or any(kw in lower_name for kw in ("hándicap", "handicap", "spread", "run line", "runline", "línea de carreras", "línea de puntos"))
        )
        if not is_spread:
            continue

        raw_ids = _flatten_selection_ids(
            m.get("desktopOddIds") or m.get("mobileOddIds") or m.get("oddIds") or []
        )
        if not raw_ids:
            continue

        is_half_time = "1ª" in m_name or "1er" in lower_name or "mitad" in lower_name or m_type in (61, 66)
        scope = "first_half" if is_half_time else "full_game"

        selections = []
        for oid in raw_ids:
            odd = odds_by_id.get(oid)
            if not odd:
                continue
            price = _parse_float(odd.get("price"))
            if not price or price < 1.01:
                continue

            odd_name = str(odd.get("name") or "").strip()
            odd_sv = _parse_float(odd.get("sv"))
            
            # Extraer spread del nombre: ej. "PHI Eagles (-3.5)"
            line_val = odd_sv
            m_line = re.search(r'\(([+-]?\d+(?:\.\d+)?)\)', odd_name)
            if m_line:
                line_val = float(m_line.group(1))

            selections.append({
                "selection_id": oid,
                "name": odd_name,
                "line": line_val,
                "price_decimal": round(price, 4),
                "price_american": decimal_to_american(price),
            })

        if selections:
            key = f"spread_{scope}_{m_type}_{m_name}"
            if key not in seen_keys:
                seen_keys.add(key)
                results.append({
                    "market_key": "spreads",
                    "scope": scope,
                    "market_name": f"{m_name} ({'1ª Mitad' if is_half_time else 'Partido Completo'})",
                    "selections": selections,
                })

    return results


def extract_combos_markets(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extrae los mercados de Combos de Alto Valor (+EV) de la sección 'Todas':
    - 1X2 y Ambos Equipos Marcan (TypeId 35)
    - Total y Ambos Equipos Marcan (TypeId 36)
    - 1X2 y Total de Goles (TypeId 37)
    - Doble Oportunidad y Ambos Equipos Marcan (TypeId 546)
    - Ganador y Total (Béisbol / Baloncesto TypeId 2025)
    """
    odds_by_id = _index_odds(payload)
    markets = payload.get("markets", [])
    if not isinstance(markets, list):
        return []

    results = []
    seen_keys: Set[str] = set()

    for m in markets:
        if not isinstance(m, dict):
            continue
        m_name = str(m.get("name") or "").strip()
        m_type = m.get("typeId")
        lower_name = m_name.lower()

        is_combo = (
            m_type in (35, 36, 37, 546, 2025, 542, 543, 544, 545, 17907)
            or ("ambos equipos marcan" in lower_name and ("1x2" in lower_name or "total" in lower_name or "doble oportunidad" in lower_name))
            or ("ganador & total" in lower_name)
        )
        if not is_combo:
            continue

        raw_ids = _flatten_selection_ids(
            m.get("desktopOddIds") or m.get("mobileOddIds") or m.get("oddIds") or []
        )
        if not raw_ids:
            continue

        selections = []
        for oid in raw_ids:
            odd = odds_by_id.get(oid)
            if not odd:
                continue
            price = _parse_float(odd.get("price"))
            if not price or price < 1.01:
                continue

            odd_name = str(odd.get("name") or "").strip()
            selections.append({
                "selection_id": oid,
                "name": odd_name,
                "price_decimal": round(price, 4),
                "price_american": decimal_to_american(price),
            })

        if selections:
            key = f"combo_{m_type}_{m_name}"
            if key not in seen_keys:
                seen_keys.add(key)
                results.append({
                    "market_key": "combos",
                    "market_name": m_name,
                    "type_id": m_type,
                    "selections": selections,
                })

    return results


def extract_team_totals_markets(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extrae los mercados de Totales por Equipo (Team Totals):
    - Goles por equipo (TypeId 19, 20)
    - Carreras por equipo béisbol (TypeId 260, 261, 17691, 17692)
    - Puntos por equipo baloncesto (TypeId 227, 228)
    """
    odds_by_id = _index_odds(payload)
    markets = payload.get("markets", [])
    if not isinstance(markets, list):
        return []

    results = []
    seen_keys: Set[str] = set()

    for m in markets:
        if not isinstance(m, dict):
            continue
        m_name = str(m.get("name") or "").strip()
        m_type = m.get("typeId")
        lower_name = m_name.lower()

        is_team_total = (
            m_type in (19, 20, 260, 261, 17691, 17692, 227, 228, 69, 70, 91, 92, 277, 278)
            or ("total" in lower_name and any(kw in lower_name for kw in ("goles", "carreras", "totales (incl. extra innings)", "totales (incl. prórroga)")))
        )
        if not is_team_total:
            continue

        raw_ids = _flatten_selection_ids(
            m.get("desktopOddIds") or m.get("mobileOddIds") or m.get("oddIds") or []
        )
        if not raw_ids:
            continue

        lines_map: Dict[float, Dict[str, Any]] = {}
        for oid in raw_ids:
            odd = odds_by_id.get(oid)
            if not odd:
                continue
            price = _parse_float(odd.get("price"))
            if not price or price < 1.01:
                continue

            odd_name = str(odd.get("name") or "").strip()
            odd_type = odd.get("typeId")
            odd_sv = _parse_float(odd.get("sv") or m.get("sv"))

            is_over = odd_type == 12 or "más" in odd_name.lower() or "over" in odd_name.lower()
            is_under = odd_type == 13 or "menos" in odd_name.lower() or "under" in odd_name.lower()

            line_val = odd_sv
            if line_val is None:
                m_line = re.search(r'\b(\d+(?:\.\d+)?)\b', odd_name)
                if m_line:
                    line_val = float(m_line.group(1))
            if line_val is None:
                line_val = 0.5

            entry = lines_map.setdefault(line_val, {"line": line_val, "over": None, "under": None})
            sel_dict = {
                "selection_id": oid,
                "name": odd_name,
                "price_decimal": round(price, 4),
                "price_american": decimal_to_american(price),
            }
            if is_over:
                entry["over"] = sel_dict
            elif is_under:
                entry["under"] = sel_dict

        for line_val, pair in sorted(lines_map.items()):
            if pair["over"] or pair["under"]:
                key = f"team_total_{m_name}_{line_val}"
                if key not in seen_keys:
                    seen_keys.add(key)
                    results.append({
                        "market_key": "team_totals",
                        "market_name": m_name,
                        "line": line_val,
                        "over": pair["over"],
                        "under": pair["under"],
                        "selections": [s for s in [pair["over"], pair["under"]] if s],
                    })

    return results


def extract_baseball_f5_markets(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extrae los mercados clave de Béisbol (F5 y 1er Inning):
    - Innings 1 a 5 (Ganador TypeId 274, 1124)
    - Innings 1 a 5 (Hándicap / Spread TypeId 275)
    - Innings 1 a 5 (Total carreras Over/Under TypeId 276)
    - Primer inning carrera (NRFI/YRFI TypeId 749, 750, 1043)
    """
    odds_by_id = _index_odds(payload)
    markets = payload.get("markets", [])
    if not isinstance(markets, list):
        return []

    results = []
    seen_keys: Set[str] = set()

    for m in markets:
        if not isinstance(m, dict):
            continue
        m_name = str(m.get("name") or "").strip()
        m_type = m.get("typeId")
        lower_name = m_name.lower()

        is_f5_or_inning = (
            m_type in (274, 275, 276, 1124, 749, 750, 608, 1043)
            or "innings 1 a 5" in lower_name
            or "primer inning" in lower_name
            or "primero inning" in lower_name
        )
        if not is_f5_or_inning:
            continue

        raw_ids = _flatten_selection_ids(
            m.get("desktopOddIds") or m.get("mobileOddIds") or m.get("oddIds") or []
        )
        if not raw_ids:
            continue

        selections = []
        for oid in raw_ids:
            odd = odds_by_id.get(oid)
            if not odd:
                continue
            price = _parse_float(odd.get("price"))
            if not price or price < 1.01:
                continue

            odd_name = str(odd.get("name") or "").strip()
            selections.append({
                "selection_id": oid,
                "name": odd_name,
                "price_decimal": round(price, 4),
                "price_american": decimal_to_american(price),
            })

        if selections:
            key = f"f5_inning_{m_type}_{m_name}"
            if key not in seen_keys:
                seen_keys.add(key)
                results.append({
                    "market_key": "baseball_f5",
                    "market_name": m_name,
                    "type_id": m_type,
                    "selections": selections,
                })

    return results


def extract_player_props_markets(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extrae los mercados de Props de Jugador de alta liquidez:
    - Fútbol: Remates a puerta (TypeId 15734, 15737), Goleador (TypeId 21001), Tarjetas
    - Béisbol: Ponches del pitcher (TypeId 785, 31244), Hits del bateador (TypeId 781, 1040, 2123), Bases (TypeId 2132)
    - Baloncesto: Puntos (TypeId 768), Asistencias (TypeId 770), Rebotes (TypeId 772), Triples (TypeId 774)
    """
    odds_by_id = _index_odds(payload)
    markets = payload.get("markets", [])
    if not isinstance(markets, list):
        return []

    results = []
    seen_keys: Set[str] = set()

    for m in markets:
        if not isinstance(m, dict):
            continue
        m_name = str(m.get("name") or "").strip()
        m_type = m.get("typeId")
        lower_name = m_name.lower()

        is_prop = (
            m_type in (15734, 15737, 21001, 31200, 785, 31244, 781, 1040, 2123, 2132, 768, 770, 772, 774)
            or any(kw in lower_name for kw in (
                "remates a puerta", "remates a portería", "goleador",
                "strikeouts del pitcher", "ponches de los lanzadores", "bases totales por jugador",
                "puntos de jugador", "triples anotados", "asistencias de jugador", "rebotes de jugador"
            ))
        )
        if not is_prop:
            continue

        raw_ids = _flatten_selection_ids(
            m.get("desktopOddIds") or m.get("mobileOddIds") or m.get("oddIds") or []
        )
        if not raw_ids:
            continue

        selections = []
        for oid in raw_ids:
            odd = odds_by_id.get(oid)
            if not odd:
                continue
            price = _parse_float(odd.get("price"))
            if not price or price < 1.01:
                continue

            odd_name = str(odd.get("name") or "").strip()
            selections.append({
                "selection_id": oid,
                "name": odd_name,
                "price_decimal": round(price, 4),
                "price_american": decimal_to_american(price),
            })

        if selections:
            key = f"prop_{m_type}_{m_name}"
            if key not in seen_keys:
                seen_keys.add(key)
                results.append({
                    "market_key": "player_props",
                    "market_name": m_name,
                    "type_id": m_type,
                    "selections": selections,
                })

    return results


def extract_all_enriched_markets(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extrae todos los mercados enriquecidos de un evento en una sola estructura limpia,
    abarcando la sección completa de 'Todas' en Playdoit / Altenar.
    """
    event_id = str(payload.get("id") or "").strip()
    event_name = str(payload.get("name") or "").strip()
    champ_name = str(payload.get("champ", {}).get("name") or "").strip()
    starts_at = payload.get("startDate")

    corners = extract_corners_markets(payload)
    btts = extract_btts_markets(payload)
    totals = extract_totals_markets(payload)
    double_chance = extract_double_chance_markets(payload)
    moneyline = extract_moneyline_markets(payload)
    spreads = extract_spread_markets(payload)
    combos = extract_combos_markets(payload)
    team_totals = extract_team_totals_markets(payload)
    baseball_f5 = extract_baseball_f5_markets(payload)
    player_props = extract_player_props_markets(payload)

    total_selections = (
        sum(len(m.get("selections", [])) for m in corners)
        + sum(len(m.get("selections", [])) for m in btts)
        + sum(len(m.get("selections", [])) for m in totals)
        + sum(len(m.get("selections", [])) for m in double_chance)
        + sum(len(m.get("selections", [])) for m in moneyline)
        + sum(len(m.get("selections", [])) for m in spreads)
        + sum(len(m.get("selections", [])) for m in combos)
        + sum(len(m.get("selections", [])) for m in team_totals)
        + sum(len(m.get("selections", [])) for m in baseball_f5)
        + sum(len(m.get("selections", [])) for m in player_props)
    )

    return {
        "event_id": event_id,
        "event_name": event_name,
        "competition": champ_name,
        "starts_at": starts_at,
        "market_categories": {
            "corners": corners,
            "btts": btts,
            "totals": totals,
            "double_chance": double_chance,
            "moneyline": moneyline,
            "spreads": spreads,
            "combos": combos,
            "team_totals": team_totals,
            "baseball_f5": baseball_f5,
            "player_props": player_props,
        },
        "stats": {
            "corners_lines_count": len(corners),
            "btts_lines_count": len(btts),
            "totals_lines_count": len(totals),
            "double_chance_lines_count": len(double_chance),
            "moneyline_count": len(moneyline),
            "spreads_lines_count": len(spreads),
            "combos_count": len(combos),
            "team_totals_count": len(team_totals),
            "baseball_f5_count": len(baseball_f5),
            "player_props_count": len(player_props),
            "total_enriched_selections": total_selections,
        }
    }


