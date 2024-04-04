# -*- coding:utf-8 -*-
import sys,time, traceback
import requests
import datetime as dt
import pytz
import argparse
import multiprocessing as mp
import redis
import random
from multiprocessing import Pool

from seleniumwire import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException
from common import *

TIMEOUT = 10
LOGGER = getLogger()
CONFIG = getConfig()
BOOK_INTERVAL = 7
MAX_WAIT_TEETIME = 100
WEEKDAY = ['MON','TUE','WED','THU','FRI','SAT','SUN']
HEADERS = {'X-Be-Alias': 'city-of-london-golf-courses'}

LONDON_GOLF_GET_LOGIN = "https://city-of-london-golf-courses.book.teeitup.golf/login"
LONDON_GOLF_GET_COURSE = "https://phx-api-be-east-1b.kenna.io/course"
LONDON_GOLF_GET_CART = "https://phx-api-be-east-1b.kenna.io/shopping-cart/"
LONDON_GOLF_SET_CART = "https://phx-api-be-east-1b.kenna.io/shopping-cart/{}/cart-item"
LONDON_GOLF_GET_TEE_TIME = "https://phx-api-be-east-1b.kenna.io/v2/tee-times?date={}&facilityIds={}"
LONDON_GOLF_SET_LOCK = "https://phx-api-be-east-1b.kenna.io/course/{}/tee-time/lock"

def getDriver(isHeadless = False):
  '''
  options.add_argument('--allow-insecure-localhost')
  options.add_argument('--no-sandbox')
  options.add_argument('--disable-gpu')
  options.add_argument('--headless')
  options.add_argument('--disable-dev-shm-usage')
  options.add_argument('--allow-running-insecure-content')
  options.add_argument('--ignore-certificate-errors')
  '''
  options = webdriver.ChromeOptions()
  if isHeadless:
    options.add_argument('--headless')
  return webdriver.Chrome(options=options, seleniumwire_options={})

def doLogin(driver, loginUrl, loginUid, loginPwd):
  driver.set_window_size(500,1000)
  driver.get(loginUrl)
  driver.implicitly_wait(TIMEOUT)
  WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.XPATH, "//input[@data-testid='login-email-component']"))).send_keys(loginUid)
  WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.XPATH, "//input[@data-testid='login-password-component']"))).send_keys(loginPwd)
  WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, "//button[@data-testid='login-button']"))).click()

def getCartSessionRequest(driver):
  try:
    driver.wait_for_request(LONDON_GOLF_GET_COURSE,TIMEOUT)
    driver.refresh()
    return driver.wait_for_request(LONDON_GOLF_GET_CART,TIMEOUT)
  except TimeoutException as ex:
    LOGGER.info(f"* Exception has been thrown. {str(ex)}")

def getCartSession(driver):
  return getCartSessionRequest(driver).path.split('/')[-1]

def getLoginSession(driver):
  for request in driver.requests:
    if request.response and request.response.status_code == 200 and request.headers['Session'] != None:
      return request.headers['Session']

def getTeeTimes(course, date):
  try:
    res = requests.get(LONDON_GOLF_GET_TEE_TIME.format(date, course), headers=HEADERS)
    result = [ x for x in res.json()[0]['teetimes'] if x['bookedPlayers'] == 0 and x['maxPlayers'] == 4 ]
  except Exception as e:
    LOGGER.info("========== Error ==========")
    LOGGER.info(res.json())
    LOGGER.info("========== Error ==========")
  return result

def setShoppingCart(cartSession, teeTimeInfo):
  data = {
    'item': {
      'facilityId': teeTimeInfo['rates'][0]['golfnow']['GolfFacilityId'],
      'type': "TeeTime",
      'extra': {
        'teetime': teeTimeInfo['teetime'],
        'players': teeTimeInfo['maxPlayers'],
        'price': int(teeTimeInfo['rates'][0]['greenFeeWalking'] / 100),
        'rate': {
          'holes': teeTimeInfo['rates'][0]['holes'],
          'rateId': teeTimeInfo['rates'][0]['_id'],
          'rateSetId': teeTimeInfo['rates'][0]['golfnow']['GolfCourseId'],
          'name': teeTimeInfo['rates'][0]['name'],
          'transportation': 'Walking',
        },
        'featuredProducts': []
      }
    }
  }

  return requests.post(LONDON_GOLF_SET_CART.format(cartSession), headers=HEADERS, json=data)

def setLockTeeTime(loginSession, teeTimeInfo):
  data = {
    "teetime": teeTimeInfo['teetime'],
    "slots": 4,
    "expiresIn": 5
  }

  headers = HEADERS;
  headers['Session'] = loginSession
  return requests.put(LONDON_GOLF_SET_LOCK.format(teeTimeInfo['courseId']), headers=headers, json=data)

