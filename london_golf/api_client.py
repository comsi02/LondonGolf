"""HTTP client for Kenna tee-time, cart, and lock endpoints (async via httpx)."""

import contextlib
import logging
from typing import Any, Dict, List, Mapping, MutableMapping, Union

import httpx

from london_golf.constants import ENDPOINTS, HEADERS

HeaderMap = Union[Mapping[str, str], MutableMapping[str, str]]


def _coerce_cart_int(value: Any) -> Any:
    """Cart API expects integer ids; JSON may use str or float."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    try:
        return int(str(value).strip(), 10)
    except (TypeError, ValueError):
        return value


def _cart_terms_and_conditions(tee_time_info: Dict[str, Any], rate: Dict[str, Any]) -> str:
    for src in (tee_time_info, rate):
        for key in (
            "termsAndConditions",
            "termsAndConditionsText",
            "cancellationTerms",
        ):
            val = src.get(key)
            if val:
                return str(val)
    return ""


def _cart_teetime_notes(tee_time_info: Dict[str, Any], rate: Dict[str, Any]) -> str:
    for src in (tee_time_info, rate):
        for key in (
            "teetimeNotes",
            "rateDescription",
            "description",
            "notes",
            "longDescription",
        ):
            val = src.get(key)
            if val:
                return str(val)
    return ""


def _cart_product_lineups(tee_time_info: Dict[str, Any], rate: Dict[str, Any]) -> List[Any]:
    raw = tee_time_info.get("productLineups")
    if raw is None:
        raw = rate.get("productLineups")
    if raw is None:
        raw = tee_time_info.get("featuredProducts")
    if raw is None:
        raw = rate.get("featuredProducts")
    return list(raw) if isinstance(raw, list) else []


def _redact_headers(headers: HeaderMap) -> Dict[str, str]:
    out = {str(k): str(v) for k, v in headers.items()}
    sess = out.get("Session")
    if sess:
        if len(sess) > 28:
            out["Session"] = f"{sess[:18]}…{sess[-10:]}"
        else:
            out["Session"] = "<redacted>"
    return out


def _log_rest_response(
    logger: logging.Logger,
    label: str,
    response: httpx.Response,
) -> None:
    logger.info(
        "[REST] %s <= HTTP %s",
        label,
        response.status_code,
    )


async def get_tee_times(
    client: httpx.AsyncClient, course: str, date: str, logger: logging.Logger
) -> List[Dict[str, Any]]:
    """Fetch tee times for a facility/date; unbooked foursome slots only."""
    url = ENDPOINTS["tee_time"].format(date, course)
    response = None
    try:
        response = await client.get(url, headers=HEADERS, timeout=30.0)
        response.raise_for_status()
        payload = response.json()
        tee_times = payload[0]["teetimes"]
        filtered = [
            t for t in tee_times if t.get("bookedPlayers") == 0 and t.get("maxPlayers") == 4
        ]
        return filtered
    except (httpx.RequestError, httpx.HTTPStatusError, KeyError, IndexError, TypeError) as exc:
        logger.info("========== get_tee_times error ==========")
        if response is not None:
            logger.info("status=%s", response.status_code)
            text = getattr(response, "text", "")
            logger.info("body=%s", text[:2000])
            with contextlib.suppress(ValueError):
                logger.info("json=%s", response.json())
        else:
            logger.info("no response: %s", exc)
        logger.info("========== get_tee_times error ==========")
        return []


async def set_shopping_cart(
    client: httpx.AsyncClient,
    cart_session: str,
    tee_time_info: Dict[str, Any],
    logger: logging.Logger,
) -> httpx.Response:
    """POST selected tee time into the shopping cart."""
    rate = tee_time_info["rates"][0]
    gn = rate["golfnow"]
    price = float(rate["greenFeeWalking"]) / 100.0
    players = int(rate["allowedPlayers"][-1])
    facility_id = _coerce_cart_int(gn["GolfFacilityId"])
    rate_id = _coerce_cart_int(rate["_id"])
    rate_set_id = _coerce_cart_int(gn["GolfCourseId"])
    transportation = str(rate.get("transportation") or rate.get("name") or "Walking")
    is_pnas = bool(tee_time_info.get("isPnasSelected", rate.get("isPnasSelected", False)))
    data = {
        "item": {
            "facilityId": facility_id,
            "type": "TeeTime",
            "extra": {
                "teetime": tee_time_info["teetime"],
                "players": players,
                "groupSize": 1,
                "price": price,
                "isPnasSelected": is_pnas,
                "rate": {
                    "holes": int(rate["holes"]),
                    "price": price,
                    "rateId": rate_id,
                    "rateSetId": rate_set_id,
                    "name": rate["name"],
                    "transactionFees": 0,
                    "transportation": transportation,
                    "isSimulator": bool(rate["isSimulator"]),
                },
                "productLineups": _cart_product_lineups(tee_time_info, rate),
                "termsAndConditions": _cart_terms_and_conditions(tee_time_info, rate),
                "teetimeNotes": _cart_teetime_notes(tee_time_info, rate),
            },
        }
    }
    url = ENDPOINTS["cart_item"].format(cart_session)
    logger.info(
        "[REST] cart_item => POST teetime=%s facilityId=%s rateId=%s players=%s price=%s",
        tee_time_info.get("teetime"),
        data["item"]["facilityId"],
        data["item"]["extra"]["rate"]["rateId"],
        data["item"]["extra"]["players"],
        data["item"]["extra"]["price"],
    )

    response = await client.post(url, headers=HEADERS, json=data, timeout=30.0)
    _log_rest_response(logger, "cart_item", response)
    return response


async def set_lock_tee_time(
    client: httpx.AsyncClient,
    login_session: str,
    tee_time_info: Dict[str, Any],
    logger: logging.Logger,
) -> httpx.Response:
    """Hold a tee time briefly via the lock API."""
    data = {
        "teetime": tee_time_info["teetime"],
        "slots": 4,
        "expiresIn": 5,
    }
    headers = {**HEADERS, "Session": login_session}
    url = ENDPOINTS["lock"].format(tee_time_info["courseId"])
    logger.info(
        "[REST] lock => PUT teetime=%s courseId=%s",
        tee_time_info.get("teetime"),
        tee_time_info.get("courseId"),
    )

    response = await client.put(url, headers=headers, json=data, timeout=30.0)
    _log_rest_response(logger, "lock", response)
    return response
