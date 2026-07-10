"""Test isolation: never touch the real Gemini API from unit tests.

A local .env may set GEMINI_API_KEY, which would make the suite do live network
calls (slow, flaky, and it would invalidate the deterministic fallback asserts).
This autouse fixture forces GenAI off so build_report is fully deterministic.
Tests that exercise the Gemini path monkeypatch generate_reasoning directly.
"""
import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def _disable_genai(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "")
