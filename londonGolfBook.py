# -*- coding:utf-8 -*-
import sys
import time
import traceback
import requests
import datetime as dt
import pytz
import argparse
import multiprocessing as mp
import redis
import random
import os
import json
from multiprocessing import Pool
from typing import Dict, List, Optional, Any, Tuple

from seleniumwire import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException
from common import *

# Constants
TIMEOUT = 20
BOOK_INTERVAL = 8
MAX_WAIT_TEETIME = 100
WEEKDAY = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN']
HEADERS = {'X-Be-Alias': 'city-of-london-golf-courses'}
LOCAL_CACHE_FILE = "tee_time_cache.json"

# API Endpoints
ENDPOINTS = {
    'login': "https://city-of-london-golf-courses.book.teeitup.com/login",
    'course': "https://phx-api-be-east-1b.kenna.io/course",
    'cart': "https://phx-api-be-east-1b.kenna.io/shopping-cart/",
    'cart_item': "https://phx-api-be-east-1b.kenna.io/shopping-cart/{}/cart-item",
    'tee_time': "https://phx-api-be-east-1b.kenna.io/v2/tee-times?date={}&facilityIds={}",
    'lock': "https://phx-api-be-east-1b.kenna.io/course/{}/tee-time/lock"
}

# Initialize logger and configuration
LOGGER = getLogger()
CONFIG = getConfig()


class GolfBookingError(Exception):
    """Base exception class for golf booking errors"""
    pass


class AuthenticationError(GolfBookingError):
    """Exception for authentication related errors"""
    pass


class TeeTimeError(GolfBookingError):
    """Exception for tee time related errors"""
    pass


class CartError(GolfBookingError):
    """Exception for shopping cart related errors"""
    pass


class ReservationError(GolfBookingError):
    """Exception for reservation related errors"""
    pass


class CacheManager:
    """Manages caching of tee time data using either Redis or local file"""
    
    def __init__(self):
        """Initialize the cache manager"""
        self.use_redis = False
        self.redis_connection = None
        self.cache_file = LOCAL_CACHE_FILE
        self.cache_data = {}
        
        # Try to connect to Redis if configuration exists
        if 'redis' in CONFIG and 'host' in CONFIG['redis'] and 'port' in CONFIG['redis']:
            try:
                self.redis_connection = redis.Redis(
                    host=CONFIG['redis']['host'],
                    port=CONFIG['redis']['port'],
                    decode_responses=True
                )
                # Test connection
                self.redis_connection.ping()
                self.use_redis = True
                LOGGER.info("Using Redis for caching")
            except Exception as e:
                LOGGER.info(f"Redis connection failed: {str(e)}. Using local file cache instead.")
                self.use_redis = False
        
        # Load local cache if exists
        if not self.use_redis and os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r') as f:
                    self.cache_data = json.load(f)
                LOGGER.info(f"Loaded local cache from {self.cache_file}")
            except Exception as e:
                LOGGER.info(f"Failed to load local cache: {str(e)}. Starting with empty cache.")
                self.cache_data = {}
    
    def get(self, key: str) -> Optional[str]:
        """
        Get value from cache
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None if not found
        """
        if self.use_redis:
            return self.redis_connection.get(key)
        else:
            return self.cache_data.get(key)
    
    def set(self, key: str, value: str, expire_seconds: int = 300) -> None:
        """
        Set value in cache
        
        Args:
            key: Cache key
            value: Value to cache
            expire_seconds: Expiration time in seconds
        """
        if self.use_redis:
            self.redis_connection.set(key, value)
            self.redis_connection.expire(key, expire_seconds)
        else:
            self.cache_data[key] = value
            # Save to file
            try:
                with open(self.cache_file, 'w') as f:
                    json.dump(self.cache_data, f)
            except Exception as e:
                LOGGER.info(f"Failed to save local cache: {str(e)}")
    
    def delete(self, key: str) -> None:
        """
        Delete value from cache
        
        Args:
            key: Cache key
        """
        if self.use_redis:
            self.redis_connection.delete(key)
        else:
            if key in self.cache_data:
                del self.cache_data[key]
                # Save to file
                try:
                    with open(self.cache_file, 'w') as f:
                        json.dump(self.cache_data, f)
                except Exception as e:
                    LOGGER.info(f"Failed to save local cache: {str(e)}")


# Initialize cache manager
CACHE_MANAGER = CacheManager()


