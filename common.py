# -*- coding:utf-8 -*-
def getLogger():
  try:
    import os, sys
    import logging
    from logging.handlers import TimedRotatingFileHandler

    logFile = os.path.dirname(os.path.abspath(__file__)) + '/logs/' + os.path.splitext(sys.argv[0])[0] + '.log'
    if not os.path.isdir(os.path.dirname(logFile)):
        os.makedirs(os.path.dirname(logFile))
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)
    log_handler = TimedRotatingFileHandler(logFile, when='midnight', interval=1, backupCount=100)
    log_handler.setFormatter(logging.Formatter("%(asctime)-15s,%(message)s"))
    log_handler.suffix = "%Y%m%d"
    logger.addHandler(log_handler)
    return logger
  except Exception as ex:
    print(str(ex))

def getLogStr(logA):
  return ','.join(["%s"]*len(logA)) % tuple([str(x) for x in logA])

def getConfig():
  try:
    import os, sys
    import yaml
    confFile = os.path.dirname(os.path.abspath(__file__)) + '/' + os.path.splitext(sys.argv[0])[0] + '.yaml'
    with open(confFile, "r") as f:
      return yaml.safe_load(f)
  except yaml.YAMLError as ex:
    print(str(ex))
