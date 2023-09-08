# -*- coding:utf-8 -*-
# ------------------------------------------------------------------------------
# https://www.selenium.dev/selenium/docs/api/py/api.html#common
# https://pypi.org/project/selenium-wire/#request-objects
# https://gist.github.com/mcchae/c9323d426aba8fcde3c1b54731f6cfbe
#
# --------- API ----------------------------------------------------------------
# https://phx-api-be-east-1b.kenna.io/v2/tee-times?date=2023-07-01&facilityIds=9710
# ------------------------------------------------------------------------------

import sys,time
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

def getCartSession(driver):
  try:
    driver.wait_for_request('https://phx-api-be-east-1b.kenna.io/course',TIMEOUT)
    driver.refresh()
    return driver.wait_for_request('https://phx-api-be-east-1b.kenna.io/shopping-cart/',TIMEOUT)
  except TimeoutException as ex:
    LOGGER.info("* Exception has been thrown. " + str(ex))

def getTeeTimes(course, date):

  headers = { 'X-Be-Alias': 'city-of-london-golf-courses'}
  res = requests.get("https://phx-api-be-east-1b.kenna.io/v2/tee-times?date=%s&facilityIds=%s" % (date, course), headers=headers)

  LOGGER.info(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
  LOGGER.info(res.json()[0]['dayInfo'])
  LOGGER.info(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")

  LOGGER.info("==========================")
  LOGGER.info(dt.datetime.utcnow())
  LOGGER.info(exchangeDatetime(dt.datetime.utcnow()))
  LOGGER.info("==========================")

  for x in res.json()[0]['teetimes']:

    if x['bookedPlayers'] == 0 and x['maxPlayers'] == 4:
      logA = []
      logA.append(x['courseId'])
      logA.append(x['teetime'])
      logA.append(x['rates'][0]['externalId'])
      logA.append(x['bookedPlayers'])
      logA.append(x['maxPlayers'])
      LOGGER.info(getLogStr(logA))


  rbj = {}
  rbj['item'] = {}
  rbj['item']['facilityId'] = 9714
  rbj['item']['type'] = "TeeTime"
  rbj['item']['extra'] = {}
  rbj['item']['extra']['teetime'] = "2023-07-10T22:51:00.000Z"
  rbj['item']['extra']['players'] = 4
  rbj['item']['extra']['price'] = 26
  rbj['item']['extra']['rate'] = {}
  rbj['item']['extra']['rate']['holes'] = 18
  rbj['item']['extra']['rate']['rateId'] = 560823234
  rbj['item']['extra']['rate']['rateSetId'] = 137191
  rbj['item']['extra']['rate']['name'] = "Walking"
  rbj['item']['extra']['rate']['transportation'] = "Walking"
  rbj['item']['extra']['featuredProducts'] = []

  data = rbj

  # 카트 담기 성공
  #cartSession = 'dffbfc10-21f3-4d33-8af3-f96dcbb863ea'
  #headers = { 'X-Be-Alias': 'city-of-london-golf-courses'}
  #res = requests.post("https://phx-api-be-east-1b.kenna.io/shopping-cart/%s/cart-item" % cartSession, headers=headers, json=data)
  #print(res.text)


def exchangeDatetime(utc, tz='US/Eastern'):
  try:
    return parser.isoparse(utc).astimezone(pytz.timezone(tz))
  except:
    if type(utc) == dt.datetime:
      utc = utc.strftime("%Y-%m-%d %H:%M:%S.000Z")
    return parser.isoparse(utc).astimezone(pytz.timezone(tz))

def main():

  LOGGER.info("")
  LOGGER.info("------------- START ------------------")

  parser = argparse.ArgumentParser(prog='London Golf Booking', description='London Golf Booking Batch', epilog='Copyright.2023.Andrew Song.All rights reserved.')
  parser.add_argument('-d', '--debug', required=True, choices=['yes','no'], help='use debug mode')  
  parser.add_argument('-t', '--task',  required=True, help='use task name')  

  args = parser.parse_args()

  print(args.debug)
  print(args.task)

  print(dt.datetime.now())

  courseCode = CONFIG['course']['TRAD']['code']
  courseName = CONFIG['course']['TRAD']['name']

  print(exchangeDatetime(dt.datetime.utcnow()))
  print(exchangeDatetime(dt.datetime.utcnow() + dt.timedelta(days=7)))

  for x in CONFIG['book_schedules'][args.task]:
    print(x)

  sys.exit(0)




  getTeeTimes(courseCode, exchangeDatetime(dt.datetime.utcnow() + dt.timedelta(days=7)).strftime("%Y-%m-%d"))

  options = webdriver.ChromeOptions()
  #options.add_argument('--allow-insecure-localhost')
  #options.add_argument('--no-sandbox')
  #options.add_argument('--disable-gpu')
  #options.add_argument('--headless')
  #options.add_argument('--disable-dev-shm-usage')
  #options.add_argument('--allow-running-insecure-content')
  #options.add_argument('--ignore-certificate-errors')

  seleniumwire_options = {
  }

  driver = webdriver.Chrome(
      options = options,
      seleniumwire_options=seleniumwire_options
  )

  driver.set_window_size(500,1000)

  # for test
  '''
  '''
  driver.get(CONFIG['url']['teetimes'])

  # for real
  '''
  driver.get(CONFIG['url']['login'])
  driver.implicitly_wait(TIMEOUT)

  WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.ID,'txtUsername1'))).send_keys(CONFIG['login']['userid'])
  WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.ID,'txtPassword1'))).send_keys(CONFIG['login']['password'])
  WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.CLASS_NAME,'MuiButton-label'))).click()
  '''

  cart_session_request = getCartSession(driver)
  cart_session = cart_session_request.path.split('/')[-1]

  LOGGER.info("Golf API url : %s" % CONFIG['url'])
  LOGGER.info("Golf Course  : %s" % CONFIG['course'])
  LOGGER.info("Cart Session : %s" % cart_session)

  # Access requests via the `requests` attribute
  '''
  for request in driver.requests:
      if request.response and request.response.status_code == 200:
          LOGGER.info("%s,%s,%s" % (
              request.url,
              request.response.status_code,
              request.response.headers['Content-Type']
          ))
  '''

  time.sleep(5)

if __name__ == '__main__':
  main()
