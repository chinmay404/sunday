"""
LLM factory — reads MODEL_PROVIDER env var to decide backend.

Features:
  - Automatic fallback: if primary provider fails, tries the other
  - Retry with exponential backoff for transient errors (429, 503, etc.)
  - Token-aware truncation helpers for cheap LLM calls
  - Smart get_cheap_llm: tries Groq first (free), falls back to Google

Env vars:
  MODEL_PROVIDER   = "google" | "groq"  (default: "groq")

  # Groq
  GROQ_API_KEY     = ...
  GROQ_MODEL       = "llama-3.3-70b-versatile"

  # Google Gemini
  GOOGLE_API_KEY   = ...
  GOOGLE_MODEL     = "gemini-2.5-flash"

  # Optional: separate thinking model
  THINKING_MODEL   = "..."  (falls back to GROQ_MODEL / GOOGLE_MODEL)

  # Cheap model override (defaults to GOOGLE_MODEL with low temp)
  CHEAP_MODEL      = "..."
"""

import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, cast

from dotenv import load_dotenv

# Ensure repo root is on sys.path for sibling imports
_root = Path(__file__).resolve().parent.parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

load_dotenv()
logger = logging.getLogger(__name__)

# -- Lazy imports (avoid hard crash if a package isn't installed) ------------

try:
    from langchain_groq import ChatGroq
except Exception:
    ChatGroq = None

try:
    from langchain_google_genai import ChatGoogleGenerativeAI
except Exception:
    ChatGoogleGenerativeAI = None


# -- Constants --------------------------------------------------------------

# Rate-limit / transient error codes that warrant a retry
_RETRYABLE_SUBSTRINGS = (
    "rate_limit",
    "429",
    "503",
    "overloaded",
    "capacity",
    "too many requests",
    "resource_exhausted",
    "quota",
    "tokens per minute",
    "request too large",
    "high demand",
    "temporarily unavailable",
)

# Max chars we'll send to the cheap LLM to avoid TPM blowouts
CHEAP_LLM_MAX_INPUT_CHARS = int(os.getenv("CHEAP_LLM_MAX_INPUT_CHARS", "6000"))


# -- Helpers ----------------------------------------------------------------

def _provider() -> str:
    """Return normalised provider name from MODEL_PROVIDER env var."""
    return os.getenv("MODEL_PROVIDER", "groq").strip().lower()


def _is_retryable(exc: Exception) -> bool:
    """Check if an exception looks like a transient/rate-limit error."""
    msg = str(exc).lower()
    return any(s in msg for s in _RETRYABLE_SUBSTRINGS)


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


def _build_for_provider(provider: str, model: str, temperature: float):
    """Build an LLM for the given provider string."""
    if provider == "google":
        return _build_google(model, temperature)
    else:
        return _build_groq(model, temperature)


def _model_for_provider(provider: str) -> str:
    """Return the model name for a given provider."""
    if provider == "google":
        return os.getenv("GOOGLE_MODEL", "gemini-2.5-flash")
    else:
        return os.getenv("GROQ_MODEL", "")


def _alt_provider(provider: str) -> str:
    """Return the alternative provider."""
    return "groq" if provider == "google" else "google"


# -- Token-aware truncation -------------------------------------------------

def truncate_text(text: str, max_chars: int = CHEAP_LLM_MAX_INPUT_CHARS) -> str:
    """Truncate text to fit within cheap LLM token limits.

    Keeps the beginning (context) and end (most recent) of the text,
    inserting a [...truncated...] marker in the middle.
    """
    if not text or len(text) <= max_chars:
        return text
    # Keep 40% from start, 60% from end (recent context matters more)
    keep_start = int(max_chars * 0.4)
    keep_end = max_chars - keep_start - 30  # 30 chars for marker
    return (
        text[:keep_start]
        + "\n\n[... truncated middle section ...]\n\n"
        + text[-keep_end:]
    )


# -- Resilient invocation wrapper -------------------------------------------

