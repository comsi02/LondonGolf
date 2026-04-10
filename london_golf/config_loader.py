"""Load YAML configuration and resolve default config path."""

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from london_golf.exceptions import ConfigError


def resolve_default_config_path() -> Path:
    """Default YAML in repo root; stem from script name when applicable."""
    if env := os.environ.get("LONDON_GOLF_CONFIG"):
        return Path(env).expanduser().resolve()
    repo_root = Path(__file__).resolve().parent.parent
    stem = Path(sys.argv[0]).resolve().stem
    if stem in ("cli", "__main__"):
        return repo_root / "londonGolfBook.yaml"
    return repo_root / f"{stem}.yaml"


def load_config(path: Optional[Path] = None) -> Dict[str, Any]:
    """Load and validate YAML config. Raises ConfigError on failure."""
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
    return data


def get_task_schedule_entries(
    config: Dict[str, Any], task_name: str
) -> List[Dict[str, Any]]:
    """Return schedule rows for ``task_name``.

    Supports:

    - **Nested** (``example.yaml``): ``schedule.<task>: {auth: ..., tasks: [ ... ]}``
    - **Legacy list**: ``schedule.<task>: [ {weekday: ...}, ... ]``
    """
    try:
        block = config["schedule"][task_name]
    except KeyError as exc:
        raise ConfigError(f"Unknown schedule task: {task_name}") from exc
    except TypeError as exc:
        raise ConfigError("'schedule' must be a mapping of task names") from exc

    if isinstance(block, list):
        return block
    if isinstance(block, dict):
        if "tasks" in block:
            tasks = block["tasks"]
            if not isinstance(tasks, list):
                raise ConfigError(
                    f"schedule.{task_name}.tasks must be a list"
                )
            return tasks
    raise ConfigError(
        f"schedule.{task_name} must be a list of entries, or "
        f"{{auth: ..., tasks: [...]}}"
    )


def get_task_credentials(
    config: Dict[str, Any], task_name: str
) -> Tuple[str, str]:
    """Return ``(userid, password)`` for ``task_name``.

    Supports:

    - **Indirect auth** (``example.yaml``): ``schedule.<task>.auth`` names a key
      under ``authentication``.
    - **Per-task credentials** (legacy): ``authentication.<task>`` holds
      ``userid`` / ``password`` and ``schedule.<task>`` is a bare list.
    """
    try:
        block = config["schedule"][task_name]
    except KeyError as exc:
        raise ConfigError(f"Unknown schedule task: {task_name}") from exc

    auth_map = config.get("authentication")
    if not isinstance(auth_map, dict):
        raise ConfigError("'authentication' must be a mapping")

    if isinstance(block, dict) and "auth" in block:
        auth_key = block["auth"]
        if auth_key not in auth_map:
            raise ConfigError(f"Unknown authentication key: {auth_key}")
        creds = auth_map[auth_key]
    elif task_name not in auth_map:
        raise ConfigError(
            f"No credentials for task {task_name!r}: add "
            f"authentication.{task_name} or schedule.{task_name}.auth"
        )
    else:
        creds = auth_map[task_name]

    if not isinstance(creds, dict):
        raise ConfigError(f"Invalid credential entry for task {task_name!r}")
    try:
        return creds["userid"], creds["password"]
    except KeyError as exc:
        raise ConfigError(
            "Credentials need 'userid' and 'password' keys"
        ) from exc
