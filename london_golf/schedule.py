"""Schedule interpretation, timezone math, and tee-time search loop."""

import datetime as dt
import logging
import multiprocessing as mp
import random
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Set

import pytz

from london_golf.api_client import (
    get_tee_times,
    set_lock_tee_time,
    set_shopping_cart,
)
from london_golf.cache import CacheManager
from london_golf.constants import BOOK_INTERVAL, MAX_WAIT_TEETIME, WEEKDAY
from london_golf.logging_config import get_logger


def normalize_weekday(value: Any) -> Set[str]:
    """Parse weekday from YAML string, list, or None; uppercase codes."""
    if value is None or value == "":
        return set()
    if isinstance(value, (list, tuple)):
        parts = [str(x).strip() for x in value if str(x).strip()]
    else:
        parts = [p.strip() for p in str(value).split(",") if p.strip()]
    return {p.upper() for p in parts}


def convert_tz(input_dt: Any, tz1: str, tz2: str) -> dt.datetime:
    """Convert a naive local timestamp string between IANA time zones."""
    if isinstance(input_dt, dt.datetime):
        input_dt = input_dt.strftime("%Y-%m-%d %H:%M:%S")
    tz1_obj = pytz.timezone(tz1)
    tz2_obj = pytz.timezone(tz2)
    parsed = dt.datetime.strptime(input_dt, "%Y-%m-%d %H:%M:%S")
    parsed = tz1_obj.localize(parsed)
    return parsed.astimezone(tz2_obj)


def convert_tz_eastern_to_utc(input_dt: Any) -> dt.datetime:
    """Convert US Eastern time to UTC."""
    return convert_tz(input_dt, "US/Eastern", "UTC")


def convert_tz_utc_to_eastern(input_dt: Any) -> dt.datetime:
    """Convert UTC to US Eastern time."""
    return convert_tz(input_dt, "UTC", "US/Eastern")


def convert_tz_utc_to_utc(input_dt: Any) -> dt.datetime:
    """Normalize a UTC wall time through the same parsing path."""
    return convert_tz(input_dt, "UTC", "UTC")


def _resolve_book_date(schedule_info: Dict[str, Any]) -> str:
    """Return explicit book_date or default (today + BOOK_INTERVAL)."""
    return schedule_info.get("book_date") or (
        dt.datetime.now() + dt.timedelta(days=BOOK_INTERVAL)
    ).strftime("%Y-%m-%d")


def _apply_time_window(schedule_info: Dict[str, Any], book_date: str) -> None:
    """Populate UTC/Eastern booking window fields on schedule_info."""
    buf_hi = schedule_info.get("buffer", 0) + 1
    schedule_info["bufferTime"] = random.randrange(0, buf_hi)
    schedule_info["bookStartTimeUtc"] = convert_tz_eastern_to_utc(
        f"{book_date} {schedule_info['start_time']}:00"
    ) + dt.timedelta(minutes=schedule_info["bufferTime"])
    start_utc = schedule_info["bookStartTimeUtc"]
    dur_m = schedule_info.get("duration", 30)
    schedule_info["bookEndTimeUtc"] = start_utc + dt.timedelta(minutes=dur_m)
    schedule_info["bookStartTimeEastern"] = convert_tz_utc_to_eastern(
        start_utc
    )
    end_utc = schedule_info["bookEndTimeUtc"]
    schedule_info["bookEndTimeEastern"] = convert_tz_utc_to_eastern(end_utc)


def _pick_course_fields(
    schedule_info: Dict[str, Any], config: Dict[str, Any]
) -> None:
    """Choose a random course and attach code/name from config."""
    schedule_info["picked_course"] = random.choice(schedule_info["course"])
    picked = schedule_info["picked_course"]
    course_cfg = config["course"][picked]
    schedule_info["courseCode"] = course_cfg["code"]
    schedule_info["courseName"] = course_cfg["name"]


def _log_schedule_dump(
    task_column: str,
    proc_name: str,
    schedule_info: Dict[str, Any],
    log: logging.Logger,
) -> None:
    """Log a multi-line dump of resolved schedule_info."""
    pad = " " * 26
    lines = ["", "-" * 100]
    lines.extend(
        (
            f"{pad}[{task_column}] [{proc_name}] * {k:<20} : {v}"
            for k, v in schedule_info.items()
        )
    )
    lines.append("-" * 100)
    log.info("\n".join(lines))