class ResilientLLM:
    """Wraps a LangChain LLM with retry + automatic provider fallback.

    On transient errors (rate limit, 503, etc.):
      1. Retry the primary LLM up to max_retries times with backoff
      2. If still failing, try the fallback provider once

    This is transparent -- it quacks like a regular LLM.
    """

    def __init__(self, primary, fallback=None, max_retries: int = 2,
                 provider_name: str = "unknown"):
        self._primary = primary
        self._fallback = fallback
        self._max_retries = max_retries
        self._provider_name = provider_name

    # -- Forward attribute access to primary --------------------------------
    def __getattr__(self, name):
        return getattr(self._primary, name)

    # -- Core invoke with retry + fallback ----------------------------------
    def invoke(self, *args, **kwargs):
        last_exc = None
        for attempt in range(self._max_retries + 1):
            try:
                return self._primary.invoke(*args, **kwargs)
            except Exception as exc:
                last_exc = exc
                if not _is_retryable(exc):
                    logger.warning("[LLM] Non-retryable error on %s: %s",
                                   self._provider_name, str(exc)[:200])
                    break
                wait = min(2 ** attempt, 8)
                logger.warning("[LLM] Retryable error on %s (attempt %d/%d), "
                               "waiting %.1fs: %s",
                               self._provider_name, attempt + 1,
                               self._max_retries + 1, wait, str(exc)[:150])
                time.sleep(wait)

        # Primary exhausted -- try fallback
        if self._fallback is not None:
            logger.info("[LLM] Falling back from %s to alternate provider",
                        self._provider_name)
            try:
                return self._fallback.invoke(*args, **kwargs)
            except Exception as fb_exc:
                logger.error("[LLM] Fallback also failed: %s", str(fb_exc)[:200])
                raise fb_exc from last_exc

        # No fallback available
        if last_exc:
            raise last_exc

    # -- bind_tools returns a new ResilientLLM wrapping the bound version ---
    def bind_tools(self, tools, **kwargs):
        bound_primary = self._primary.bind_tools(tools, **kwargs)
        bound_fallback = None
        if self._fallback is not None and hasattr(self._fallback, "bind_tools"):
            try:
                bound_fallback = self._fallback.bind_tools(tools, **kwargs)
            except Exception:
                pass  # fallback might not support all tool formats
        return ResilientLLM(bound_primary, bound_fallback,
                            max_retries=self._max_retries,
                            provider_name=self._provider_name)

    def with_structured_output(self, *args, **kwargs):
        structured_primary = self._primary.with_structured_output(*args, **kwargs)
        structured_fallback = None
        if self._fallback is not None and hasattr(self._fallback, "with_structured_output"):
            try:
                structured_fallback = self._fallback.with_structured_output(*args, **kwargs)
            except Exception:
                pass
        return ResilientLLM(structured_primary, structured_fallback,
                            max_retries=self._max_retries,
                            provider_name=self._provider_name)


# -- Public API -------------------------------------------------------------

def get_llm(temperature: float = 0.8, provider: str | None = None):
    """Return a configured chat LLM with automatic fallback.

    Provider is resolved as: explicit arg -> MODEL_PROVIDER env -> "groq".
    Model name comes from GROQ_MODEL or GOOGLE_MODEL depending on provider.
    If the primary provider fails with a transient error, falls back to the other.
    """
    prov = (provider or _provider()).lower()
    alt = _alt_provider(prov)
    try:
        model = _model_for_provider(prov)
        primary = _build_for_provider(prov, model, temperature)

        # Build fallback (different provider)
        alt_model = _model_for_provider(alt)
        fallback = None
        try:
            fallback = _build_for_provider(alt, alt_model, temperature)
        except Exception:
            pass  # fallback is optional

        if primary:
            logger.debug("LLM ready: provider=%s model=%s (fallback=%s)", prov, model, alt)
            return ResilientLLM(primary, fallback, max_retries=2, provider_name=prov)
        elif fallback:
            logger.warning("Primary LLM (%s) unavailable, using fallback (%s)", prov, alt)
            return ResilientLLM(fallback, None, max_retries=2, provider_name=alt)
        return None
    except Exception as e:
        logger.exception("Error initialising LLM (provider=%s): %s", prov, e)
        return None


def get_cheap_llm(temperature: float = 0.2, model: str | None = None):
    """Smart cheap LLM for internal tasks (memory, actions, summaries).

    Strategy:
      1. Try Groq first (it's free / cheap)
      2. If Groq isn't available or fails, fall back to Google with low temp
    This prevents the TPM blowouts we were seeing with Groq's tight limits.
    """
    # Try Groq as primary (cheap)
    groq_model = model or os.getenv("GROQ_MODEL", "")
    primary = None
    try:
        primary = _build_groq(groq_model, temperature)
    except Exception:
        pass

    # Google as fallback
    google_model = os.getenv("CHEAP_MODEL") or os.getenv("GOOGLE_MODEL", "gemini-2.5-flash")
    fallback = None
    try:
        fallback = _build_google(google_model, temperature)
    except Exception:
        pass

    if primary:
        return ResilientLLM(primary, fallback, max_retries=1, provider_name="groq-cheap")
    elif fallback:
        return ResilientLLM(fallback, None, max_retries=2, provider_name="google-cheap")

    logger.error("No LLM available for cheap tasks (neither Groq nor Google)")
    return None


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
        primary = _build_for_provider(prov, thinking_model, temperature)
        alt = _alt_provider(prov)
        fallback = None
        try:
            fallback = _build_for_provider(alt, _model_for_provider(alt), temperature)
        except Exception:
            pass
        if primary:
            return ResilientLLM(primary, fallback, max_retries=2,
                                provider_name=f"{prov}-thinking")
        return None
    except Exception as e:
        logger.exception("Error initialising thinking LLM: %s", e)
        return None
