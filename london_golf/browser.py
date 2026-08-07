"""Playwright helpers: login, sessions, and checkout UI flow."""

import asyncio
import logging
from typing import Tuple

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

from london_golf.constants import ENDPOINTS
from london_golf.exceptions import (
    AuthenticationError,
    CartError,
    ReservationError,
)

logger = logging.getLogger("london_golf")


async def do_login_and_get_sessions(
    page: Page,
    login_url: str,
    login_uid: str,
    login_pwd: str,
) -> Tuple[str, str]:
    """Fill login form, submit, and intercept Session and cart identifiers."""
    login_session = ""
    cart_session = ""

    async def handle_request(request):
        nonlocal login_session, cart_session
        headers = request.headers

        # Extract Session token from any request that has it
        if not login_session and "session" in headers:
            login_session = headers["session"]

        # Extract cart session id
        if ENDPOINTS["cart"] in request.url:
            cart_session = request.url.split("/")[-1]

    page.on("request", handle_request)

    try:
        await page.set_viewport_size({"width": 500, "height": 1000})
        await page.goto(login_url, wait_until="domcontentloaded")

        await page.fill("[data-testid='login-email-component']", login_uid)
        await page.fill("[data-testid='login-password-component']", login_pwd)
        await page.click("[data-testid='login-button']")

        # Wait until we see a successful navigation
        await page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(2)

        # If cart session is not found, force a refresh or navigation to trigger it
        if not cart_session:
            await page.reload(wait_until="domcontentloaded")

        # Wait a bit if it's still not populated
        for _ in range(10):
            if login_session and cart_session:
                break
            await asyncio.sleep(0.5)

    except PlaywrightError as exc:
        raise AuthenticationError(f"Login failed: {exc}") from exc

    if not login_session:
        raise AuthenticationError("Could not get login session")
    if not cart_session:
        raise CartError("Could not get cart session")

    return login_session, cart_session


async def set_reservation(page: Page, task_name: str) -> None:
    """Checkout: cart, checkout, waiver checkbox, confirm reservation."""
    tn = task_name.strip()
    try:
        await page.reload(wait_until="domcontentloaded")
        await asyncio.sleep(2)

        logger.info("[%s] + reservation.: click shopping cart button", tn)
        await page.click("[data-testid='shopping-cart-button']")

        logger.info("[%s] + reservation.: click checkout button", tn)
        await page.click("[data-testid='shopping-cart-drawer-checkout-btn']")

        logger.info("[%s] + reservation.: click checkbox", tn)
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.click("input[name='chb-nm']")

        logger.info("[%s] + reservation.: click the reservation button", tn)
        await page.click("[data-testid='make-your-reservation-btn']")

        logger.info("[%s] + reservation.: completed.", tn)
    except PlaywrightError as exc:
        detail = f"Failed to complete reservation UI step. url={page.url}\nError: {exc}"
        raise ReservationError(detail) from exc


async def set_reservation_with_retry(page: Page, task_name: str, max_retries: int = 5) -> None:
    """Run `set_reservation` with retries on transient UI failures."""
    tn = task_name.strip()
    for attempt in range(max_retries):
        try:
            logger.info(
                "[%s] (Attempt %s/%s) Starting reservation process",
                tn,
                attempt + 1,
                max_retries,
            )
            await set_reservation(page, task_name)
            logger.info(
                "[%s] (Success) Reservation completed on attempt %s",
                tn,
                attempt + 1,
            )
            return
        except ReservationError as exc:
            if attempt < max_retries - 1:
                logger.info(
                    "[%s] (Attempt %s/%s) Failed: %s. Retrying...",
                    tn,
                    attempt + 1,
                    max_retries,
                    exc,
                )
                await asyncio.sleep(1)
            else:
                logger.info(
                    "[%s] (Failed) All %s attempts failed. Last error: %s",
                    tn,
                    max_retries,
                    exc,
                )
                raise ReservationError(
                    f"Failed to complete reservation after {max_retries} attempts: {exc}"
                ) from exc