def get_driver(is_headless: bool = False) -> webdriver.Chrome:
    """
    Configure and return a Chrome driver.
    
    Args:
        is_headless: Whether to run in headless mode
        
    Returns:
        Configured Chrome driver
    """
    options = webdriver.ChromeOptions()
    if is_headless:
        options.add_argument('--headless')
    return webdriver.Chrome(options=options, seleniumwire_options={})


def do_login(driver: webdriver.Chrome, login_url: str, login_uid: str, login_pwd: str) -> None:
    """
    Perform login operation.
    
    Args:
        driver: Web driver
        login_url: Login URL
        login_uid: Login ID
        login_pwd: Login password
    """
    try:
        driver.set_window_size(500, 1000)
        driver.get(login_url)
        driver.implicitly_wait(TIMEOUT)
        
        # Enter email
        WebDriverWait(driver, TIMEOUT).until(
            EC.presence_of_element_located((By.XPATH, "//input[@data-testid='login-email-component']"))
        ).send_keys(login_uid)
        
        # Enter password
        WebDriverWait(driver, TIMEOUT).until(
            EC.presence_of_element_located((By.XPATH, "//input[@data-testid='login-password-component']"))
        ).send_keys(login_pwd)
        
        # Click login button
        WebDriverWait(driver, TIMEOUT).until(
            EC.element_to_be_clickable((By.XPATH, "//button[@data-testid='login-button']"))
        ).click()
    except Exception as e:
        raise AuthenticationError(f"Login failed: {str(e)}")


def get_cart_session_request(driver: webdriver.Chrome) -> Any:
    """
    Get cart session request.
    
    Args:
        driver: Web driver
        
    Returns:
        Cart session request object
    """
    try:
        driver.wait_for_request(ENDPOINTS['course'], TIMEOUT)
        driver.refresh()
        return driver.wait_for_request(ENDPOINTS['cart'], TIMEOUT)
    except TimeoutException as ex:
        LOGGER.info(f"* Exception occurred: {str(ex)}")
        raise CartError(f"Failed to get cart session request: {str(ex)}")


def get_cart_session(driver: webdriver.Chrome) -> str:
    """
    Get cart session ID.
    
    Args:
        driver: Web driver
        
    Returns:
        Cart session ID
    """
    return get_cart_session_request(driver).path.split('/')[-1]


def get_login_session(driver: webdriver.Chrome) -> str:
    """
    Get login session ID.
    
    Args:
        driver: Web driver
        
    Returns:
        Login session ID
    """
    for request in driver.requests:
        if (request.response and 
            request.response.status_code == 200 and 
            request.headers.get('Session')):
            return request.headers['Session']
    raise AuthenticationError("Could not get login session")


def get_tee_times(course: str, date: str) -> List[Dict]:
    """
    Get tee times for a specific course and date.
    
    Args:
        course: Course code
        date: Date in YYYY-MM-DD format
        
    Returns:
        List of available tee times
    """
    try:
        response = requests.get(
            ENDPOINTS['tee_time'].format(date, course), 
            headers=HEADERS
        )
        response.raise_for_status()
        
        tee_times = response.json()[0]['teetimes']
        return [t for t in tee_times if t['bookedPlayers'] == 0 and t['maxPlayers'] == 4]
    except Exception as e:
        LOGGER.info("========== Error ==========")
        LOGGER.info(response.json() if 'response' in locals() else "No response")
        LOGGER.info("========== Error ==========")
        return []


def set_shopping_cart(cart_session: str, tee_time_info: Dict) -> requests.Response:
    """
    Add tee time to shopping cart.
    
    Args:
        cart_session: Cart session ID
        tee_time_info: Tee time information
        
    Returns:
        API response
    """

    rate = tee_time_info['rates'][0]

    data = {
        'item': {
            'facilityId': rate['golfnow']['GolfFacilityId'],
            'type': "TeeTime",
            'extra': {
                'teetime': tee_time_info['teetime'],
                'players': rate['allowedPlayers'][-1],
                'groupSize': 1,
                'price': rate['greenFeeWalking'] / 100.0,
                'rate': {
                    'holes': rate['holes'],
                    'rateId': rate['_id'],
                    'rateSetId': rate['golfnow']['GolfCourseId'],
                    'name': rate['name'],
                    'transactionFees': 0,
                    'transportation': rate['name'],
                    'isSimulator': rate['isSimulator']
                },
                'featuredProducts': []
            }
        }
    }

    LOGGER.info("------------------------------")
    LOGGER.info(data)
    LOGGER.info("------------------------------")

    return requests.post(
        ENDPOINTS['cart_item'].format(cart_session), 
        headers=HEADERS, 
        json=data
    )


