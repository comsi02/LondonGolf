"""CLI: parse args, login, run schedules, finalize reservation."""

import warnings

# macOS system Python often uses LibreSSL; urllib3 v2 warns but still works.
# https://github.com/urllib3/urllib3/issues/3020
warnings.filterwarnings(
    "ignore",
    message=r"urllib3 v2 only supports OpenSSL",
)

import argparse
import logging
import multiprocessing as mp
import sys
import time
import traceback
from dataclasses import dataclass
from multiprocessing import Pool
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from london_golf.browser import (
    do_login,
    get_cart_session,
    get_driver,
    get_login_session,
    quit_driver_safely,
    set_reservation_with_retry,
)
from london_golf.config_loader import (
    get_task_credentials,
    get_task_schedule_entries,
    load_config,
    resolve_default_config_path,
)
from london_golf.constants import ENDPOINTS, TIMEOUT
from london_golf.exceptions import ConfigError
from london_golf.logging_config import get_logger
from london_golf.schedule import get_book_schedule


@dataclass(frozen=True)
class ScheduleRunContext:
    """One task's schedule list: sequential or pooled workers."""

    config: Dict[str, Any]
    task_name: str
    cart_session: str
    login_session: str
    workers: int
    sequential: bool


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="London Golf Booking",
        description="London Golf Booking batch job",
    )
    parser.add_argument(
        "-d",
        "--debug",
        required=True,
        choices=["yes", "no"],
        help="yes = show browser, no = headless",
    )
    parser.add_argument(
        "-t",
        "--task",
        required=True,
        help="Schedule task name",
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=None,
        help=(
            "YAML config path (default: londonGolfBook.yaml in repo "
            "or LONDON_GOLF_CONFIG)"
        ),
    )
    parser.add_argument(
        "--sequential",
        action="store_true",
        help=(
            "Run schedule tasks in-process (one session; no parallel API)"
        ),
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        metavar="N",
        help="Pool size for parallel schedule workers (default: CPU count)",
    )
    return parser


def _resolve_worker_count(sequential: bool, workers_arg: Optional[int]) -> int:
    if sequential:
        return 1
    return workers_arg if workers_arg is not None else mp.cpu_count()


def _load_config_or_exit(config_path: Path) -> Dict[str, Any]:
    try:
        return load_config(config_path)
    except ConfigError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)


def _run_schedules(ctx: ScheduleRunContext) -> bool:
    log = logging.getLogger("london_golf")
    tasks = get_task_schedule_entries(ctx.config, ctx.task_name)
    found = False
    log.info(
        "[DEBUG] run_schedules task=%r rows=%s workers=%s sequential=%s",
        ctx.task_name,
        len(tasks),
        ctx.workers,
        ctx.sequential,
    )

    if ctx.sequential or ctx.workers <= 1:
        for row_idx, schedule_info in enumerate(tasks, start=1):
            log.info(
                "[DEBUG] row %s/%s start keys=%s",
                row_idx,
                len(tasks),
                sorted(schedule_info.keys()),
            )
            result = get_book_schedule(
                schedule_info,
                ctx.task_name,
                ctx.cart_session,
                ctx.login_session,
                ctx.config,
            )
            log.info(
                "[DEBUG] row %s/%s done selected_slots=%s",
                row_idx,
                len(tasks),
                len(result),
            )
            if result:
                found = True
                break
        return found

    log.info(
        "[DEBUG] pool start workers=%s jobs=%s (blocking .get() runs inside "
        "context so logs match real order)",
        ctx.workers,
        len(tasks),
    )
    with Pool(ctx.workers) as pool:
        async_results = [
            pool.apply_async(
                get_book_schedule,
                (
                    si,
                    ctx.task_name,
                    ctx.cart_session,
                    ctx.login_session,
                    ctx.config,
                ),
            )
            for si in tasks
        ]
        log.info(
            "[DEBUG] pool apply_async done queued=%s — next: .get() per job",
            len(async_results),
        )
        for job_i, async_result in enumerate(async_results, start=1):
            log.info(
                "[DEBUG] pool job %s/%s: AsyncResult.get() (blocks until worker "
                "returns or raises)",
                job_i,
                len(async_results),
            )
            try:
                result = async_result.get()
            except Exception:  # pylint: disable=broad-exception-caught
                log.exception(
                    "[DEBUG] pool job %s/%s failed in worker",
                    job_i,
                    len(async_results),
                )
                raise
            n_slots = len(result) if isinstance(result, list) else None
            log.info(
                "[DEBUG] pool job %s/%s returned type=%s len=%s",
                job_i,
                len(async_results),
                type(result).__name__,
                n_slots,
            )
            for _ in result:
                found = True
                break
            if found:
                break
        log.info("[DEBUG] pool collected results early_exit=%s", found)

    log.info("[DEBUG] pool closed (context exited) found=%s", found)
    return found