def _weekday_allowed(
    task_column: str,
    proc_name: str,
    schedule_info: Dict[str, Any],
    allowed: Set[str],
    log: logging.Logger,
) -> bool:
    """Return False if booking weekday is not in the configured set."""
    weekday_code = WEEKDAY[schedule_info["bookStartTimeUtc"].weekday()]
    if weekday_code in allowed:
        log.info(
            "[DEBUG] weekday gate OK target=%s allowed=%s",
            weekday_code,
            sorted(allowed),
        )
        return True
    log.info(
        "* [%s] [%s] [%s] %s is not in %s",
        task_column,
        proc_name,
        schedule_info["picked_course"],
        weekday_code,
        sorted(allowed),
    )
    return False


def _log_tee_scan_outcome(
    log: logging.Logger,
    task_column: str,
    proc_name: str,
    picked_course: str,
    found_slot: bool,
) -> None:
    """Log whether the scan pass found a matching tee time."""
    prefix = f"* [{task_column}] [{proc_name}] [{picked_course}]"
    log.info("%s", prefix)
    if found_slot:
        log.info("%s >>>>>>>>>> found teetime <<<<<<<<<<", prefix)
    else:
        log.info("%s >>>>>>>>>> Couldn't find any teetime <<<<<<<<<<", prefix)
    log.info("%s", prefix)


@dataclass(frozen=True)
class _TeeSearchContext:
    """Context for tee-time polling and lock/cart for one schedule row."""

    schedule_info: Dict[str, Any]
    task_column: str
    proc_name: str
    book_date: str
    cart_session: str
    login_session: str
    log: logging.Logger
    cache: CacheManager


def _process_tee_candidate(
    ctx: _TeeSearchContext,
    tee_time_info: Dict[str, Any],
    selected: List[Dict[str, Any]],
) -> bool:
    """One tee row; True if locked and added to cart."""
    schedule_info = ctx.schedule_info
    raw_tt = tee_time_info["teetime"]
    parsed = dt.datetime.strptime(raw_tt, "%Y-%m-%dT%H:%M:%S.000Z")
    tee_time = convert_tz_utc_to_utc(parsed.strftime("%Y-%m-%d %H:%M:%S"))
    eastern = convert_tz_utc_to_eastern(tee_time)
    picked = schedule_info["picked_course"]
    bse_hm = schedule_info["bookStartTimeEastern"].strftime("%H:%M")
    bee_hm = schedule_info["bookEndTimeEastern"].strftime("%H:%M")
    east_hm = eastern.strftime("%H:%M")
    log_str = (
        f"* [{ctx.task_column}] [{ctx.proc_name}] [{picked}] "
        f"{bse_hm} <= {east_hm} <= {bee_hm}"
    )

    start_u = schedule_info["bookStartTimeUtc"]
    end_u = schedule_info["bookEndTimeUtc"]
    if not (start_u <= tee_time <= end_u):
        ctx.log.info("%s", log_str)
        return False

    rate_id = tee_time_info["rates"][0]["_id"]
    east_key = eastern.strftime("%Y-%m-%d %H:%M:%S")
    validation_key = f"{rate_id}:{east_key}"
    cached = ctx.cache.get(validation_key)
    book_cap = schedule_info.get("book_count", 1)

    if len(selected) < book_cap and cached is None:
        schedule_info["teeTimeEastern"] = eastern.strftime("%Y-%m-%d %H:%M")
        tee_time_info["scheduleInfo"] = schedule_info
        selected.append(tee_time_info)
        ctx.cache.set(validation_key, "OK", 300)
        ctx.log.info(
            "[DEBUG] schedule: calling lock+cart teetime=%s courseId=%s "
            "cart_session_suffix=%s",
            tee_time_info.get("teetime"),
            tee_time_info.get("courseId"),
            (ctx.cart_session or "")[-12:],
        )
        lock_res = set_lock_tee_time(
            ctx.login_session, tee_time_info, ctx.log
        )
        if lock_res.status_code >= 300:
            ctx.log.info(
                "[DEBUG] lock HTTP %s teetime=%s snip=%s",
                lock_res.status_code,
                tee_time_info.get("teetime"),
                (lock_res.text or "")[:500],
            )
        cart_res = set_shopping_cart(ctx.cart_session, tee_time_info, ctx.log)
        if cart_res.status_code >= 300:
            ctx.log.info(
                "[DEBUG] cart HTTP %s teetime=%s snip=%s",
                cart_res.status_code,
                tee_time_info.get("teetime"),
                (cart_res.text or "")[:500],
            )
        ctx.log.info(
            "%s [Valid] [Selected] [lock:%s & cart:%s]",
            log_str,
            lock_res.status_code,
            cart_res.status_code,
        )
        return True
    if cached is None:
        ctx.log.info("%s [Valid]", log_str)
    else:
        ctx.log.info("%s [Valid] [Cache]", log_str)
    return False


