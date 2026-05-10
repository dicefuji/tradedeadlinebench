"""OpenRouter API client with caching and cost tracking.

All LLM API calls route through OpenRouter using the OpenAI-compatible
/v1/chat/completions endpoint.  Uses httpx directly (not the OpenAI SDK)
so that connect / read timeouts are reliably enforced and the raw JSON
body — including ``usage.cost`` — is always available.

Responses are cached by
(model_id, prompt_hash, team, run_id, turn_index) for reproducibility.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# Suppress noisy per-request httpx logging
logging.getLogger("httpx").setLevel(logging.WARNING)

# 30 s connect, 180 s read (some models are slow on long prompts)
_DEFAULT_TIMEOUT = httpx.Timeout(180.0, connect=30.0)
# Hard ceiling enforced via thread pool — kills truly stuck requests
_HARD_TIMEOUT_SECONDS = 210
_MAX_RETRIES = 3


class CostTracker:
    """Tracks per-run and cumulative API costs from OpenRouter metadata."""

    def __init__(self) -> None:
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_dollars = 0.0
        self.per_call: list[dict] = []

    def record(self, model: str, usage: dict, generation_cost: float | None) -> None:
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        cost = generation_cost if generation_cost is not None else 0.0

        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_dollars += cost
        self.per_call.append({
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_dollars": cost,
        })

    def to_dict(self) -> dict:
        return {
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_dollars": self.total_dollars,
            "num_calls": len(self.per_call),
        }


class APICache:
    """JSONL-based API response cache for reproducibility.

    Cache key: (model_id, prompt_hash, team, run_id, turn_index)
    """

    def __init__(self, cache_path: Path) -> None:
        self.cache_path = cache_path
        self._cache: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self.cache_path.exists():
            with open(self.cache_path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        entry = json.loads(line)
                        self._cache[entry["cache_key"]] = entry

    @staticmethod
    def make_key(
        model_id: str,
        prompt_hash: str,
        team: str,
        run_id: int,
        turn_index: int,
    ) -> str:
        return f"{model_id}|{prompt_hash}|{team}|{run_id}|{turn_index}"

    @staticmethod
    def hash_prompt(system_prompt: str, messages: list[dict]) -> str:
        content = json.dumps({"system": system_prompt, "messages": messages}, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()

    def get(self, cache_key: str) -> dict | None:
        entry = self._cache.get(cache_key)
        if entry is not None:
            return entry["response"]
        return None

    def put(self, cache_key: str, response: dict) -> None:
        entry = {"cache_key": cache_key, "response": response}
        self._cache[cache_key] = entry
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_path, "a") as f:
            f.write(json.dumps(entry, separators=(",", ":")) + "\n")

    @property
    def hit_count(self) -> int:
        return self._hit_count if hasattr(self, "_hit_count") else 0

    @property
    def miss_count(self) -> int:
        return self._miss_count if hasattr(self, "_miss_count") else 0


class OpenRouterClient:
    """Single API surface for all LLM calls via OpenRouter.

    Uses httpx directly for reliable timeout control and raw-JSON access.
    """

    OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

    def __init__(
        self,
        api_key: str | None = None,
        cache: APICache | None = None,
        cost_tracker: CostTracker | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY not set")

        self._headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        self.cache = cache
        self.cost_tracker = cost_tracker or CostTracker()
        self._cache_hits = 0
        self._cache_misses = 0

    def call(
        self,
        model_id: str,
        system_prompt: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        team: str = "",
        run_id: int = 0,
        turn_index: int = 0,
        temperature: float = 0.0,
    ) -> dict:
        """Make an LLM API call, checking cache first.

        Returns a dict with keys: content, tool_calls, usage, model.
        """
        prompt_hash = APICache.hash_prompt(system_prompt, messages)
        cache_key = APICache.make_key(model_id, prompt_hash, team, run_id, turn_index)

        if self.cache is not None:
            cached = self.cache.get(cache_key)
            if cached is not None:
                self._cache_hits += 1
                return cached

        self._cache_misses += 1

        full_messages = [{"role": "system", "content": system_prompt}] + messages

        payload: dict = {
            "model": model_id,
            "messages": full_messages,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        t0 = time.monotonic()

        raw_body: dict | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                raw_body = self._post_with_hard_timeout(payload)
                break
            except Exception as exc:
                elapsed = time.monotonic() - t0
                if attempt < _MAX_RETRIES - 1:
                    wait_time = 2 ** attempt * 5
                    logger.warning(
                        "API call attempt %d/%d failed after %.1fs (%s: %s), retrying in %ds",
                        attempt + 1, _MAX_RETRIES, elapsed,
                        type(exc).__name__, exc, wait_time,
                    )
                    time.sleep(wait_time)
                    t0 = time.monotonic()
                else:
                    logger.error(
                        "API call failed after %d attempts (%.1fs): %s",
                        _MAX_RETRIES, elapsed, exc,
                    )
                    raise

        assert raw_body is not None

        elapsed = time.monotonic() - t0
        logger.debug("API call to %s completed in %.1fs", model_id, elapsed)

        # --- Parse the raw JSON ourselves --------------------------------
        choice = raw_body["choices"][0]
        message = choice["message"]

        # Cost from OpenRouter's usage.cost field
        generation_cost = None
        raw_usage = raw_body.get("usage") or {}
        if "cost" in raw_usage:
            try:
                generation_cost = float(raw_usage["cost"])
            except (ValueError, TypeError):
                pass

        tool_calls_list: list[dict] = []
        for tc in message.get("tool_calls") or []:
            tool_calls_list.append({
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["function"]["name"],
                    "arguments": tc["function"]["arguments"],
                },
            })

        usage_dict: dict = {}
        if raw_usage:
            usage_dict = {
                "prompt_tokens": raw_usage.get("prompt_tokens", 0),
                "completion_tokens": raw_usage.get("completion_tokens", 0),
                "total_tokens": raw_usage.get("total_tokens", 0),
            }

        result = {
            "content": message.get("content") or "",
            "tool_calls": tool_calls_list,
            "usage": usage_dict,
            "model": model_id,
            "finish_reason": choice.get("finish_reason", ""),
        }

        if self.cache is not None:
            self.cache.put(cache_key, result)

        self.cost_tracker.record(model_id, usage_dict, generation_cost)

        return result

    def _post_with_hard_timeout(self, payload: dict) -> dict:
        """POST to /chat/completions with a hard daemon-thread timeout.

        Each call creates a fresh httpx connection (no pool reuse) so stale
        CLOSE-WAIT sockets cannot cause indefinite hangs.  The worker runs
        on a daemon thread so the main thread is never blocked by cleanup.
        """
        url = f"{self.OPENROUTER_BASE_URL}/chat/completions"
        result_box: list[dict] = []
        error_box: list[Exception] = []

        def _do_post() -> None:
            try:
                resp = httpx.post(
                    url,
                    json=payload,
                    headers=self._headers,
                    timeout=_DEFAULT_TIMEOUT,
                )
                if resp.status_code >= 400:
                    logger.warning(
                        "HTTP %d response body: %s",
                        resp.status_code,
                        resp.text[:1000],
                    )
                resp.raise_for_status()
                result_box.append(resp.json())
            except Exception as exc:
                error_box.append(exc)

        worker = threading.Thread(target=_do_post, daemon=True)
        worker.start()
        worker.join(timeout=_HARD_TIMEOUT_SECONDS)

        if worker.is_alive():
            logger.warning("Hard timeout fired after %ds — abandoning request", _HARD_TIMEOUT_SECONDS)
            raise TimeoutError(
                f"API call exceeded hard timeout of {_HARD_TIMEOUT_SECONDS}s"
            )

        if error_box:
            raise error_box[0]

        if not result_box:
            raise RuntimeError("API call returned no result and no error")

        return result_box[0]

    def verify_model(self, model_id: str) -> bool:
        """Verify a model ID is available on OpenRouter."""
        try:
            resp = httpx.get(
                f"{self.OPENROUTER_BASE_URL}/models",
                headers=self._headers,
                timeout=_DEFAULT_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])
            available_ids = {m["id"] for m in data}
            return model_id in available_ids
        except Exception:
            return False

    @property
    def cache_hits(self) -> int:
        return self._cache_hits

    @property
    def cache_misses(self) -> int:
        return self._cache_misses
