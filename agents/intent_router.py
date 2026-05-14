"""
agents/intent_router.py
Classifies every incoming message and routes it to the right agent.
"""

import json
import logging
from enum import Enum

from agents.base import BaseAgent

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
You are the Intent Router for a classroom management Telegram bot.
Your ONLY job is to classify the user's message into exactly one intent
and return a JSON object — nothing else, no preamble, no explanation.

Possible intents:
- "assign_work"       : Teacher is giving a student an assignment
- "request_summary"   : Teacher wants a progress summary for a student
- "give_feedback"     : Teacher is providing feedback on a submission
- "progress_update"   : Student is reporting progress on an assignment
- "submit_work"       : Student is submitting completed work
- "greeting"          : A hello / how are you type message
- "unknown"           : Anything else

Return ONLY this JSON (no markdown, no backticks):
{"intent": "<one of the intents above>", "confidence": <0.0-1.0>}
"""


class Intent(str, Enum):
    ASSIGN_WORK     = "assign_work"
    REQUEST_SUMMARY = "request_summary"
    GIVE_FEEDBACK   = "give_feedback"
    PROGRESS_UPDATE = "progress_update"
    SUBMIT_WORK     = "submit_work"
    GREETING        = "greeting"
    UNKNOWN         = "unknown"


class IntentRouter(BaseAgent):
    name = "intent_router"

    def run(self, message: str, user_id: int | None = None) -> Intent:
        """
        Classify `message` and return an Intent enum value.
        Falls back to Intent.UNKNOWN on any error.
        """
        try:
            raw = self.llm(system=SYSTEM_PROMPT, user=message, max_tokens=64)
            clean = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            data = json.loads(clean)
            intent_str = data.get("intent", "unknown")
            intent = Intent(intent_str)
            logger.info(f"IntentRouter → {intent} (confidence={data.get('confidence')})")
            self.log(input_text=message, output_text=raw, user_id=user_id)
            return intent

        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"IntentRouter parse error: {e} | raw={raw!r}")
            return Intent.UNKNOWN

        except Exception as e:
            logger.error(f"IntentRouter unexpected error: {e}")
            return Intent.UNKNOWN


# Singleton
intent_router = IntentRouter()
