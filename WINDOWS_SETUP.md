# London Golf Booking - Windows Setup Guide

이 문서는 **London Golf Booking Bot**을 Windows 환경에서 설치하고, 예약 스케줄러를 통해 매일 자동 실행되도록 설정하는 방법을 설명합니다.

---

## 1. 사전 준비 및 패키지 설치

Windows에서는 Python 패키지 관리자인 `uv`를 이용하여 의존성과 브라우저(Chromium)를 격리된 환경에 깔끔하게 설치합니다.

### 1-1. `uv` 패키지 관리자 설치
Windows PowerShell을 열고 아래 명령어를 입력하여 `uv`를 설치합니다.
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 1-2. 프로젝트 설정 및 의존성 설치
코드가 위치한 폴더(예: `C:\Users\comsi02\LondonGolf`)로 이동한 후, `uv sync`를 통해 파이썬 패키지를 설치합니다.
```powershell
cd C:\Users\comsi02\LondonGolf
uv sync
```
> [!NOTE]
> `uv sync`를 실행하면 `pyproject.toml`에 정의된 Windows용 필수 패키지(`tzdata` 등)가 자동으로 설치됩니다.

### 1-3. Playwright 브라우저 설치
웹 자동화를 위한 크롬 브라우저(Chromium) 엔진을 다운로드합니다.
```powershell
uv run playwright install chromium
```

---

## 2. 수동 실행 테스트

자동화를 설정하기 전, 봇이 정상적으로 작동하는지 터미널에서 직접 실행해 봅니다. (예: `pro_song` 작업 실행)
```powershell
uv run python londonGolfBook.py pro_song --headless
```
로그가 정상적으로 출력되고 에러가 없다면 다음 단계로 넘어갑니다.

---

## 3. 주기적 자동 실행 설정 (작업 스케줄러)

Mac의 `cron` 역할을 하는 Windows의 **작업 스케줄러(Task Scheduler)**를 설정합니다.

### 3-1. 실행용 Batch(`.bat`) 파일 만들기
작업 스케줄러에 파이썬 명령어를 직접 넣는 것보다 배치 파일을 만들어 실행하는 것이 훨씬 안정적입니다.
프로젝트 루트 폴더(예: `C:\Users\comsi02\LondonGolf`)에 `run_golf_bot.bat` 파일을 새로 만들고 아래 코드를 붙여넣습니다.

```bat
@echo off
:: 프로젝트 폴더로 이동 (드라이브 문자가 다를 경우 cd /d 사용 권장)
cd /d "C:\Users\comsi02\LondonGolf"

:: 백그라운드 환경에서 브라우저 UI 없이 실행하고, 결과를 cron_run.log에 저장합니다.
uv run python londonGolfBook.py pro_song --headless >> cron_run.log 2>&1
```

### 3-2. 작업 스케줄러에 등록하기
1. Windows 검색창에 **작업 스케줄러(Task Scheduler)** 를 검색해서 실행합니다.
2. 우측 작업 패널에서 **기본 작업 만들기(Create Basic Task...)** 를 클릭합니다.
3. **이름:** `London Golf Booking Bot` 등 알아보기 쉽게 입력하고 [다음]을 누릅니다.
4. **트리거:** `매일(Daily)`을 선택하고, 예약 시도를 시작할 시간을 지정합니다. (예: 오후 8시 59분)
5. **작업:** `프로그램 시작(Start a program)`을 선택합니다.
6. **프로그램/스크립트:** `찾아보기(Browse)` 버튼을 눌러 방금 만든 `run_golf_bot.bat` 파일을 선택합니다.
   - **시작 위치(Start in):** 선택 사항이지만 `C:\Users\comsi02\LondonGolf` 라고 명시해 두면 더 안전합니다.
7. [마침]을 누릅니다.

### 3-3. 팝업창 숨기기 (백그라운드 무음 실행)
배치 파일이 실행될 때마다 검은색 CMD 창이 화면에 뜨는 것을 방지하려면 다음 설정을 추가합니다.

1. 스케줄러 라이브러리(목록)에서 방금 만든 `London Golf Booking Bot`을 찾아 **우클릭 -> 속성(Properties)** 을 클릭합니다.
2. **일반(General)** 탭에서 하단의 **"사용자의 로그온 여부에 관계없이 실행(Run whether user is logged on or not)"** 항목에 체크합니다.
3. [확인]을 누르면 Windows 계정 비밀번호를 물어보는데, 비밀번호를 입력해 저장해 둡니다.

> [!TIP]
> 이제 설정하신 시간에 맞춰 컴퓨터 화면에 아무 창도 뜨지 않고, 백그라운드에서 예약 봇이 조용히 작동합니다. 실행 내역 및 성공/실패 여부는 프로젝트 폴더 안의 `cron_run.log` 파일을 열어 확인하실 수 있습니다.
