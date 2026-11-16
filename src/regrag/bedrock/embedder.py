"""Amazon Titan Text Embeddings V2 (SPEC section 5, "Embed")."""

import json
import time
import warnings
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from regrag.bedrock.retry import with_retries
from regrag.config import Settings
from regrag.types import EmbedResult

# Titan V2 accepts up to 8K tokens; stay safely below with our characters/4 estimate.
MAX_INPUT_CHARS = 7_500 * 4


class TitanEmbedder:
    """Implements the Embedder protocol.

    Titan takes one text per call, so texts are sent in parallel (a few at a time, to stay
    under the account's request quota) and the results are put back in input order.
    """

    def __init__(
        self,
        client,
        *,
        model_id: str = "amazon.titan-embed-text-v2:0",
        dimensions: int = 1024,
        concurrency: int = 4,
        sleep: Callable[[float], None] = time.sleep,
    ):
        # The client is passed in (never created here) so tests can hand in a fake.
        self.client = client
        self.model_id = model_id
        self.dimensions = dimensions
        self.concurrency = concurrency
        self.sleep = sleep

    @classmethod
    def from_settings(cls, client, settings: Settings) -> "TitanEmbedder":
        return cls(
            client,
            model_id=settings.bedrock_embed_model_id,
            dimensions=settings.embed_dimensions,
            concurrency=settings.embed_concurrency,
        )

    def _embed_one(self, text: str) -> tuple[list[float], int]:
        if len(text) > MAX_INPUT_CHARS:
            warnings.warn(f"text of {len(text)} characters truncated for embedding", stacklevel=2)
            text = text[:MAX_INPUT_CHARS]
        body = json.dumps({"inputText": text, "dimensions": self.dimensions, "normalize": True})

        def call():
            return self.client.invoke_model(
                modelId=self.model_id,
                body=body,
                contentType="application/json",
                accept="application/json",
            )

        response = with_retries(call, sleep=self.sleep)
        payload = json.loads(response["body"].read())
        return payload["embedding"], int(payload.get("inputTextTokenCount", 0))

    def embed(self, texts: list[str]) -> EmbedResult:
        if not texts:
            return EmbedResult(vectors=[], input_tokens=0)
        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            results = list(pool.map(self._embed_one, texts))  # map keeps input order
        return EmbedResult(
            vectors=[vector for vector, _ in results],
            input_tokens=sum(tokens for _, tokens in results),
        )
