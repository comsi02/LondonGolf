"""Schedule interpretation, timezone math, and tee-time search loop."""

import asyncio
import datetime as dt
import logging
import secrets
from dataclasses import dataclass
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

import httpx

from london_golf.api_client import (
    get_tee_times,
    set_lock_tee_time,
    set_shopping_cart,
)
from london_golf.cache import CacheManager
from london_golf.config_loader import AppConfig, TaskScheduleRow
from london_golf.constants import BOOK_INTERVAL, MAX_WAIT_TEETIME, WEEKDAY
from london_golf.logging_config import get_logger


def convert_tz(input_dt: Any, tz1: str, tz2: str) -> dt.datetime:
    """Convert a naive local timestamp string between IANA time zones."""
    if isinstance(input_dt, dt.datetime):
        input_dt = input_dt.strftime("%Y-%m-%d %H:%M:%S")
    parsed = dt.datetime.strptime(input_dt, "%Y-%m-%d %H:%M:%S")
    parsed = parsed.replace(tzinfo=ZoneInfo(tz1))
    return parsed.astimezone(ZoneInfo(tz2))


def convert_tz_eastern_to_utc(input_dt: Any) -> dt.datetime:
    return convert_tz(input_dt, "US/Eastern", "UTC")


def convert_tz_utc_to_eastern(input_dt: Any) -> dt.datetime:
    return convert_tz(input_dt, "UTC", "US/Eastern")


def convert_tz_utc_to_utc(input_dt: Any) -> dt.datetime:
    return convert_tz(input_dt, "UTC", "UTC")


def _resolve_book_date(schedule_info: TaskScheduleRow) -> str:
    """Return explicit book_date or default (today + BOOK_INTERVAL)."""
    if schedule_info.book_date:
        if isinstance(schedule_info.book_date, dt.date):
            return schedule_info.book_date.strftime("%Y-%m-%d")
        return str(schedule_info.book_date)
    return (dt.datetime.now() + dt.timedelta(days=BOOK_INTERVAL)).strftime("%Y-%m-%d")


def _apply_time_window(
    schedule_info: TaskScheduleRow, book_date: str, state: Dict[str, Any]
) -> None:
    """Populate UTC/Eastern booking window fields into state dictionary."""
    start_utc = convert_tz_eastern_to_utc(f"{book_date} {schedule_info.start_time}:00")
    state["bookStartTimeUtc"] = start_utc

    dur_m = schedule_info.duration
    state["bookEndTimeUtc"] = start_utc + dt.timedelta(minutes=dur_m)
    state["bookStartTimeEastern"] = convert_tz_utc_to_eastern(start_utc)
    state["bookEndTimeEastern"] = convert_tz_utc_to_eastern(state["bookEndTimeUtc"])


def _pick_course_fields(
    schedule_info: TaskScheduleRow, config: AppConfig, state: Dict[str, Any]
) -> None:
    """Choose a random course and attach code/name from config."""
    courses = (
        [schedule_info.course] if isinstance(schedule_info.course, str) else schedule_info.course
    )
    picked = secrets.choice(courses)
    state["picked_course"] = picked
    course_cfg = config.course[picked]
    state["courseCode"] = course_cfg.code
    state["courseName"] = course_cfg.name


def _log_schedule_dump(
    task_column: str, worker_id: str, state: Dict[str, Any], log: logging.Logger
) -> None:
    """Log a clean summary of the resolved schedule_info."""
    log.info(
        "[%s] Target configuration: Course: %s (%s) | Window: %s-%s EST | Target Slot Offset: %s",
        task_column.strip(),
        state.get("picked_course"),
        state.get("courseName"),
        state["bookStartTimeEastern"].strftime("%H:%M"),
        state["bookEndTimeEastern"].strftime("%H:%M"),
        state.get("slot_offset"),
    )


def _weekday_allowed(
    task_column: str, worker_id: str, state: Dict[str, Any], log: logging.Logger
) -> bool:
    """Return False if booking weekday does not match the worker's assigned weekday."""
    weekday_code = WEEKDAY[state["bookStartTimeUtc"].weekday()]
    if weekday_code == worker_id:
        log.info("[DEBUG] weekday gate OK target=%s", weekday_code)
        return True
    log.info(
        "[%s] [%s] Target day is %s. Skipping.",
        task_column.strip(),
        worker_id,
        weekday_code,
    )
    return False


def _log_tee_scan_outcome(
    log: logging.Logger, task_column: str, worker_id: str, picked_course: str, found_slot: bool
) -> None:
    task = task_column.strip()
    if found_slot:
        log.info("[%s] SUCCESS: Tee time locked and added to cart.", task)
    else:
        log.info("[%s] FAILED: No available tee times found.", task)


@dataclass(frozen=True)
class _TeeSearchContext:
    client: httpx.AsyncClient
    schedule_info: TaskScheduleRow
    state: Dict[str, Any]
    task_column: str
    worker_id: str
    book_date: str
    cart_session: str
    login_session: str
    log: logging.Logger
    cache: CacheManager