def set_lock_tee_time(login_session: str, tee_time_info: Dict) -> requests.Response:
    """
    Lock a tee time.
    
    Args:
        login_session: Login session ID
        tee_time_info: Tee time information
        
    Returns:
        API response
    """
    data = {
        "teetime": tee_time_info['teetime'],
        "slots": 4,
        "expiresIn": 5
    }

    headers = HEADERS.copy()
    headers['Session'] = login_session
    return requests.put(
        ENDPOINTS['lock'].format(tee_time_info['courseId']), 
        headers=headers, 
        json=data
    )


def set_reservation(driver: webdriver.Chrome, task_name: str) -> None:
    """
    Complete the reservation process.
    
    Args:
        driver: Web driver
    """
    try:
        driver.refresh()
        driver.implicitly_wait(TIMEOUT)
        time.sleep(2)

        # Click shopping cart button
        LOGGER.info("* [{:<10}] + reservation.: click shopping cart button".format(task_name))
        WebDriverWait(driver, TIMEOUT).until(EC.element_to_be_clickable((By.XPATH, "//button[@data-testid='shopping-cart-button']"))).click()

        # click checkout
        LOGGER.info("* [{:<10}] + reservation.: click checkout button".format(task_name))
        WebDriverWait(driver, TIMEOUT).until(EC.element_to_be_clickable((By.XPATH, "//button[@data-testid='shopping-cart-drawer-checkout-btn']"))).click()

        # click checkbox
        LOGGER.info("* [{:<10}] + reservation.: click checkbox".format(task_name))
        driver.execute_script("window.scrollTo(0,document.body.scrollHeight)")
        driver.find_element(By.NAME, 'chb-nm').click()

        # Click reservation button
        LOGGER.info("* [{:<10}] + reservation.: click the reservation button".format(task_name))
        WebDriverWait(driver, TIMEOUT).until(EC.element_to_be_clickable((By.XPATH, "//button[@data-testid='make-your-reservation-btn']"))).click()
        LOGGER.info("* [{:<10}] + reservation.: completed.".format(task_name))

    except Exception as e:
        raise ReservationError(f"Failed to complete reservation: {str(e)}")


def set_reservation_with_retry(driver: webdriver.Chrome, task_name: str, max_retries: int = 5) -> None:
    """
    Complete the reservation process with retry logic.
    
    Args:
        driver: Web driver
        task_name: Task name for logging
        max_retries: Maximum number of retry attempts
    """
    for attempt in range(max_retries):
        try:
            LOGGER.info("* [{:<10}] (Attempt {}/{}) Starting reservation process".format(task_name, attempt + 1, max_retries))
            set_reservation(driver, task_name)
            LOGGER.info("* [{:<10}] (Success) Reservation completed on attempt {}".format(task_name, attempt + 1))
            return
        except Exception as e:
            if attempt < max_retries - 1:
                LOGGER.info("* [{:<10}] (Attempt {}/{}) Failed: {}. Retrying...".format(task_name, attempt + 1, max_retries, str(e)))
                time.sleep(1)  # Wait before retrying
            else:
                LOGGER.info("* [{:<10}] (Failed) All {} attempts failed. Last error: {}".format(task_name, max_retries, str(e)))
                raise ReservationError(f"Failed to complete reservation after {max_retries} attempts: {str(e)}")


def convert_tz(input_dt: Any, tz1: str, tz2: str) -> dt.datetime:
    """
    Convert timezone.
    
    Args:
        input_dt: Input date/time
        tz1: Source timezone
        tz2: Target timezone
        
    Returns:
        Converted date/time
    """
    if isinstance(input_dt, dt.datetime):
        input_dt = input_dt.strftime("%Y-%m-%d %H:%M:%S")

    tz1_obj = pytz.timezone(tz1)
    tz2_obj = pytz.timezone(tz2)
    input_dt = dt.datetime.strptime(input_dt, "%Y-%m-%d %H:%M:%S")
    input_dt = tz1_obj.localize(input_dt)
    return input_dt.astimezone(tz2_obj)


def convert_tz_eastern_to_utc(input_dt: Any) -> dt.datetime:
    """Convert US Eastern time to UTC."""
    return convert_tz(input_dt, 'US/Eastern', 'UTC')


def convert_tz_utc_to_eastern(input_dt: Any) -> dt.datetime:
    """Convert UTC to US Eastern time."""
    return convert_tz(input_dt, 'UTC', 'US/Eastern')


def convert_tz_utc_to_utc(input_dt: Any) -> dt.datetime:
    """Convert UTC to UTC (format standardization only)."""
    return convert_tz(input_dt, 'UTC', 'UTC')