def setReservation(driver):
  driver.refresh()
  driver.implicitly_wait(TIMEOUT)
  WebDriverWait(driver, TIMEOUT).until(EC.element_to_be_clickable((By.XPATH, "//div[@data-testid='mobile-core-shopping-cart']"))).click()
  WebDriverWait(driver, TIMEOUT).until(EC.element_to_be_clickable((By.XPATH, "//button[@data-testid='shopping-cart-drawer-checkout-btn']"))).click()
  driver.execute_script("window.scrollTo(0,document.body.scrollHeight)")
  driver.find_element(By.NAME, 'chb-nm').click()
  WebDriverWait(driver, TIMEOUT).until(EC.element_to_be_clickable((By.XPATH, "//button[@data-testid='make-your-reservation-btn']"))).click()

def convertTz(inputDt, tz1, tz2):

  if type(inputDt) == dt.datetime:
    inputDt = inputDt.strftime("%Y-%m-%d %H:%M:%S")

  tz1 = pytz.timezone(tz1)
  tz2 = pytz.timezone(tz2)
  inputDt = dt.datetime.strptime(inputDt,"%Y-%m-%d %H:%M:%S")
  inputDt = tz1.localize(inputDt)
  return inputDt.astimezone(tz2)

def convertTzEasternToUtc(inputDt):
  return convertTz(inputDt, 'US/Eastern', 'UTC')

def convertTzUtcToEastern(inputDt):
  return convertTz(inputDt, 'UTC', 'US/Eastern')

def convertTzUtcToUtc(inputDt):
  return convertTz(inputDt, 'UTC', 'UTC')

def getBookSchedule(scheduleInfo, taskName, cartSession, loginSession):

  redisConnection = redis.Redis(host='localhost', port=6379, decode_responses=True)
  c_proc = mp.current_process()

  bookDate = scheduleInfo.get('book_date',None) or (dt.datetime.now() + dt.timedelta(days=BOOK_INTERVAL)).strftime("%Y-%m-%d")
  scheduleInfo['bufferTime'] = random.randrange(0, scheduleInfo.get('buffer',0) + 1)
  scheduleInfo['bookStartTimeUtc'] = convertTzEasternToUtc(f"{bookDate} {scheduleInfo['start_time']}:00") + dt.timedelta(minutes=scheduleInfo['bufferTime'])
  scheduleInfo['bookEndTimeUtc']   = scheduleInfo['bookStartTimeUtc'] + dt.timedelta(minutes=scheduleInfo.get('duration',30))
  scheduleInfo['bookStartTimeEastern'] = convertTzUtcToEastern(scheduleInfo['bookStartTimeUtc'])
  scheduleInfo['bookEndTimeEastern']   = convertTzUtcToEastern(scheduleInfo['bookEndTimeUtc'])
  scheduleInfo['courseCode'] = CONFIG['course'][scheduleInfo['course']]['code']
  scheduleInfo['courseName'] = CONFIG['course'][scheduleInfo['course']]['name']

  logArray = ["", "-" * 100]
  logArray.extend(
      " " * 26 +
      "[{:<10}] [{}] * {:<20} : {}".format(taskName, c_proc.name, k, v)
      for k, v in scheduleInfo.items())
  logArray.append("-" * 100)
  LOGGER.info("\n".join(logArray))

  if WEEKDAY[scheduleInfo['bookStartTimeUtc'].weekday()] not in scheduleInfo['weekday']:
    LOGGER.info("* [{:<10}] [{}] [{}] {} is not in {}".format(
      taskName,
      c_proc.name,
      scheduleInfo['course'],
      WEEKDAY[scheduleInfo['bookStartTimeUtc'].weekday()],
      scheduleInfo['weekday']
    ))
    return []

  #---------------------------------------------------------------#
  # 4-1. wait and get tee time
  #---------------------------------------------------------------#
  flagTeeTime = True
  idx = 0

  while flagTeeTime and idx < MAX_WAIT_TEETIME:#{
    idx += 1

    teeTimes = getTeeTimes(scheduleInfo['courseCode'], bookDate)
    LOGGER.info("* [{:<10}] [{}] {} time(s) attempted".format(taskName,c_proc.name,idx))

    #---------------------------------------------------------------#
    # 4-2. select tee time
    #---------------------------------------------------------------#
    selectedTeeTimes = []
    for teeTimeInfo in teeTimes: #{
      teeTime = convertTzUtcToUtc(dt.datetime.strptime(teeTimeInfo['teetime'],"%Y-%m-%dT%H:%M:%S.000Z").strftime("%Y-%m-%d %H:%M:%S"))

      logStr = "* [{:<10}] [{}] [{}] {} <= {} <= {}".format(
          taskName,
          c_proc.name,
          scheduleInfo['course'],
          scheduleInfo['bookStartTimeEastern'].strftime("%Y-%m-%d %H:%M"),
          convertTzUtcToEastern(teeTime).strftime("%Y-%m-%d %H:%M"),
          scheduleInfo['bookEndTimeEastern'].strftime("%Y-%m-%d %H:%M")
      )

      if (scheduleInfo['bookStartTimeUtc'] <= teeTime <= scheduleInfo['bookEndTimeUtc']):

        redisVaildationKey = f"""{teeTimeInfo['rates'][0]['_id']}:{convertTzUtcToEastern(teeTime).strftime("%Y-%m-%d %H:%M:%S")}"""
        redisRes = redisConnection.get(redisVaildationKey)

        if (len(selectedTeeTimes) < scheduleInfo['book_count'] and redisRes is None):
          scheduleInfo['teeTimeEastern'] = convertTzUtcToEastern(teeTime).strftime("%Y-%m-%d %H:%M")
          teeTimeInfo['scheduleInfo'] = scheduleInfo

          selectedTeeTimes.append(teeTimeInfo)
          redisConnection.set(redisVaildationKey,"OK")
          redisConnection.expire(redisVaildationKey,300)

          #---------------------------------------------------------------#
          # 4-3. set lock and cart
          #---------------------------------------------------------------#
          lockRes = setLockTeeTime(loginSession, teeTimeInfo)
          cartRes = setShoppingCart(cartSession, teeTimeInfo)
          flagTeeTime = False
          LOGGER.info(
              f"{logStr} [Valid] [Selected] [lock:{lockRes.status_code} & cart:{cartRes.status_code}]"
          )
        elif redisRes is None:
          LOGGER.info(f"{logStr} [Valid]")
        else:
          LOGGER.info(f"{logStr} [Valid] [Redis]")
      else:
        LOGGER.info(logStr)
    #}for

    if len(teeTimes) > 0:
      time.sleep(1)
    else:
      time.sleep(0.5)
  #}while

  return selectedTeeTimes

