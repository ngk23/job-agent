"""
OpenRouter LLM client for free-tier vision + text inference.
"""

import os
from typing import List

from openai import AsyncOpenAI

# Free models on OpenRouter (use :free suffix)
VISION_MODEL = "meta-llama/llama-4-maverick:free"  # Supports vision + 1M context
TEXT_MODEL = "deepseek/deepseek-chat-v3-0324:free"  # Fast text reasoning
FALLBACK_MODELS = [
    "qwen/qwen3-235b-a22b:free",
    "mistralai/mistral-small-3.1-24b-instruct:free",
    "google/gemma-3-27b-it:free",
]
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class LLMClient:
    """Handles all LLM interactions via OpenRouter with fallback support."""

    def __init__(self, api_key: str):
        self.client = AsyncOpenAI(
            base_url=OPENROUTER_BASE_URL,
            api_key=api_key,
            default_headers={
                "HTTP-Referer": "https://github.com/job-agent",
                "X-Title": "Job Application Agent",
            },
        )
        self.models = [VISION_MODEL, TEXT_MODEL] + FALLBACK_MODELS

    async def chat_with_vision(self, image_base64: str, prompt: str, max_tokens: int = 4000) -> str:
        """Send screenshot + prompt to vision model."""
        for model in self.models:
            try:
                response = await self.client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/png;base64,{image_base64}"},
                                },
                            ],
                        }
                    ],
                    max_tokens=max_tokens,
                    temperature=0.1,
                )
                return response.choices[0].message.content
            except Exception as e:
                print(f"  [WARN] Model {model} failed: {e}")
                continue
        raise Exception("All OpenRouter models failed")

    async def chat_text(self, prompt: str, max_tokens: int = 2000) -> str:
        """Send text-only prompt."""
        for model in self.models:
            try:
                response = await self.client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens,
                    temperature=0.1,
                )
                return response.choices[0].message.content
            except Exception as e:
                print(f"  [WARN] Model {model} failed: {e}")
                continue
        raise Exception("All OpenRouter models failed")