def get_book_schedule(schedule_info: Dict, task_name: str, cart_session: str, login_session: str) -> List[Dict]:
    """
    Process booking schedule.
    
    Args:
        schedule_info: Schedule information
        task_name: Task name
        cart_session: Cart session ID
        login_session: Login session ID
        
    Returns:
        List of selected tee times
    """
    c_proc = mp.current_process()

    # Set booking date
    book_date = schedule_info.get('book_date', None) or (
        dt.datetime.now() + dt.timedelta(days=BOOK_INTERVAL)
    ).strftime("%Y-%m-%d")
    
    # Set buffer time
    schedule_info['bufferTime'] = random.randrange(0, schedule_info.get('buffer', 0) + 1)
    
    # Set UTC times
    schedule_info['bookStartTimeUtc'] = convert_tz_eastern_to_utc(
        f"{book_date} {schedule_info['start_time']}:00"
    ) + dt.timedelta(minutes=schedule_info['bufferTime'])
    
    schedule_info['bookEndTimeUtc'] = schedule_info['bookStartTimeUtc'] + dt.timedelta(
        minutes=schedule_info.get('duration', 30)
    )
    
    # Set Eastern times
    schedule_info['bookStartTimeEastern'] = convert_tz_utc_to_eastern(schedule_info['bookStartTimeUtc'])
    schedule_info['bookEndTimeEastern'] = convert_tz_utc_to_eastern(schedule_info['bookEndTimeUtc'])

    # Select course
    schedule_info['picked_course'] = random.choice(schedule_info['course'])
    schedule_info['courseCode'] = CONFIG['course'][schedule_info['picked_course']]['code']
    schedule_info['courseName'] = CONFIG['course'][schedule_info['picked_course']]['name']

    # Log output
    log_array = ["", "-" * 100]
    log_array.extend(
        " " * 26 + "[{:<10}] [{}] * {:<20} : {}".format(
            task_name, c_proc.name, k, v
        ) for k, v in schedule_info.items()
    )
    log_array.append("-" * 100)
    LOGGER.info("\n".join(log_array))

    # Check weekday
    if WEEKDAY[schedule_info['bookStartTimeUtc'].weekday()] not in schedule_info['weekday']:
        LOGGER.info("* [{:<10}] [{}] [{}] {} is not in {}".format(
            task_name,
            c_proc.name,
            schedule_info['picked_course'],
            WEEKDAY[schedule_info['bookStartTimeUtc'].weekday()],
            schedule_info['weekday']
        ))
        return []

    # Search and select tee times
    flag_tee_time = True
    idx = 0
    selected_tee_times = []

    while flag_tee_time and idx < MAX_WAIT_TEETIME:
        idx += 1

        tee_times = get_tee_times(schedule_info['courseCode'], book_date)
        LOGGER.info("* [{:<10}] [{}] {} time(s) attempted".format(
            task_name, c_proc.name, idx
        ))

        for tee_time_info in tee_times:
            tee_time = convert_tz_utc_to_utc(
                dt.datetime.strptime(
                    tee_time_info['teetime'],
                    "%Y-%m-%dT%H:%M:%S.000Z"
                ).strftime("%Y-%m-%d %H:%M:%S")
            )

            log_str = "* [{:<10}] [{}] [{}] {} <= {} <= {}".format(
                task_name,
                c_proc.name,
                schedule_info['picked_course'],
                schedule_info['bookStartTimeEastern'].strftime("%H:%M"),
                convert_tz_utc_to_eastern(tee_time).strftime("%H:%M"),
                schedule_info['bookEndTimeEastern'].strftime("%H:%M")
            )

            if schedule_info['bookStartTimeUtc'] <= tee_time <= schedule_info['bookEndTimeUtc']:
                redis_validation_key = f"{tee_time_info['rates'][0]['_id']}:{convert_tz_utc_to_eastern(tee_time).strftime('%Y-%m-%d %H:%M:%S')}"
                redis_res = CACHE_MANAGER.get(redis_validation_key)

                if len(selected_tee_times) < schedule_info.get('book_count', 1) and redis_res is None:
                    schedule_info['teeTimeEastern'] = convert_tz_utc_to_eastern(tee_time).strftime("%Y-%m-%d %H:%M")
                    tee_time_info['scheduleInfo'] = schedule_info

                    selected_tee_times.append(tee_time_info)
                    CACHE_MANAGER.set(redis_validation_key, "OK", 300)

                    # Lock tee time and add to cart
                    lock_res = set_lock_tee_time(login_session, tee_time_info)
                    cart_res = set_shopping_cart(cart_session, tee_time_info)
                    flag_tee_time = False
                    LOGGER.info(
                        f"{log_str} [Valid] [Selected] [lock:{lock_res.status_code} & cart:{cart_res.status_code}]"
                    )
                elif redis_res is None:
                    LOGGER.info(f"{log_str} [Valid]")
                else:
                    LOGGER.info(f"{log_str} [Valid] [Cache]")
            else:
                LOGGER.info(log_str)

        if len(tee_times) > 0:
            log_str = "* [{:<10}] [{}] [{}]".format(
                task_name, c_proc.name, schedule_info['picked_course']
            )
            if not flag_tee_time:
                LOGGER.info(f"{log_str}")
                LOGGER.info(f"{log_str} >>>>>>>>>> found teetime <<<<<<<<<<")
                LOGGER.info(f"{log_str}")
            else:
                LOGGER.info(f"{log_str}")
                LOGGER.info(f"{log_str} >>>>>>>>>> Couldn't find any teetime <<<<<<<<<<")
                LOGGER.info(f"{log_str}")
            break
        else:
            time.sleep(1)

    return selected_tee_times