def _log_phase_banner(logger, *, start: bool) -> None:
    logger.info("")
    logger.info("#---------------------------------------------------#")
    if start:
        logger.info("#                     START                         #")
    else:
        logger.info("#                      END                          #")
    logger.info("#---------------------------------------------------#")
    logger.info("")


def _log_traceback(logger: logging.Logger, traceback_msg: str) -> None:
    sep = "[ERROR]" + "-" * 100
    logger.info("%s", sep)
    logger.info("%s", traceback_msg)
    logger.info("%s", sep)
    print(sep, file=sys.stderr)
    print(traceback_msg, file=sys.stderr)
    print(sep, file=sys.stderr)


def _open_browser_session(
    debug_mode: bool,
    login_uid: str,
    login_pwd: str,
    task_name: str,
    logger: logging.Logger,
) -> Tuple[Any, str, str]:
    task_col = f"{task_name:<10}"
    logger.info(
        "[DEBUG] opening browser headless=%s login_url=%s",
        not debug_mode,
        ENDPOINTS["login"],
    )
    driver = get_driver(not debug_mode)
    logger.info("[DEBUG] logging in as %s", login_uid)
    do_login(driver, ENDPOINTS["login"], login_uid, login_pwd)
    logger.info("* [%s] (Done.) login : %s", task_col, login_uid)
    cart_session = get_cart_session(driver, logger)
    logger.info(
        "* [%s] (Done.) get cart session : %s",
        task_col,
        cart_session,
    )
    login_session = get_login_session(driver)
    logger.info(
        "* [%s] (Done.) get login session : %s...%s",
        task_col,
        login_session[:20],
        login_session[-20:],
    )
    return driver, cart_session, login_session


def _finalize_schedules_and_checkout(
    logger: logging.Logger,
    args: argparse.Namespace,
    config: Dict[str, Any],
    task_name: str,
    driver: Any,
    cart_session: str,
    login_session: str,
) -> None:
    workers = _resolve_worker_count(args.sequential, args.workers)
    task_col = f"{task_name:<10}"
    logger.info(
        "* [%s] workers=%s sequential=%s cpu_count=%s",
        task_col,
        workers,
        args.sequential,
        mp.cpu_count(),
    )
    ctx = ScheduleRunContext(
        config=config,
        task_name=task_name,
        cart_session=cart_session,
        login_session=login_session,
        workers=workers,
        sequential=args.sequential,
    )
    if _run_schedules(ctx):
        logger.info("* [%s] (Start) set reservation with retry.", task_col)
        set_reservation_with_retry(driver, task_name)
        logger.info("* [%s] (Done.) set reservation with retry.", task_col)
        time.sleep(TIMEOUT)
    else:
        logger.info(
            "[DEBUG] task=%r: no slot locked/carted — check weekday, time "
            "window, API empty responses, lock/cart HTTP status in logs above",
            task_name,
        )
        logger.info(
            "* [%s] Skip checkout (nothing in cart from workers).",
            task_col,
        )
    _log_phase_banner(logger, start=False)


def main() -> None:
    """Load config, sessions, workers; checkout if a slot was found."""
    logger = get_logger()
    driver = None
    try:
        args = _build_argument_parser().parse_args()
        cfg_path = args.config or resolve_default_config_path()
        config = _load_config_or_exit(cfg_path)
        task_name = args.task
        logger.info(
            "[DEBUG] config_path=%s task=%r debug=%s",
            cfg_path,
            task_name,
            args.debug,
        )
        login_uid, login_pwd = get_task_credentials(config, task_name)
        _log_phase_banner(logger, start=True)
        driver, cart_session, login_session = _open_browser_session(
            args.debug == "yes", login_uid, login_pwd, task_name, logger
        )
        _finalize_schedules_and_checkout(
            logger,
            args,
            config,
            task_name,
            driver,
            cart_session,
            login_session,
        )

    except ConfigError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception:  # pylint: disable=broad-exception-caught
        traceback_msg = f"Traceback: {traceback.format_exc()}"
        _log_traceback(logger, traceback_msg)
    finally:
        if driver is not None:
            quit_driver_safely(driver)


if __name__ == "__main__":
    main()
