# -*- coding:utf-8 -*-
# ------------------------------------------------------------------------------
# https://www.selenium.dev/selenium/docs/api/py/api.html#common
# https://pypi.org/project/selenium-wire/#request-objects
# https://gist.github.com/mcchae/c9323d426aba8fcde3c1b54731f6cfbe
#
# --------- API ----------------------------------------------------------------
# https://phx-api-be-east-1b.kenna.io/v2/tee-times?date=2023-07-01&facilityIds=9710
# ------------------------------------------------------------------------------

import sys,time, traceback
import requests
import datetime as dt
import pytz
import simplejson
import argparse
from dateutil import parser

from seleniumwire import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException
from common import *

TIMEOUT = 5
LOGGER = getLogger()
CONFIG = getConfig()
BOOK_INTERVAL = 7

def getDriver(isHeadless = False):
  options = webdriver.ChromeOptions()
  #options.add_argument('--allow-insecure-localhost')
  #options.add_argument('--no-sandbox')
  #options.add_argument('--disable-gpu')
  if isHeadless:
    options.add_argument('--headless')
  #options.add_argument('--disable-dev-shm-usage')
  #options.add_argument('--allow-running-insecure-content')
  #options.add_argument('--ignore-certificate-errors')

  seleniumwire_options = {}

  return webdriver.Chrome(options=options, seleniumwire_options=seleniumwire_options)

def doLogin(driver, loginUrl, loginUid, loginPwd):
  driver.set_window_size(500,1000)
  driver.get(loginUrl)
  driver.implicitly_wait(TIMEOUT)
  WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.ID,'txtUsername1'))).send_keys(loginUid)
  WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.ID,'txtPassword1'))).send_keys(loginPwd)
  WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.CLASS_NAME,'MuiButton-label'))).click()

def getCartSessionRequest(driver):
  try:
    driver.wait_for_request('https://phx-api-be-east-1b.kenna.io/course',TIMEOUT)
    driver.refresh()
    return driver.wait_for_request('https://phx-api-be-east-1b.kenna.io/shopping-cart/',TIMEOUT)
  except TimeoutException as ex:
    LOGGER.info("* Exception has been thrown. " + str(ex))

def getCartSession(driver):
  return getCartSessionRequest(driver).path.split('/')[-1]

def getLoginSession(driver):
  for request in driver.requests:
    if request.response and request.response.status_code == 200 and request.headers['Session'] != None:
      return request.headers['Session']

def getTeeTimes(course, date):
  try:
    headers = { 'X-Be-Alias': 'city-of-london-golf-courses'}
    res = requests.get("https://phx-api-be-east-1b.kenna.io/v2/tee-times?date={}&facilityIds={}".format(date, course), headers=headers)

    result = []
    for x in res.json()[0]['teetimes']:
      if x['bookedPlayers'] == 0 and x['maxPlayers'] == 4:
        result.append(x)

  except Exception as e:
    LOGGER.info("========== Error ==========")
    LOGGER.info(res.json())
    LOGGER.info("========== Error ==========")
    pass

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

  LOGGER.info(data)

  headers = { 'X-Be-Alias': 'city-of-london-golf-courses'}
  res = requests.post("https://phx-api-be-east-1b.kenna.io/shopping-cart/{}/cart-item".format(cartSession), headers=headers, json=data)

  LOGGER.info(res)
  LOGGER.info(res.text)

def setLockTeeTime(loginSession, teeTimeInfo):
  data = {
    "teetime": teeTimeInfo['teetime'],
    "slots": 4,
    "expiresIn": 5
  }

  LOGGER.info(data)

  headers = { 'X-Be-Alias': 'city-of-london-golf-courses', 'Session': loginSession }
  res = requests.put("https://phx-api-be-east-1b.kenna.io/course/{}/tee-time/lock".format(teeTimeInfo['courseId']), headers=headers, json=data)

  LOGGER.info(res)
  LOGGER.info(res.text)

def setReservation(driver):
  time.sleep(1)
  driver.refresh()
  WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, "//div[@data-testid='mobile-core-shopping-cart']"))).click()
  WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, "//button[@data-testid='shopping-cart-drawer-checkout-btn']"))).click()
  driver.execute_script("window.scrollTo(0,document.body.scrollHeight)")
  driver.find_element(By.NAME, 'chb-nm').click()
  WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, "//button[@data-testid='make-your-reservation-btn']"))).click()

def convertTz(inputDt, tz1, tz2):
  tz1 = pytz.timezone(tz1)
  tz2 = pytz.timezone(tz2)
  inputDt = dt.datetime.strptime(inputDt,"%Y-%m-%d %H:%M:%S")
  inputDt = tz1.localize(inputDt)
  return inputDt.astimezone(tz2)

