"""Shared constants: API endpoints, headers, and booking tuning parameters."""

TIMEOUT = 20
BOOK_INTERVAL = 8
MAX_WAIT_TEETIME = 100
WEEKDAY = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
HEADERS = {"X-Be-Alias": "city-of-london-golf-courses"}
LOCAL_CACHE_FILE = "tee_time_cache.json"

_KENNA = "https://phx-api-be-east-1b.kenna.io"
ENDPOINTS = {
    "login": "https://city-of-london-golf-courses.book.teeitup.com/login",
    "course": f"{_KENNA}/course",
    "cart": f"{_KENNA}/shopping-cart/",
    "cart_item": f"{_KENNA}/shopping-cart/{{}}/cart-item",
    "tee_time": f"{_KENNA}/v2/tee-times?date={{}}&facilityIds={{}}",
    "lock": f"{_KENNA}/course/{{}}/tee-time/lock",
}
