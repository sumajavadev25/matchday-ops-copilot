"""Runtime configuration, read once from the environment.

Kept tiny and dependency-free so tests can import it without side effects.
"""
import os

from dotenv import load_dotenv

# Load .env for local dev. In production (Cloud Run) real env vars take precedence.
load_dotenv()


class Settings:
    def __init__(self) -> None:
        self.gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
        # `-latest` alias resolves to the current flash so a retired pin can't
        # break us at evaluation time (a real failure mode we hit in testing).
        self.gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
        # Secondary model tried when the primary is overloaded (503) or
        # rate-limited (429). flash-lite has higher free-tier limits and is
        # cheaper, keeping GenAI functional under load instead of degrading.
        self.gemini_fallback_model: str = os.getenv(
            "GEMINI_FALLBACK_MODEL", "gemini-flash-lite-latest")
        # Fraction of capacity at which a zone is flagged. Clamped to a sane range.
        raw = os.getenv("CROWD_ALERT_THRESHOLD", "0.80")
        try:
            self.crowd_alert_threshold: float = min(max(float(raw), 0.1), 1.0)
        except ValueError:
            self.crowd_alert_threshold = 0.80

    @property
    def genai_enabled(self) -> bool:
        return bool(self.gemini_api_key)


settings = Settings()
