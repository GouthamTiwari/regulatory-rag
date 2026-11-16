"""Generate a cited draft answer (SPEC section 5, "Generate")."""

from regrag.query.prompts import INSUFFICIENT, SYSTEM_PROMPT, build_user_prompt
from regrag.query.validate import markers_in
from regrag.types import DraftAnswer, RetrievedChunk


class CitedGenerator:
    """Implements the Generator protocol on top of any object with
    `complete(system, user, max_tokens) -> (text, Usage)` (e.g. BedrockLLM)."""

    def __init__(self, llm, *, max_tokens: int = 1500, extra_instruction: str = ""):
        self.llm = llm
        self.max_tokens = max_tokens
        # Used for the one retry after a failed validation: tells the model what to fix.
        self.extra_instruction = extra_instruction

    def generate(self, question: str, chunks: list[RetrievedChunk]) -> DraftAnswer:
        if not chunks:
            return DraftAnswer(text=INSUFFICIENT, insufficient=True)
        system = SYSTEM_PROMPT + (f"\n\n{self.extra_instruction}" if self.extra_instruction else "")
        text, usage = self.llm.complete(
            system, build_user_prompt(question, chunks), self.max_tokens
        )
        if text.strip().upper().startswith(INSUFFICIENT):
            return DraftAnswer(text=INSUFFICIENT, insufficient=True, usage=usage)
        return DraftAnswer(text=text.strip(), markers=markers_in(text), usage=usage)
