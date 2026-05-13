"""
services/transcription.py
Voice note → text transcription using OpenAI Whisper API.
Falls back gracefully if not configured.
"""

import logging
import tempfile
from pathlib import Path
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)


async def transcribe_voice(file_url: str) -> Optional[str]:
    """
    Download a voice file from Telegram and transcribe it with Whisper.
    Returns transcribed text or None on failure.
    """
    if not settings.OPENAI_API_KEY:
        logger.warning("transcribe_voice: OPENAI_API_KEY not set, skipping transcription")
        return None

    try:
        # Download the file
        async with httpx.AsyncClient() as client:
            resp = await client.get(file_url, timeout=30)
            resp.raise_for_status()
            audio_bytes = resp.content

        # Write to a temp file and send to Whisper
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = Path(tmp.name)

        import openai
        oai = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
        with open(tmp_path, "rb") as f:
            transcript = oai.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                response_format="text",
            )

        tmp_path.unlink(missing_ok=True)
        logger.info("Voice note transcribed successfully.")
        return transcript

    except Exception as e:
        logger.error(f"transcribe_voice error: {e}")
        return None


async def get_telegram_file_url(bot_token: str, file_id: str) -> Optional[str]:
    """Resolve a Telegram file_id to a download URL."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://api.telegram.org/bot{bot_token}/getFile",
                params={"file_id": file_id},
                timeout=10,
            )
            data = resp.json()
            file_path = data["result"]["file_path"]
            return f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
    except Exception as e:
        logger.error(f"get_telegram_file_url error: {e}")
        return None
