"""
LLM factory — reads MODEL_PROVIDER env var to decide backend.

Env vars:
  MODEL_PROVIDER   = "google" | "groq"  (default: "groq")

  # Groq
  GROQ_API_KEY     = ...
  GROQ_MODEL       = "llama-3.3-70b-versatile"

  # Google Gemini
  GOOGLE_API_KEY   = ...
  GOOGLE_MODEL     = "gemini-2.5-flash-preview-05-20"

  # Optional: separate thinking model
  THINKING_MODEL   = "..."  (falls back to GROQ_MODEL / GOOGLE_MODEL)
"""

import logging
import os
import sys
from pathlib import Path
from typing import Any, cast

from dotenv import load_dotenv

# Ensure repo root is on sys.path for sibling imports
_root = Path(__file__).resolve().parent.parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

load_dotenv()
logger = logging.getLogger(__name__)

# ── Lazy imports (avoid hard crash if a package isn't installed) ────────────

try:
    from langchain_groq import ChatGroq
except Exception:
    ChatGroq = None

try:
    from langchain_google_genai import ChatGoogleGenerativeAI
except Exception:
    ChatGoogleGenerativeAI = None


# ── Helpers ────────────────────────────────────────────────────────────────

def _provider() -> str:
    """Return normalised provider name from MODEL_PROVIDER env var."""
    return os.getenv("MODEL_PROVIDER", "groq").strip().lower()


def _build_groq(model: str, temperature: float):
    """Instantiate a ChatGroq LLM."""
    if ChatGroq is None:
        logger.error("langchain-groq is not installed")
        return None
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key or not model:
        logger.error("GROQ_API_KEY and/or GROQ_MODEL not set")
        return None
    try:
        from pydantic import SecretStr
        api_key_param = SecretStr(api_key)
    except Exception:
        api_key_param = cast(Any, api_key)
    return ChatGroq(api_key=api_key_param, model=model, temperature=temperature)


def _build_google(model: str, temperature: float):
    """Instantiate a ChatGoogleGenerativeAI LLM."""
    if ChatGoogleGenerativeAI is None:
        logger.error("langchain-google-genai is not installed")
        return None
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key or not model:
        logger.error("GOOGLE_API_KEY (or GEMINI_API_KEY) and/or GOOGLE_MODEL not set")
        return None
    return ChatGoogleGenerativeAI(
        model=model,
        google_api_key=api_key,
        temperature=temperature,
        max_retries=2,
    )


# ── Public API ─────────────────────────────────────────────────────────────

def get_llm(temperature: float = 0.8, provider: str | None = None):
    """Return a configured chat LLM.

    Provider is resolved as: explicit arg → MODEL_PROVIDER env → "groq".
    Model name comes from GROQ_MODEL or GOOGLE_MODEL depending on provider.
    """
    prov = (provider or _provider()).lower()
    try:
        if prov == "google":
            model = os.getenv("GOOGLE_MODEL", "gemini-2.5-flash")
            llm = _build_google(model, temperature)
        else:
            model = os.getenv("GROQ_MODEL", "")
            llm = _build_groq(model, temperature)

        if llm:
            logger.debug("LLM ready: provider=%s model=%s", prov, model)
        return llm
    except Exception as e:
        logger.exception("Error initialising LLM (provider=%s): %s", prov, e)
        return None


def get_cheap_llm(temperature: float = 0.2, model: str | None = None):
    """Always-Groq LLM for cheap internal tasks (memory, actions, summaries).

    Uses Groq regardless of MODEL_PROVIDER so we don't burn expensive
    Gemini tokens on background processing.
    """
    m = model or os.getenv("GROQ_MODEL", "")
    return _build_groq(m, temperature)


def get_llm_with_tools(temperature: float = 0.8, provider: str | None = None):
    """Return an LLM bound with all registered tools."""
    from llm.graph.tools.manager import get_all_tools

    llm = get_llm(temperature=temperature, provider=provider)
    if llm is None:
        logger.error("LLM could not be created; cannot bind tools")
        return None
    try:
        tools = get_all_tools()
        if hasattr(llm, "bind_tools"):
            return llm.bind_tools(tools, tool_choice="auto")
        setattr(llm, "tools", tools)
        return llm
    except Exception as e:
        logger.exception("Failed to bind tools: %s", e)
        return None


def get_thinking_llm(temperature: float = 0.8, provider: str | None = None):
    """Return a thinking/reasoning LLM (separate model name via THINKING_MODEL env)."""
    prov = (provider or _provider()).lower()
    thinking_model = os.getenv("THINKING_MODEL", "")

    # If no dedicated thinking model, just use the default get_llm
    if not thinking_model:
        return get_llm(temperature=temperature, provider=prov)

    try:
        if prov == "google":
            return _build_google(thinking_model, temperature)
        else:
            return _build_groq(thinking_model, temperature)
    except Exception as e:
        logger.exception("Error initialising thinking LLM: %s", e)
        return None
