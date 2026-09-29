"""Secrets: from the environment, or from AWS Secrets Manager.

    get_secret("JWT_SECRET", default="dev-only")

One call for every secret-bearing setting, so that where a value lives is a
deployment decision and not a code change. SECRETS_BACKEND chooses:

  * env: read the environment, which in development load_dotenv() has
    filled from .env. This is also the recommended production setting on
    ECS, where the task definition injects each secret as an environment
    variable (`secrets` with `valueFrom` an SSM parameter or a Secrets
    Manager ARN). The container then needs no AWS call and no permission of
    its own to learn its secrets; the task execution role fetches them
    before the container starts.
  * secretsmanager: ask Secrets Manager for <SECRETS_PREFIX>/<NAME>,
    cached per process, and fall back to the environment. For platforms
    that cannot inject secrets.

Unset, it is `secretsmanager` when APP_ENV=prod and `env` otherwise, which is
what this module did before the setting existed.

This module reads APP_ENV, SECRETS_BACKEND and SECRETS_PREFIX straight from
the environment rather than importing app.config: config.py calls
get_secret() while it is being imported, so importing the other way would be
circular. It is the one sanctioned exception to "config.py is the only reader
of the environment".

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


def backend() -> str:
    chosen = os.getenv("SECRETS_BACKEND", "").strip().lower()
    return chosen or ("secretsmanager" if _app_env() == "prod" else "env")


def get_secret(name: str, default: str = "") -> str:
    """The one accessor. `name` is the plain env-var-style key, e.g. "JWT_SECRET"."""
    if backend() == "secretsmanager":
        value = _from_secrets_manager(name)
        if value is not None:
            return value
    return os.getenv(name, default)
