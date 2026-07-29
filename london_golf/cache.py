"""Tee-time deduplication cache backed by Redis or a local JSON file."""

import json
import logging
import os
from typing import Any, Dict, Optional

import redis

from london_golf.constants import LOCAL_CACHE_FILE


class CacheManager:
    """Deduplicate tee times: Redis if configured, else local JSON."""

    def __init__(self, config: Dict[str, Any], logger: logging.Logger) -> None:
        self._logger = logger
        self.use_redis = False
        self.redis_connection = None
        self.cache_file = LOCAL_CACHE_FILE
        self.cache_data: Dict[str, Any] = {}

        redis_cfg = config.get("redis") or {}
        if isinstance(redis_cfg, dict) and "host" in redis_cfg and "port" in redis_cfg:
            try:
                self.redis_connection = redis.Redis(
                    host=redis_cfg["host"],
                    port=redis_cfg["port"],
                    decode_responses=True,
                )
                self.redis_connection.ping()
                self.use_redis = True
                self._logger.info("Using Redis for caching")
            except (redis.exceptions.RedisError, OSError, ValueError) as exc:
                self._logger.info(
                    "Redis connection failed: %s. Using local file cache instead.",
                    exc,
                )
                self.use_redis = False

        if not self.use_redis and os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, encoding="utf-8") as file_handle:
                    self.cache_data = json.load(file_handle)
                self._logger.info("Loaded local cache from %s", self.cache_file)
            except (OSError, json.JSONDecodeError, TypeError) as exc:
                self._logger.info(
                    "Failed to load local cache: %s. Starting with empty cache.",
                    exc,
                )
                self.cache_data = {}

    def get(self, key: str) -> Optional[str]:
        """Return cached string value or None."""
        if self.use_redis:
            return self.redis_connection.get(key)
        return self.cache_data.get(key)

    def set(self, key: str, value: str, expire_seconds: int = 300) -> None:
        """Store value; Redis TTL or persist JSON for file cache."""
        if self.use_redis:
            self.redis_connection.set(key, value)
            self.redis_connection.expire(key, expire_seconds)
        else:
            self.cache_data[key] = value
            try:
                with open(self.cache_file, "w", encoding="utf-8") as file_handle:
                    json.dump(self.cache_data, file_handle)
            except (OSError, TypeError) as exc:
                self._logger.info("Failed to save local cache: %s", exc)

    def delete(self, key: str) -> None:
        """Remove a key from cache."""
        if self.use_redis:
            self.redis_connection.delete(key)
        elif key in self.cache_data:
            del self.cache_data[key]
            try:
                with open(self.cache_file, "w", encoding="utf-8") as file_handle:
                    json.dump(self.cache_data, file_handle)
            except (OSError, TypeError) as exc:
                self._logger.info("Failed to save local cache: %s", exc)
