"""The one place that calls a language model.

LLM_BACKEND chooses:

  * bedrock: Claude on Amazon Bedrock, through bedrock-runtime's Converse
    API. TAILOR_MODEL_ID names the inference profile.
  * fake: no model at all. Deterministic answers built from the input, for
    the tests and for working on the app without AWS. Tests can swap in
    their own answer with `use_fake(fn)`.

Every call asks for exactly one tool call whose input is the JSON the caller
wants, with a JSON schema for it: the structured output. What comes back is
still checked by the caller (services/tailor.py), because a schema says what
shape the answer has, not whether it is true.

Timeouts are short and bounded, a throttled call is retried once after a
short pause, and anything else that goes wrong at Bedrock is LLMUnavailable,
which the routes turn into a 503. Token usage is logged for every call; the
prompts and answers, which hold a person's resume, never are.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass

from app import config

log = logging.getLogger(__name__)

# Bedrock error codes that mean "not now", worth one more try.
_RETRY = {"ThrottlingException", "ServiceUnavailableException", "ModelNotReadyException"}
_RETRY_PAUSE_S = 2.0


class LLMUnavailable(Exception):
    """The model could not be reached or refused for a reason that is not the
    caller's fault. The message is for the log, never the response."""


class LLMBadOutput(Exception):
    """The model answered, but not with the tool call it was asked for."""


@dataclass
class Usage:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    latency_ms: int = 0


# --------------------------------------------------------------------------- #
# Fake
# --------------------------------------------------------------------------- #

FakeFn = Callable[[str, str], dict]
_fake: FakeFn | None = None


def use_fake(fn: FakeFn | None) -> None:
    """Tests: answer every fake call with fn(task, user_message)."""
    global _fake
    _fake = fn


def _call_fake(task: str, user: str) -> tuple[dict, Usage]:
    if _fake is not None:
        return _fake(task, user), Usage(model="fake")
    from app.services import tailor

    return tailor.fake_answer(task, user), Usage(model="fake")


# --------------------------------------------------------------------------- #
# Bedrock
# --------------------------------------------------------------------------- #


def _bedrock():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "bedrock-runtime",
        region_name=config.AWS_REGION,
        config=Config(
            connect_timeout=5,
            read_timeout=config.LLM_TIMEOUT_S,
            # One attempt here; the one retry is ours, below, so it is counted.
            retries={"max_attempts": 1, "mode": "standard"},
        ),
    )


def _call_bedrock(
    *, task: str, system: str, user: str, tool: str, description: str, schema: dict, max_tokens: int
) -> tuple[dict, Usage]:
    from botocore.exceptions import BotoCoreError, ClientError

    request = {
        "modelId": config.TAILOR_MODEL_ID,
        # The instructions are the same for every call of a task: cached
        # once long enough to be (below the model's minimum it is a no-op).
        "system": [{"text": system}, {"cachePoint": {"type": "default"}}],
        "messages": [{"role": "user", "content": [{"text": user}]}],
        "inferenceConfig": {"maxTokens": max_tokens, "temperature": 0.2},
        "toolConfig": {
            "tools": [
                {
                    "toolSpec": {
                        "name": tool,
                        "description": description,
                        "inputSchema": {"json": schema},
                    }
                }
            ],
            "toolChoice": {"tool": {"name": tool}},
        },
    }
    client = _bedrock()
    for attempt in (1, 2):
        started = time.perf_counter()
        try:
            response = client.converse(
                modelId=request["modelId"],
                system=request["system"],
                messages=request["messages"],
                inferenceConfig=request["inferenceConfig"],
                toolConfig=request["toolConfig"],
            )
            break
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "ClientError")
            if code in _RETRY and attempt == 1:
                log.warning("llm: %s, retrying once", code, extra={"task": task})
                time.sleep(_RETRY_PAUSE_S)
                continue
            raise LLMUnavailable(code) from None
        except BotoCoreError as exc:
            raise LLMUnavailable(type(exc).__name__) from None

    usage_raw = response.get("usage", {})
    usage = Usage(
        model=config.TAILOR_MODEL_ID,
        input_tokens=usage_raw.get("inputTokens", 0),
        output_tokens=usage_raw.get("outputTokens", 0),
        cache_read_tokens=usage_raw.get("cacheReadInputTokens", 0),
        cache_write_tokens=usage_raw.get("cacheWriteInputTokens", 0),
        latency_ms=round((time.perf_counter() - started) * 1000),
    )
    if response.get("stopReason") == "max_tokens":
        raise LLMBadOutput("the answer was cut off at max_tokens")
    for block in response.get("output", {}).get("message", {}).get("content", []):
        call = block.get("toolUse")
        if call and call.get("name") == tool and isinstance(call.get("input"), dict):
            return call["input"], usage
    raise LLMBadOutput(f"no {tool} call in the answer (stop: {response.get('stopReason')})")


# --------------------------------------------------------------------------- #
# The one entry point
# --------------------------------------------------------------------------- #


def call_tool(
    *,
    task: str,
    system: str,
    user: str,
    tool: str,
    description: str,
    schema: dict,
    max_tokens: int | None = None,
) -> tuple[dict, Usage]:
    """Ask the model for one `tool` call matching `schema`; return its input."""
    if config.LLM_BACKEND == "fake":
        answer, usage = _call_fake(task, user)
    else:
        answer, usage = _call_bedrock(
            task=task,
            system=system,
            user=user,
            tool=tool,
            description=description,
            schema=schema,
            max_tokens=max_tokens or config.LLM_MAX_TOKENS,
        )
    # Counts and timings only. Never the prompt or the answer.
    log.info("llm call", extra={"task": task} | asdict(usage))
    return answer, usage