def convertTzEasternToUtc(inputDt):
  return convertTz(inputDt, 'US/Eastern', 'UTC')

def convertTzUtcToUtc(inputDt):
  return convertTz(inputDt, 'UTC', 'UTC')

def main():

  try:
    LOGGER.info("")
    LOGGER.info("------------- START ------------------")

    #---------------------------------------------------------------#
    # 0. set parameters
    #---------------------------------------------------------------#
    parser = argparse.ArgumentParser(prog='London Golf Booking', description='London Golf Booking Batch', epilog='Copyright.2023.Andrew Song.All rights reserved.')
    parser.add_argument('-d', '--debug', required=True, choices=['yes','no'], help='use debug mode')
    parser.add_argument('-t', '--task',  required=True, help='use task name')

    args = parser.parse_args()

    taskName = args.task
    loginUrl = CONFIG['config']['url']['login']
    loginUid = CONFIG['authentication'][taskName]['userid']
    loginPwd = CONFIG['authentication'][taskName]['password']

    #---------------------------------------------------------------#
    # 1. getDriver and login
    #---------------------------------------------------------------#
    driver = getDriver(False)
    doLogin(driver, loginUrl, loginUid, loginPwd)
    LOGGER.info("* [Done] Do login : %s" % loginUid)

    #---------------------------------------------------------------#
    # 2. get cart session
    #---------------------------------------------------------------#
    cartSession = getCartSession(driver)
    LOGGER.info("* [Done] get cart session : %s" % cartSession)

    #---------------------------------------------------------------#
    # 3. get login session
    #---------------------------------------------------------------#
    loginSession = getLoginSession(driver)
    LOGGER.info("* [Done] get login session : %s" % loginSession)

    selectedTeeTimes = []

    #---------------------------------------------------------------#
    # 4. select book schedules
    #---------------------------------------------------------------#
    for x in CONFIG['book_schedules'][taskName]: #{

      bookDate = x.get('book_date',None)
      if not bookDate:
        bookDate = (dt.datetime.now() + dt.timedelta(days=BOOK_INTERVAL)).strftime("%Y-%m-%d")

      courseCode = CONFIG['course'][x['course']]['code']
      courseName = CONFIG['course'][x['course']]['name']
      bookStartTimeUtc = convertTzEasternToUtc("{} {}:00".format(bookDate,x['start_time']))
      bookEndTimeUtc   = bookStartTimeUtc + dt.timedelta(minutes=x.get('duration',30))

      LOGGER.info("############################################")
      LOGGER.info("* CourseCode : {}".format(courseCode))
      LOGGER.info("* BookDate   : {}".format(bookDate))

      #---------------------------------------------------------------#
      # 4-1. wait and get tee time
      #---------------------------------------------------------------#
      teeTimes = []

      idx = 1
      while idx < 60:#{
        teeTimes = getTeeTimes(courseCode, bookDate)
        if teeTimes:
          LOGGER.info("* [Done] find tee time : %s" % idx)
          break
        LOGGER.info("* [Proc] Did not find tee time : %s" % idx)
        idx += 1
      #} while

      #---------------------------------------------------------------#
      # 4-2. select tee time
      #---------------------------------------------------------------#
      for x in teeTimes: #{
        teeTime = convertTzUtcToUtc(dt.datetime.strptime(x['teetime'],"%Y-%m-%dT%H:%M:%S.000Z").strftime("%Y-%m-%d %H:%M:%S"))

        LOGGER.info("%s <= %s <= %s" % (bookStartTimeUtc, teeTime, bookEndTimeUtc))

        if bookStartTimeUtc <= teeTime and teeTime <= bookEndTimeUtc:
          LOGGER.info("#########################################################")
          LOGGER.info("* [Done] select tee time : %s" % teeTime)
          LOGGER.info(x)
          LOGGER.info("#########################################################")
          selectedTeeTimes.append(x)
          break
      #} for
    #} for

    if selectedTeeTimes:
      #---------------------------------------------------------------#
      # 5. set cart and lock
      #---------------------------------------------------------------#
      for teeTimeInfo in selectedTeeTimes:#{
        setShoppingCart(cartSession, teeTimeInfo)
        LOGGER.info("* [Done] set shopping cart : %s" % teeTime)

        setLockTeeTime(loginSession, teeTimeInfo)
        LOGGER.info("* [Done] set lock tee time : %s" % teeTime)
      #}

      #---------------------------------------------------------------#
      # 6. set reservation
      #---------------------------------------------------------------#
      setReservation(driver)
      LOGGER.info("* [Done] set reservation")

      time.sleep(10)

    LOGGER.info("-------------  END  ------------------")
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