def main():
    """Main function"""
    try:
        LOGGER.info("")
        LOGGER.info("#---------------------------------------------------#")
        LOGGER.info("#                     START                         #")
        LOGGER.info("#---------------------------------------------------#")
        LOGGER.info("")

        # Parse command line arguments
        parser = argparse.ArgumentParser(
            prog='London Golf Booking', 
            description='London Golf Booking Batch', 
            epilog='Copyright.2025.Andrew Song.All rights reserved.'
        )
        parser.add_argument(
            '-d', '--debug', 
            required=True, 
            choices=['yes', 'no'], 
            help='use debug mode'
        )
        parser.add_argument(
            '-t', '--task',  
            required=True, 
            help='use task name'
        )

        args = parser.parse_args()

        task_name = args.task
        debug_mode = args.debug == 'yes'
        
        # Get authentication information
        auth_key = CONFIG['schedule'][task_name]['auth']
        login_uid = CONFIG['authentication'][auth_key]['userid']
        login_pwd = CONFIG['authentication'][auth_key]['password']

        # Initialize driver and login
        driver = get_driver(not debug_mode)
        do_login(driver, ENDPOINTS['login'], login_uid, login_pwd)
        LOGGER.info("* [{:<10}] (Done.) login : {}".format(task_name, login_uid))

        # Get cart session
        cart_session = get_cart_session(driver)
        LOGGER.info("* [{:<10}] (Done.) get cart session : {}".format(task_name, cart_session))

        # Get login session
        login_session = get_login_session(driver)
        LOGGER.info("* [{:<10}] (Done.) get login session : {}...{}".format(
            task_name, login_session[:20], login_session[-20:]
        ))

        LOGGER.info("* [{:<10}] (Debug) CPU count : {}".format( task_name, mp.cpu_count()))

        # Process booking schedules
        p = Pool(mp.cpu_count())

        flag_reservation = False
        multi_process_result = []

        for schedule_info in CONFIG['schedule'][task_name]['tasks']:
            multi_process_result.append(
                p.apply_async(
                    get_book_schedule,
                    (schedule_info, task_name, cart_session, login_session)
                )
            )

        p.close()
        p.join()

        for m in multi_process_result:
            for r in m.get():
                flag_reservation = True
                break

        if flag_reservation:
            # Complete reservation with retry logic
            LOGGER.info("* [{:<10}] (Start) set reservation with retry.".format(task_name))
            set_reservation_with_retry(driver, task_name)
            LOGGER.info("* [{:<10}] (Done.) set reservation with retry.".format(task_name))
            time.sleep(TIMEOUT)

        LOGGER.info("")
        LOGGER.info("#---------------------------------------------------#")
        LOGGER.info("#                      END                          #")
        LOGGER.info("#---------------------------------------------------#")
        LOGGER.info("")

    except Exception as e:
        traceback_msg = "Traceback: %s" % traceback.format_exc()
        LOGGER.info("[ERROR]" + "-" * 100)
        LOGGER.info(traceback_msg)
        LOGGER.info("[ERROR]" + "-" * 100)
        print("[ERROR]" + "-" * 100, file=sys.stderr)
        print(traceback_msg, file=sys.stderr)
        print("[ERROR]" + "-" * 100, file=sys.stderr)


if __name__ == '__main__':
    main()
