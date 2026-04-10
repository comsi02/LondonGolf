# -*- coding: utf-8 -*-
"""Legacy helpers; prefer london_golf.logging_config and config_loader."""

from london_golf.config_loader import load_config, resolve_default_config_path
from london_golf.logging_config import get_logger


def getLogger():
    """Return the application logger (historical name for scripts)."""
    return get_logger()


def getConfig():
    """Load config from the default path (historical name for scripts)."""
    return load_config(resolve_default_config_path())
