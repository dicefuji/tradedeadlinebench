"""OpenRouter API client with caching and cost tracking.

All LLM API calls route through OpenRouter using the OpenAI-compatible
/v1/chat/completions endpoint. Responses are cached by
(model_id, prompt_hash, team, run_id, turn_index) for reproducibility.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from openai import OpenAI


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

    Uses the OpenAI Python SDK pointed at the OpenRouter base URL.
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

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.OPENROUTER_BASE_URL,
        )
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

        kwargs: dict = {
            "model": model_id,
            "messages": full_messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        response = self.client.chat.completions.create(**kwargs)

        choice = response.choices[0]
        message = choice.message

        tool_calls_list = []
        if message.tool_calls:
            for tc in message.tool_calls:
                tool_calls_list.append({
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                })

        usage_dict = {}
        if response.usage:
            usage_dict = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        generation_cost = None
        if hasattr(response, "x_openrouter") and response.x_openrouter:
            generation_cost = getattr(response.x_openrouter, "generation_cost", None)

        result = {
            "content": message.content or "",
            "tool_calls": tool_calls_list,
            "usage": usage_dict,
            "model": model_id,
            "finish_reason": choice.finish_reason,
        }

        if self.cache is not None:
            self.cache.put(cache_key, result)

        self.cost_tracker.record(model_id, usage_dict, generation_cost)

        return result

    def verify_model(self, model_id: str) -> bool:
        """Verify a model ID is available on OpenRouter."""
        try:
            models_response = self.client.models.list()
            available_ids = {m.id for m in models_response.data}
            return model_id in available_ids
        except Exception:
            return False

    @property
    def cache_hits(self) -> int:
        return self._cache_hits

    @property
    def cache_misses(self) -> int:
        return self._cache_misses
