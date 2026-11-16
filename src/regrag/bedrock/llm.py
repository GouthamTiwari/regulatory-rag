"""One wrapper for every chat model on Bedrock, via the Converse API (SPEC section 5).

Converse uses the same request and response shape for Nova, Claude and other models, so
the router, the generator and the judge never need model-specific code: switching models
is a change to the model ID in .env.
"""

import time
from collections.abc import Callable

from regrag.bedrock.retry import with_retries
from regrag.types import Usage


class LLMError(RuntimeError):
    """The model returned nothing usable."""


class BedrockLLM:
    def __init__(
        self,
        client,
        model_id: str,
        *,
        temperature: float = 0.0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        # Temperature 0: the most likely answer every time, so evaluation runs repeat.
        self.client = client
        self.model_id = model_id
        self.temperature = temperature
        self.sleep = sleep

    def complete(self, system: str, user: str, max_tokens: int = 1500) -> tuple[str, Usage]:
        def call():
            return self.client.converse(
                modelId=self.model_id,
                system=[{"text": system}] if system else [],
                messages=[{"role": "user", "content": [{"text": user}]}],
                inferenceConfig={"maxTokens": max_tokens, "temperature": self.temperature},
            )

        response = with_retries(call, sleep=self.sleep)
        blocks = response.get("output", {}).get("message", {}).get("content", [])
        # Only text blocks: reasoning/thinking blocks (Claude, Nova with reasoning on) are
        # the model's scratch work, not the answer.
        text = "".join(block["text"] for block in blocks if "text" in block).strip()
        raw_usage = response.get("usage", {})
        usage = Usage(
            input_tokens=int(raw_usage.get("inputTokens", 0)),
            output_tokens=int(raw_usage.get("outputTokens", 0)),
        )
        if not text and response.get("stopReason") == "max_tokens":
            raise LLMError(
                f"{self.model_id} used all {max_tokens} output tokens without an answer; "
                "raise llm_max_tokens"
            )
        if not text:
            raise LLMError(
                f"{self.model_id} returned no text (stopReason={response.get('stopReason')})"
            )
        return text, usage
