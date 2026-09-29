"""Secrets — AWS Secrets Manager in prod, plain environment in dev.

    get_secret("JWT_SECRET", default="dev-only")

One call-site pattern for both environments, so promoting a value to Secrets
Manager is an infra change, not a code change:

  * APP_ENV=dev  (default): read os.environ — which load_dotenv() has already
    populated from .env.
  * APP_ENV=prod: try Secrets Manager first (cached per process), fall back to
    the environment. The fallback matters on App Runner / ECS, which commonly
    inject Secrets Manager values AS environment variables.

This module reads APP_ENV / SECRETS_PREFIX straight from the environment
rather than importing app.config: config.py calls get_secret() at import time,
so importing the other way would be circular. It is the one sanctioned
exception to "config.py is the only reader of the environment".

Secret NAMES may appear in logs; secret VALUES never do.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

_cache: dict[str, str] = {}


def _app_env() -> str:
    return os.getenv("APP_ENV", "dev").lower()


def _from_secrets_manager(name: str) -> str | None:
    """One cached Secrets Manager lookup. None on any failure — the caller
    falls back to the environment rather than crashing boot."""
    if name in _cache:
        return _cache[name]
    prefix = os.getenv("SECRETS_PREFIX", "step1")
    try:
        import boto3

        client = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "us-east-1"))
        value = client.get_secret_value(SecretId=f"{prefix}/{name}")["SecretString"]
    except Exception as exc:  # missing secret, no creds, no network — all fall back
        log.warning("Secrets Manager lookup failed for %s/%s: %s", prefix, name, type(exc).__name__)
        return None
    _cache[name] = value
    return value


def get_secret(name: str, default: str = "") -> str:
    """The one accessor. `name` is the plain env-var-style key, e.g. "JWT_SECRET"."""
    if _app_env() == "prod":
        value = _from_secrets_manager(name)
        if value is not None:
            return value
    return os.getenv(name, default)