async def _process_tee_candidate(
    ctx: _TeeSearchContext,
    t_ctx: Dict[str, Any],
    selected: List[Dict[str, Any]],
) -> bool:
    tee_time_info = t_ctx["raw"]
    eastern = t_ctx["eastern"]
    east_hm = t_ctx["east_hm"]
    validation_key = t_ctx["validation_key"]
    picked = ctx.state["picked_course"]
    task = ctx.task_column.strip()

    ctx.state["teeTimeEastern"] = eastern.strftime("%Y-%m-%d %H:%M")
    tee_time_info["scheduleInfo"] = ctx.state
    selected.append(tee_time_info)
    ctx.cache.set(validation_key, "OK", 300)

    ctx.log.info("[%s]   - %s (%s) : >>> SELECTED! <<<", task, east_hm, picked)
    ctx.log.info("[%s] Executing lock+cart sequence for %s...", task, east_hm)
    lock_res = await set_lock_tee_time(ctx.client, ctx.login_session, tee_time_info, ctx.log)
    cart_res = await set_shopping_cart(ctx.client, ctx.cart_session, tee_time_info, ctx.log)

    ctx.log.info(
        "[%s] Sequence complete. Lock: HTTP %s | Cart: HTTP %s",
        task,
        lock_res.status_code,
        cart_res.status_code,
    )
    return True


async def _search_tee_times(ctx: _TeeSearchContext) -> List[Dict[str, Any]]:
    flag_tee_time = True
    idx = 0
    selected: List[Dict[str, Any]] = []

    while flag_tee_time and idx < MAX_WAIT_TEETIME:
        idx += 1
        code = str(ctx.state["courseCode"])
        tee_times = await get_tee_times(ctx.client, code, ctx.book_date, ctx.log)

        if not tee_times:
            if idx == 1 or idx % 10 == 0:
                ctx.log.info(
                    "[%s] Polling API (Attempt %s/%s) - No records found yet",
                    ctx.task_column.strip(),
                    idx,
                    MAX_WAIT_TEETIME,
                )
        else:
            start_u = ctx.state["bookStartTimeUtc"]
            end_u = ctx.state["bookEndTimeUtc"]

            valid_candidates = []

            for t in tee_times:
                parsed = dt.datetime.strptime(t["teetime"], "%Y-%m-%dT%H:%M:%S.000Z")
                tee_time = convert_tz_utc_to_utc(parsed.strftime("%Y-%m-%d %H:%M:%S"))

                if not (start_u <= tee_time <= end_u):
                    continue

                eastern = convert_tz_utc_to_eastern(tee_time)
                east_hm = eastern.strftime("%H:%M")

                rate_id = t["rates"][0]["_id"]
                east_key = eastern.strftime("%Y-%m-%d %H:%M:%S")
                validation_key = f"{rate_id}:{east_key}"
                cached = ctx.cache.get(validation_key)

                valid_candidates.append(
                    {
                        "raw": t,
                        "eastern": eastern,
                        "east_hm": east_hm,
                        "validation_key": validation_key,
                        "cached": cached,
                    }
                )

            ctx.log.info(
                "[%s] Polling API (Attempt %s/%s) - Discovered %s tee times in time window.",
                ctx.task_column.strip(),
                idx,
                MAX_WAIT_TEETIME,
                len(valid_candidates),
            )

            for c in valid_candidates:
                if c["cached"]:
                    ctx.log.info(
                        "[%s]   - %s (%s) : Cached (Skipping)",
                        ctx.task_column.strip(),
                        c["east_hm"],
                        ctx.state["picked_course"],
                    )
                else:
                    ctx.log.info(
                        "[%s]   - %s (%s) : Available",
                        ctx.task_column.strip(),
                        c["east_hm"],
                        ctx.state["picked_course"],
                    )

            fresh_candidates = [c for c in valid_candidates if not c["cached"]]

            if fresh_candidates:
                book_count = ctx.schedule_info.book_count
                slot = ctx.state["slot_offset"]

                max_start_idx = max(0, len(fresh_candidates) - book_count)
                actual_start_idx = min(slot, max_start_idx)

                targets = fresh_candidates[actual_start_idx : actual_start_idx + book_count]

                ctx.log.info(
                    "[%s] Targeting %s consecutive slots starting from index %s (Random slot was %s).",
                    ctx.task_column.strip(),
                    len(targets),
                    actual_start_idx,
                    slot,
                )

                for t_ctx in targets:
                    if await _process_tee_candidate(ctx, t_ctx, selected):
                        flag_tee_time = False

                _log_tee_scan_outcome(
                    ctx.log,
                    ctx.task_column,
                    ctx.worker_id,
                    ctx.state["picked_course"],
                    not flag_tee_time,
                )
                break

        await asyncio.sleep(1)

    ctx.log.info(
        "[%s] Search completed. Iterations: %s, Selected: %s",
        ctx.task_column.strip(),
        idx,
        len(selected),
    )
    return selected


async def get_book_schedule(
    client: httpx.AsyncClient,
    schedule_info: TaskScheduleRow,
    task_name: str,
    cart_session: str,
    login_session: str,
    config: AppConfig,
    worker_id: str,
) -> List[Dict[str, Any]]:
    """One schedule: weekday filter, API search, lock/cart on match."""
    log = get_logger()
    task = task_name.strip()
    log.info("[%s] Initializing search for %s", task, worker_id)
    cache = CacheManager(config.model_dump(), log)
    book_date = _resolve_book_date(schedule_info)

    state: Dict[str, Any] = {}
    _apply_time_window(schedule_info, book_date, state)

    task_column = f"{task_name:<10}"
    if not _weekday_allowed(task_column, worker_id, state, log):
        return []

    _pick_course_fields(schedule_info, config, state)
    state["slot_offset"] = secrets.randbelow(schedule_info.slot + 1)

    _log_schedule_dump(task_column, worker_id, state, log)

    search_ctx = _TeeSearchContext(
        client=client,
        schedule_info=schedule_info,
        state=state,
        task_column=task_column,
        worker_id=worker_id,
        book_date=book_date,
        cart_session=cart_session,
        login_session=login_session,
        log=log,
        cache=cache,
    )
    return await _search_tee_times(search_ctx)
