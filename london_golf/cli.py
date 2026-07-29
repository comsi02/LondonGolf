"""CLI: parse args, login, run schedules, finalize reservation (Async)."""

import argparse
import asyncio
import datetime as dt
import logging
import sys
import traceback
from pathlib import Path

import httpx
from playwright.async_api import async_playwright

from london_golf.browser import (
    do_login_and_get_sessions,
    set_reservation_with_retry,
)
from london_golf.config_loader import (
    AppConfig,
    get_task_credentials,
    get_task_schedule_entries,
    load_config,
    resolve_default_config_path,
)
from london_golf.constants import BOOK_INTERVAL, ENDPOINTS, TIMEOUT, WEEKDAY
from london_golf.exceptions import ConfigError
from london_golf.logging_config import get_logger
from london_golf.schedule import get_book_schedule


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="London Golf Booking",
        description="London Golf Booking batch job",
    )
    parser.add_argument(
        "task",
        help="Schedule task name (e.g. pro_song)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run the browser in background without showing the UI",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip checkout (dry run mode)",
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=None,
        help="YAML config path",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        metavar="N",
        help="Ignored in asyncio mode (all tasks run concurrently)",
    )
    return parser


def _load_config_or_exit(config_path: Path) -> AppConfig:
    try:
        return load_config(config_path)
    except ConfigError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)


def _log_phase_banner(logger: logging.Logger, task_name: str, *, start: bool) -> None:
    label = "START" if start else "END"
    logger.info(
        "[%s] -------------------------------- %s --------------------------------",
        task_name,
        label,
    )


def _log_traceback(logger: logging.Logger, traceback_msg: str) -> None:
    sep = "[ERROR]" + "-" * 100
    logger.info("%s", sep)
    logger.info("%s", traceback_msg)
    logger.info("%s", sep)
    print(sep, file=sys.stderr)
    print(traceback_msg, file=sys.stderr)
    print(sep, file=sys.stderr)


async def _run_schedules_async(
    client: httpx.AsyncClient,
    config: AppConfig,
    task_name: str,
    tasks_dict: dict,
    cart_session: str,
    login_session: str,
    logger: logging.Logger,
) -> bool:
    found = False

    target_date = dt.datetime.now() + dt.timedelta(days=BOOK_INTERVAL)
    default_target = WEEKDAY[target_date.weekday()]

    logger.info(
        "[%s] Target booking date: %s (%s)",
        task_name,
        target_date.strftime("%Y-%m-%d"),
        default_target,
    )

    for weekday, schedule_info in tasks_dict.items():
        # If no explicit book_date override, only execute the default target weekday
        if not schedule_info.book_date and weekday != default_target:
            continue

        result = await get_book_schedule(
            client, schedule_info, task_name, cart_session, login_session, config, weekday
        )
        if result:
            found = True
            break
    return found


async def async_main() -> None:
    logger = get_logger()
    args = _build_argument_parser().parse_args()
    cfg_path = args.config or resolve_default_config_path()
    config = _load_config_or_exit(cfg_path)
    task_name = args.task
    _log_phase_banner(logger, task_name, start=True)

    logger.info("[%s] Initializing... Headless: %s", task_name, args.headless)
    login_uid, login_pwd = get_task_credentials(config, task_name)

    is_headless = args.headless

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=is_headless)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            logger.info("[%s] Authenticating as %s...", task_name, login_uid)
            login_session, cart_session = await do_login_and_get_sessions(
                page, ENDPOINTS["login"], login_uid, login_pwd
            )
            logger.info(
                "[%s] Acquired login session: %s...%s",
                task_name,
                login_session[:10],
                login_session[-10:],
            )
            logger.info("[%s] Acquired cart session: %s", task_name, cart_session)

            tasks_dict = get_task_schedule_entries(config, task_name)
            logger.info("[%s] Loaded %s scheduled tasks", task_name, len(tasks_dict))

            async with httpx.AsyncClient() as client:
                found = await _run_schedules_async(
                    client, config, task_name, tasks_dict, cart_session, login_session, logger
                )

            if found:
                if not args.dry_run:
                    logger.info("[%s] Executing checkout sequence...", task_name)
                    await set_reservation_with_retry(page, task_name)
                    logger.info("[%s] Checkout sequence completed successfully.", task_name)
                    await asyncio.sleep(TIMEOUT)
                else:
                    logger.info("[%s] --dry-run active. Skipping actual checkout.", task_name)
            else:
                logger.info("[%s] No tee times locked. Skipping checkout.", task_name)

        except Exception:
            traceback_msg = f"Traceback: {traceback.format_exc()}"
            _log_traceback(logger, traceback_msg)
        finally:
            await context.close()
            await browser.close()
            logger.info("[%s] Session closed.", task_name)
            _log_phase_banner(logger, task_name, start=False)


def main() -> None:
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        sys.exit(1)


if __name__ == "__main__":
    main()