def main():

  try:

    LOGGER.info("")
    LOGGER.info("#---------------------------------------------------#")
    LOGGER.info("#                     START                         #")
    LOGGER.info("#---------------------------------------------------#")
    LOGGER.info("")

    #---------------------------------------------------------------#
    # 0. set parameters
    #---------------------------------------------------------------#
    parser = argparse.ArgumentParser(prog='London Golf Booking', description='London Golf Booking Batch', epilog='Copyright.2023.Andrew Song.All rights reserved.')
    parser.add_argument('-d', '--debug', required=True, choices=['yes','no'], help='use debug mode')
    parser.add_argument('-t', '--task',  required=True, help='use task name')

    args = parser.parse_args()

    taskName = args.task
    debugMode = True if args.debug == 'yes' else False
    loginUid = CONFIG['authentication'][taskName]['userid']
    loginPwd = CONFIG['authentication'][taskName]['password']

    #---------------------------------------------------------------#
    # 1. getDriver and login
    #---------------------------------------------------------------#
    driver = getDriver(not debugMode)
    doLogin(driver, LONDON_GOLF_GET_LOGIN, loginUid, loginPwd)
    LOGGER.info("* [{:<10}] (Done.) login : {}".format(taskName,loginUid))

    #---------------------------------------------------------------#
    # 2. get cart session
    #---------------------------------------------------------------#
    cartSession = getCartSession(driver)
    LOGGER.info("* [{:<10}] (Done.) get cart session : {}".format(taskName,cartSession))

    #---------------------------------------------------------------#
    # 3. get login session
    #---------------------------------------------------------------#
    loginSession = getLoginSession(driver)
    LOGGER.info("* [{:<10}] (Done.) get login session : {}...{}".format(taskName,loginSession[:20],loginSession[-20:]))

    #---------------------------------------------------------------#
    # 4. select book schedules
    #---------------------------------------------------------------#
    p = Pool(mp.cpu_count())

    flagReservation = False
    multiProcessResult = []

    for scheduleInfo in CONFIG['book_schedules'][taskName]:
      multiProcessResult.append(p.apply_async(getBookSchedule,(scheduleInfo,taskName,cartSession,loginSession)))

    p.close()
    p.join()

    for m in multiProcessResult:
      for r in m.get():
        flagReservation = True
        break

    if flagReservation:#{
      #---------------------------------------------------------------#
      # 6. set reservation
      #---------------------------------------------------------------#
      LOGGER.info("* [{:<10}] (Start) set reservation.".format(taskName))
      setReservation(driver)
      LOGGER.info("* [{:<10}] (Done.) set reservation.".format(taskName))
      time.sleep(10)
    #}if

    LOGGER.info("")
    LOGGER.info("#---------------------------------------------------#")
    LOGGER.info("#                      END                          #")
    LOGGER.info("#---------------------------------------------------#")
    LOGGER.info("")

  except Exception as e:
    traceback_msg = "Traceback: %s" % traceback.format_exc()
    LOGGER.info("[ERROR]"+"-"*100)
    LOGGER.info(traceback_msg)
    LOGGER.info("[ERROR]"+"-"*100)
    print("[ERROR]"+"-"*100, file=sys.stderr)
    print(traceback_msg, file=sys.stderr)
    print("[ERROR]"+"-"*100, file=sys.stderr)

if __name__ == '__main__':
  main()
