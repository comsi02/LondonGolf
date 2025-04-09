# London Golf Reservation System

London Golf 코스의 티타임을 자동으로 예약하는 시스템입니다.

## 목차

- [시스템 요구사항](#시스템-요구사항)
- [설치 가이드](#설치-가이드)
- [사용 방법](#사용-방법)
- [문제 해결](#문제-해결)
- [참고 자료](#참고-자료)

## 시스템 요구사항

- Python 3.8 이상
- Chrome 브라우저
- Redis 6
- Cron 서비스

## 설치 가이드

### 1. 시스템 설정

#### 클램쉘 설정 (Mac)

```bash
# 클램쉘 활성화
sudo pmset -b disablesleep 1

# 클램쉘 비활성화
sudo pmset -b disablesleep 0
```

### 2. Chrome 드라이버 설치

```bash
# Chrome 저장소 설정
sudo vi /etc/yum.repos.d/google-chrome.repo
```

다음 내용을 추가:

```
[google-chrome]
name=google-chrome
baseurl=http://dl.google.com/linux/chrome/rpm/stable/x86_64
enabled=1
gpgcheck=1
gpgkey=https://dl-ssl.google.com/linux/linux_signing_key.pub
```

```bash
# Chrome 설치
sudo yum -y install google-chrome-stable
```

### 3. Python 환경 설정

```bash
# Python 패키지 관리자 설치
sudo yum install python3-pip
sudo yum install python3-virtualenv

# 가상환경 생성
python3 -m venv .venv

# 가상환경 활성화
source .venv/bin/activate

# 필요한 패키지 설치
pip install -r requirements.txt
```

### 4. 서비스 설정

#### Redis 서비스

```bash
# Redis 설치 및 활성화
sudo yum install redis6
sudo systemctl enable redis6.service
```

#### Cron 서비스

```bash
# Cron 설치 및 활성화
sudo yum install cronie -y
sudo systemctl enable crond.service
```

## 사용 방법

1. 가상환경 활성화

```bash
source .venv/bin/activate
```

2. 프로그램 실행

```bash
python londonGolfBook.py -d yes -t task1
```

## 문제 해결

- Chrome 드라이버 버전 불일치: Chrome 브라우저와 드라이버 버전을 일치시켜주세요.
- Redis 연결 오류: Redis 서비스가 실행 중인지 확인하세요.
- Cron 작업 실패: cron 서비스 상태를 확인하세요.

## 참고 자료

- [Selenium Python API 문서](https://www.selenium.dev/selenium/docs/api/py/api.html#common)
- [Selenium Wire 문서](https://pypi.org/project/selenium-wire/#request-objects)
- [Selenium 예제 코드](https://gist.github.com/mcchae/c9323d426aba8fcde3c1b54731f6cfbe)
- [Tee Times API 예시](https://phx-api-be-east-1b.kenna.io/v2/tee-times?date=2023-07-01&facilityIds=9710)
