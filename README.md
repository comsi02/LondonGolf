# LondonGolf
London Golf Reservation

# 클램쉘 설정
- ON: sudo pmset -b disablesleep 1
- OFF: sudo pmset -b disablesleep 0

# install chrome-driver
- sudo vi /etc/yum.repos.d/google-chrome.repo
```
[google-chrome]
name=google-chrome
baseurl=http://dl.google.com/linux/chrome/rpm/stable/x86_64
enabled=1
gpgcheck=1
gpgkey=https://dl-ssl.google.com/linux/linux_signing_key.pub
```
- sudo yum -y install google-chrome-stable

# python module install
- sudo yum install python3-pip
- sudo yum install python3-virtualenv

# venv 생성

- python3 -m venv .venv

# venv 적용

- source .venv/bin/activate

# package 설치

- pip install -r requirements.txt

# redis6 서비스 등록
- sudo yum install redis6
- sudo systemctl enable redis6.service

# cron 서비스 등록
- sudo yum install cronie -y
- sudo systemctl enable crond.service

# 참고
- https://www.selenium.dev/selenium/docs/api/py/api.html#common
- https://pypi.org/project/selenium-wire/#request-objects
- https://gist.github.com/mcchae/c9323d426aba8fcde3c1b54731f6cfbe
- https://phx-api-be-east-1b.kenna.io/v2/tee-times?date=2023-07-01&facilityIds=9710

