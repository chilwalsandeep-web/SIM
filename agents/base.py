"""
agents/base.py
Provider-swappable LLM wrapper + abstract base class for all agents.
Swap LLM_PROVIDER in .env to switch between Anthropic and OpenAI live.
"""

import logging
from abc import ABC, abstractmethod
from typing import Optional

import anthropic
import openai

from config import settings
from db.models import AgentLog
from db.session import db_session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM Client — swappable by provider
# ---------------------------------------------------------------------------

class LLMClient:
    """
    Thin wrapper around Claude / OpenAI.
    Call llm.complete(system, user) regardless of which provider is active.
    """

    def __init__(self):
        self.provider = settings.LLM_PROVIDER

        if self.provider == "anthropic":
            self._client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
            self._model = settings.LLM_MODEL_ANTHROPIC
        elif self.provider == "openai":
            self._client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
            self._model = settings.LLM_MODEL_OPENAI
        else:
            raise ValueError(f"Unknown LLM_PROVIDER: {self.provider}. Use 'anthropic' or 'openai'.")

        logger.info(f"LLMClient initialised — provider={self.provider} model={self._model}")

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> str:
        """
        Send a prompt and return the assistant's reply as a plain string.
        Raises on API errors — callers should handle gracefully.
        """
        try:
            if self.provider == "anthropic":
                response = self._client.messages.create(
                    model=self._model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                return response.content[0].text.strip()

            elif self.provider == "openai":
                response = self._client.chat.completions.create(
                    model=self._model,
                    max_tokens=max_tokens,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user",   "content": user},
                    ],
                )
                return response.choices[0].message.content.strip()

        except Exception as e:
            logger.error(f"LLMClient.complete() error [{self.provider}]: {e}")
            raise


# Singleton — import and use `llm_client` anywhere
llm_client = LLMClient()


# ---------------------------------------------------------------------------
# Abstract Base Agent
# ---------------------------------------------------------------------------

class BaseAgent(ABC):
    """
    All agents extend this. Provides:
    - llm()  shortcut for completions
    - log()  writes to agent_logs table
    """

    name: str = "base_agent"

    def llm(self, system: str, user: str, max_tokens: int = 1024) -> str:
        return llm_client.complete(system=system, user=user, max_tokens=max_tokens)

    def log(
        self,
        input_text: str,
        output_text: str,
        user_id: Optional[int] = None,
        assignment_id: Optional[int] = None,
    ) -> None:
        """Persist an audit entry to agent_logs."""
        try:
            with db_session() as db:
                entry = AgentLog(
                    agent_name=self.name,
                    input_text=input_text,
                    output_text=output_text,
                    user_id=user_id,
                    assignment_id=assignment_id,
                )
                db.add(entry)
        except Exception as e:
            # Logging failure must never crash the agent
            logger.warning(f"AgentLog write failed: {e}")

    @abstractmethod
    def run(self, *args, **kwargs):
        """Entry point for each agent."""
        ...
