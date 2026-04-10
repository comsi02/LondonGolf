"""Selenium (selenium-wire) helpers: login, sessions, and checkout UI flow."""

import contextlib
import logging
import time
from typing import Any, cast

from selenium.common.exceptions import (
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from seleniumwire import webdriver

from london_golf.constants import ENDPOINTS, TIMEOUT
from london_golf.exceptions import (
    AuthenticationError,
    CartError,
    ReservationError,
)


def _driver_page_brief(driver: webdriver.Chrome) -> str:
    """Best-effort URL/title for logs when a step fails."""
    try:
        return f"url={driver.current_url!r} title={driver.title!r}"
    except WebDriverException:
        return "url/title: unreadable (session may be invalid)"


def _format_webdriver_error(
    exc: BaseException, *, max_stacktrace_chars: int = 1200
) -> str:
    """Readable Selenium error; str(exc) often has empty Message: but huge stack."""
    lines = [f"exception_type={type(exc).__name__}"]
    if not isinstance(exc, WebDriverException):
        lines.append(str(exc))
        return "\n".join(lines)

    wde = cast(WebDriverException, exc)
    lines.append(f"driver_msg={wde.msg!r}")
    if wde.stacktrace:
        joined = (
            "\n".join(wde.stacktrace)
            if isinstance(wde.stacktrace, (list, tuple))
            else str(wde.stacktrace)
        )
        if len(joined) > max_stacktrace_chars:
            joined = (
                joined[:max_stacktrace_chars]
                + "\n… [stacktrace truncated for log length]"
            )
        lines.append("stacktrace:\n" + joined)
    if wde.screen:
        lines.append(
            "screenshot: captured by driver (base64 omitted from logs)"
        )
    return "\n".join(lines)


def quit_driver_safely(driver: Any) -> None:
    """Quit driver; ignore WebDriverException if session is gone."""
    with contextlib.suppress(WebDriverException):
        driver.quit()


def get_driver(is_headless: bool = False) -> webdriver.Chrome:
    """Create Chrome webdriver; optional headless; selenium-wire enabled."""
    options = webdriver.ChromeOptions()
    if is_headless:
        options.add_argument("--headless")
    return webdriver.Chrome(options=options, seleniumwire_options={})


def do_login(
    driver: webdriver.Chrome,
    login_url: str,
    login_uid: str,
    login_pwd: str,
) -> None:
    """Fill login form and submit."""
    try:
        driver.set_window_size(500, 1000)
        driver.get(login_url)
        driver.implicitly_wait(TIMEOUT)
        WebDriverWait(driver, TIMEOUT).until(
            EC.presence_of_element_located(
                (By.XPATH, "//input[@data-testid='login-email-component']")
            )
        ).send_keys(login_uid)
        WebDriverWait(driver, TIMEOUT).until(
            EC.presence_of_element_located(
                (By.XPATH, "//input[@data-testid='login-password-component']")
            )
        ).send_keys(login_pwd)
        WebDriverWait(driver, TIMEOUT).until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[@data-testid='login-button']")
            )
        ).click()
    except (WebDriverException, TimeoutException) as exc:
        raise AuthenticationError(f"Login failed: {exc}") from exc


def get_cart_session_request(
    driver: webdriver.Chrome, logger: logging.Logger
) -> Any:
    """Wait for course/cart network calls; return the cart request object."""
    try:
        driver.wait_for_request(ENDPOINTS["course"], TIMEOUT)
        driver.refresh()
        return driver.wait_for_request(ENDPOINTS["cart"], TIMEOUT)
    except TimeoutException as exc:
        logger.info("* Exception occurred: %s", exc)
        raise CartError(f"Failed to get cart session request: {exc}") from exc


def get_cart_session(driver: webdriver.Chrome, logger: logging.Logger) -> str:
    """Extract shopping-cart session id from the captured cart request path."""
    return get_cart_session_request(driver, logger).path.split("/")[-1]


def get_login_session(driver: webdriver.Chrome) -> str:
    """Read Session header from a successful captured request."""
    for request in driver.requests:
        if (
            request.response
            and request.response.status_code == 200
            and request.headers.get("Session")
        ):
            return request.headers["Session"]
    raise AuthenticationError("Could not get login session")


def set_reservation(driver: webdriver.Chrome, task_name: str) -> None:
    """Checkout: cart, checkout, waiver checkbox, confirm reservation."""
    try:
        driver.refresh()
        driver.implicitly_wait(TIMEOUT)
        time.sleep(2)
        logger = logging.getLogger("london_golf")
        tn = f"{task_name:<10}"
        logger.info("* [%s] + reservation.: click shopping cart button", tn)
        WebDriverWait(driver, TIMEOUT).until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[@data-testid='shopping-cart-button']")
            )
        ).click()
        logger.info("* [%s] + reservation.: click checkout button", tn)
        WebDriverWait(driver, TIMEOUT).until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//button[@data-testid="
                    "'shopping-cart-drawer-checkout-btn']",
                )
            )
        ).click()
        logger.info("* [%s] + reservation.: click checkbox", tn)
        driver.execute_script("window.scrollTo(0,document.body.scrollHeight)")
        driver.find_element(By.NAME, "chb-nm").click()
        logger.info("* [%s] + reservation.: click the reservation button", tn)
        WebDriverWait(driver, TIMEOUT).until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//button[@data-testid='make-your-reservation-btn']",
                )
            )
        ).click()
        logger.info("* [%s] + reservation.: completed.", tn)
    except (WebDriverException, TimeoutException) as exc:
        detail = "\n".join(
            (
                "Failed to complete reservation UI step.",
                _driver_page_brief(driver),
                _format_webdriver_error(exc),
            )
        )
        raise ReservationError(detail) from exc


def set_reservation_with_retry(
    driver: webdriver.Chrome, task_name: str, max_retries: int = 5
) -> None:
    """Run `set_reservation` with retries on transient UI failures."""
    logger = logging.getLogger("london_golf")
    tn = f"{task_name:<10}"
    for attempt in range(max_retries):
        try:
            logger.info(
                "* [%s] (Attempt %s/%s) Starting reservation process",
                tn,
                attempt + 1,
                max_retries,
            )
            set_reservation(driver, task_name)
            logger.info(
                "* [%s] (Success) Reservation completed on attempt %s",
                tn,
                attempt + 1,
            )
            return
        except ReservationError as exc:
            if attempt < max_retries - 1:
                logger.info(
                    "* [%s] (Attempt %s/%s) Failed: %s. Retrying...",
                    tn,
                    attempt + 1,
                    max_retries,
                    exc,
                )
                time.sleep(1)
            else:
                logger.info(
                    "* [%s] (Failed) All %s attempts failed. Last error: %s",
                    tn,
                    max_retries,
                    exc,
                )
                raise ReservationError(
                    f"Failed to complete reservation after {max_retries} "
                    f"attempts: {exc}"
                ) from exc
