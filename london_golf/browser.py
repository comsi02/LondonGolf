import asyncio
import datetime as dt
import logging
from pathlib import Path
from typing import Optional, Tuple

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page, Response

from london_golf.constants import ENDPOINTS
from london_golf.exceptions import (
    AuthenticationError,
    CartError,
    ReservationError,
)

logger = logging.getLogger("london_golf")


async def _take_debug_screenshot(page: Page, task_name: str, stage: str) -> Optional[str]:
    """Capture a full-page screenshot into logs/ for debugging."""
    try:
        log_dir = Path(__file__).resolve().parent.parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        now_str = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = log_dir / f"screenshot_{task_name}_{now_str}_{stage}.png"
        await page.screenshot(path=str(filepath), full_page=True)
        logger.info("[%s] Screenshot saved: %s", task_name, filepath)
        return str(filepath)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("[%s] Failed to save screenshot (%s): %s", task_name, stage, exc)
        return None


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
    """Checkout: cart, checkout, waiver checkbox, confirm reservation and verify completion."""
    tn = task_name.strip()
    try:
        await page.reload(wait_until="domcontentloaded")
        await asyncio.sleep(2)

        logger.info("[%s] + reservation.: click shopping cart button", tn)
        cart_btn = page.locator("[data-testid='shopping-cart-button']")
        await cart_btn.wait_for(state="visible", timeout=10000)
        await cart_btn.click()

        logger.info("[%s] + reservation.: click checkout button", tn)
        checkout_btn = page.locator("[data-testid='shopping-cart-drawer-checkout-btn']")
        await checkout_btn.wait_for(state="visible", timeout=10000)
        await checkout_btn.click()

        logger.info("[%s] + reservation.: verifying terms and conditions checkbox", tn)
        checkbox = page.locator("input[name='chb-nm']")
        await checkbox.wait_for(state="attached", timeout=15000)
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await checkbox.scroll_into_view_if_needed()

        # Ensure checkbox is checked
        if not await checkbox.is_checked():
            await checkbox.check(force=True)
        if not await checkbox.is_checked():
            await checkbox.click(force=True)

        if not await checkbox.is_checked():
            await _take_debug_screenshot(page, tn, "checkbox_failed")
            raise ReservationError("Failed to check terms and conditions checkbox.")

        logger.info("[%s] + reservation.: terms checkbox confirmed (checked=True)", tn)

        res_btn = page.locator("[data-testid='make-your-reservation-btn']")
        await res_btn.wait_for(state="visible", timeout=10000)

        # Track network responses during reservation request
        captured_responses: list[Response] = []

        def handle_response(resp: Response):
            if any(k in resp.url for k in ("shopping-cart", "reservation", "checkout", "booking")):
                captured_responses.append(resp)

        page.on("response", handle_response)

        logger.info("[%s] + reservation.: click the reservation button", tn)
        await res_btn.click()

        # Wait for either completion UI / URL change or error notification
        confirmed = False
        error_message = ""

        # Poll for up to 15 seconds for reservation outcome
        for _ in range(30):
            await asyncio.sleep(0.5)

            # Check for error alert/messages in the DOM
            alerts = page.locator("[role='alert'], .MuiAlert-message, [data-testid*='error'], .error-message, .toast")
            if await alerts.count() > 0:
                for idx in range(await alerts.count()):
                    alert_elem = alerts.nth(idx)
                    if await alert_elem.is_visible():
                        txt = (await alert_elem.inner_text()).strip()
                        if txt:
                            error_message = txt
                            break
            if error_message:
                break

            # Check network errors
            for resp in captured_responses:
                if resp.status >= 400:
                    try:
                        err_body = await resp.text()
                    except Exception:
                        err_body = ""
                    error_message = f"API Error (HTTP {resp.status}) on {resp.url}: {err_body[:200]}"
                    break
            if error_message:
                break

            # Check for success indicators
            # 1. URL change
            current_url = page.url.lower()
            if any(term in current_url for term in ("confirmation", "success", "receipt", "order")):
                confirmed = True
                break

            # 2. Confirmation element / text
            confirm_elem = page.locator(
                "[data-testid*='confirmation'], [data-testid*='success'], text=/Reservation Confirmation|Booking Confirmed|Thank you/i"
            )
            if await confirm_elem.count() > 0 and await confirm_elem.first.is_visible():
                confirmed = True
                break

            # 3. Successful checkout API response
            for resp in captured_responses:
                if "checkout" in resp.url and resp.status in (200, 201, 204):
                    confirmed = True
                    break
            if confirmed:
                break

        if error_message:
            await _take_debug_screenshot(page, tn, "failed_error_message")
            raise ReservationError(f"Reservation failed: {error_message}")

        if not confirmed:
            # Take a screenshot to record the exact UI state upon timeout
            await _take_debug_screenshot(page, tn, "failed_timeout")
            raise ReservationError("Timed out waiting for reservation confirmation.")

        await _take_debug_screenshot(page, tn, "success")
        logger.info("[%s] + reservation.: verified and completed successfully.", tn)

    except PlaywrightError as exc:
        await _take_debug_screenshot(page, tn, "playwright_error")
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