def _search_tee_times(ctx: _TeeSearchContext) -> List[Dict[str, Any]]:
    """Poll until a tee is locked/carted or attempts run out."""
    flag_tee_time = True
    idx = 0
    selected: List[Dict[str, Any]] = []

    while flag_tee_time and idx < MAX_WAIT_TEETIME:
        idx += 1
        code = ctx.schedule_info["courseCode"]
        if idx <= 5 or idx % 10 == 0:
            ctx.log.info(
                "[DEBUG] before get_tee_times iter=%s/%s facility=%s date=%s",
                idx,
                MAX_WAIT_TEETIME,
                code,
                ctx.book_date,
            )
        tee_times = get_tee_times(code, ctx.book_date, ctx.log)
        if idx <= 5 or idx % 10 == 0:
            ctx.log.info(
                "[DEBUG] after get_tee_times iter=%s/%s n_rows=%s",
                idx,
                MAX_WAIT_TEETIME,
                len(tee_times),
            )
        ctx.log.info(
            "* [%s] [%s] %s time(s) attempted",
            ctx.task_column,
            ctx.proc_name,
            idx,
        )

        for tee_time_info in tee_times:
            if _process_tee_candidate(ctx, tee_time_info, selected):
                flag_tee_time = False

        if tee_times:
            _log_tee_scan_outcome(
                ctx.log,
                ctx.task_column,
                ctx.proc_name,
                ctx.schedule_info["picked_course"],
                not flag_tee_time,
            )
            break
        if idx <= 3 or idx % 15 == 0:
            ctx.log.info(
                "[DEBUG] poll_iter=%s API returned 0 rows facility=%s date=%s",
                idx,
                code,
                ctx.book_date,
            )
        time.sleep(1)

    ctx.log.info(
        "[DEBUG] tee search done iterations=%s selected_count=%s "
        "facility=%s date=%s",
        idx,
        len(selected),
        ctx.schedule_info["courseCode"],
        ctx.book_date,
    )
    return selected


def get_book_schedule(
    schedule_info: Dict[str, Any],
    task_name: str,
    cart_session: str,
    login_session: str,
    config: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """One schedule: weekday filter, API search, lock/cart on match."""
    if isinstance(schedule_info.get("course"), str):
        schedule_info["course"] = [schedule_info["course"]]
    proc = mp.current_process()
    # Pool workers are new processes (spawn): configure file logger like main.
    log = get_logger()
    log.info(
        "[DEBUG] get_book_schedule start task=%s proc=%s weekday_yaml=%r",
        task_name,
        proc.name,
        schedule_info.get("weekday"),
    )
    cache = CacheManager(config, log)
    allowed = normalize_weekday(schedule_info.get("weekday"))
    book_date = _resolve_book_date(schedule_info)
    log.info(
        "[DEBUG] book_date=%s allowed_weekdays=%s course_choices=%s",
        book_date,
        sorted(allowed),
        schedule_info["course"],
    )
    _apply_time_window(schedule_info, book_date)
    _pick_course_fields(schedule_info, config)
    task_column = f"{task_name:<10}"
    log.info(
        "[DEBUG] random_pick course=%s facility_id=%s eastern_window=%s-%s "
        "buffer_min=%s",
        schedule_info["picked_course"],
        schedule_info["courseCode"],
        schedule_info["bookStartTimeEastern"].strftime("%H:%M"),
        schedule_info["bookEndTimeEastern"].strftime("%H:%M"),
        schedule_info.get("bufferTime"),
    )

    _log_schedule_dump(task_column, proc.name, schedule_info, log)
    if not _weekday_allowed(
        task_column, proc.name, schedule_info, allowed, log
    ):
        return []

    search_ctx = _TeeSearchContext(
        schedule_info=schedule_info,
        task_column=task_column,
        proc_name=proc.name,
        book_date=book_date,
        cart_session=cart_session,
        login_session=login_session,
        log=log,
        cache=cache,
    )
    return _search_tee_times(search_ctx)
