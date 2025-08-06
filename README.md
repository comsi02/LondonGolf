# London Golf Reservation System

An automated tee time reservation system for London Golf courses.

## Table of Contents

- [System Requirements](#system-requirements)
- [Installation Guide](#installation-guide)
- [Usage](#usage)
- [Troubleshooting](#troubleshooting)
- [References](#references)

## System Requirements

- Python 3.8 or higher
- Chrome browser
- Redis 6
- Cron service

## Installation Guide

### 1. System Configuration

#### Clamshell Mode Setup (Mac)

```bash
# Enable clamshell mode
sudo pmset -b disablesleep 1

# Disable clamshell mode
sudo pmset -b disablesleep 0
```

### 2. Install Chrome Driver

```bash
# Configure Chrome repository
sudo vi /etc/yum.repos.d/google-chrome.repo
```

Add the following content:

```
[google-chrome]
name=google-chrome
baseurl=http://dl.google.com/linux/chrome/rpm/stable/x86_64
enabled=1
gpgcheck=1
gpgkey=https://dl-ssl.google.com/linux/linux_signing_key.pub
```

```bash
# Install Chrome
sudo yum -y install google-chrome-stable
```

### 3. Python Environment Setup

```bash
# Install Python package managers
sudo yum install python3-pip
sudo yum install python3-virtualenv

# Create virtual environment
python3 -m venv .venv

# Activate virtual environment
source .venv/bin/activate

# Install required packages
pip install -r requirements.txt
```

### 4. Service Configuration

#### Redis Service

```bash
# Install and enable Redis
sudo yum install redis6
sudo systemctl enable redis6.service
```

#### Cron Service

```bash
# Install and enable Cron
sudo yum install cronie -y
sudo systemctl enable crond.service
```

## Usage

1. Activate Virtual Environment

```bash
source .venv/bin/activate
```

2. Run the Program

```bash
python londonGolfBook.py -d yes -t task1
```

## Troubleshooting

- Chrome driver version mismatch: Please ensure Chrome browser and driver versions match.
- Redis connection error: Check if Redis service is running.
- Cron job failure: Verify the cron service status.

## References

- [Selenium Python API Documentation](https://www.selenium.dev/selenium/docs/api/py/api.html#common)
- [Selenium Wire Documentation](https://pypi.org/project/selenium-wire/#request-objects)
- [Selenium Example Code](https://gist.github.com/mcchae/c9323d426aba8fcde3c1b54731f6cfbe)
- [Tee Times API Example](https://phx-api-be-east-1b.kenna.io/v2/tee-times?date=2023-07-01&facilityIds=9710)

