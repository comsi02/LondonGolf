"""Load YAML configuration and resolve default config path using Pydantic."""

import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import yaml
from pydantic import BaseModel, ValidationError, model_validator

from london_golf.exceptions import ConfigError


class CourseConfig(BaseModel):
    code: int
    name: str


class AuthConfig(BaseModel):
    userid: str
    password: str


class RedisConfig(BaseModel):
    host: str
    port: int


class TaskScheduleRow(BaseModel):
    book_date: Optional[str] = None
    book_count: int = 1
    start_time: str
    duration: int = 30
    slot: int = 0
    course: Union[str, List[str]]


class ScheduleTaskConfig(BaseModel):
    auth: Optional[str] = None
    weekdays: Dict[str, Optional[TaskScheduleRow]]

    @model_validator(mode="after")
    def inherit_empty_weekdays(self):
        last_valid = None
        for day in reversed(list(self.weekdays.keys())):
            if self.weekdays[day] is not None:
                last_valid = self.weekdays[day]
            else:
                if last_valid is None:
                    raise ValueError(
                        f"Cannot inherit settings for '{day}': no subsequent configuration found."
                    )
                self.weekdays[day] = last_valid
        return self


class AppConfig(BaseModel):
    course: Dict[str, CourseConfig]
    authentication: Dict[str, AuthConfig]
    redis: Optional[RedisConfig] = None
    schedule: Dict[str, ScheduleTaskConfig]


def resolve_default_config_path() -> Path:
    """Default YAML in repo root; stem from script name when applicable."""
    if env := os.environ.get("LONDON_GOLF_CONFIG"):
        return Path(env).expanduser().resolve()
    repo_root = Path(__file__).resolve().parent.parent
    stem = Path(sys.argv[0]).resolve().stem
    if stem in ("cli", "__main__"):
        return repo_root / "londonGolfBook.yaml"
    return repo_root / f"{stem}.yaml"


def load_config(path: Optional[Path] = None) -> AppConfig:
    """Load and validate YAML config via Pydantic. Raises ConfigError on failure."""
    config_path = path or resolve_default_config_path()
    if not config_path.is_file():
        raise ConfigError(f"Config file not found: {config_path}")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except OSError as e:
        raise ConfigError(f"Cannot read config {config_path}: {e}") from e
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML in {config_path}: {e}") from e

    if not isinstance(data, dict):
        raise ConfigError(f"Config root must be a mapping: {config_path}")

    try:
        return AppConfig(**data)
    except ValidationError as e:
        raise ConfigError(f"Configuration validation failed:\n{e}") from e


def get_task_schedule_entries(config: AppConfig, task_name: str) -> Dict[str, TaskScheduleRow]:
    """Return schedule weekday mapping for ``task_name``."""
    if task_name not in config.schedule:
        raise ConfigError(f"Unknown schedule task: {task_name}")

    block = config.schedule[task_name]
    return block.weekdays


def get_task_credentials(config: AppConfig, task_name: str) -> Tuple[str, str]:
    """Return ``(userid, password)`` for ``task_name``."""
    if task_name not in config.schedule:
        raise ConfigError(f"Unknown schedule task: {task_name}")

    block = config.schedule[task_name]
    auth_key = block.auth if block.auth else task_name

    if auth_key not in config.authentication:
        raise ConfigError(f"Unknown authentication key: {auth_key}")

    creds = config.authentication[auth_key]
    return creds.userid, creds.password
