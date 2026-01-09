from llm.graph.tools.manager import get_all_tools
from dotenv import load_dotenv
import os
import logging
from typing import cast, Any
import sys
from pathlib import Path
from langchain_google_genai import ChatGoogleGenerativeAI
# Add parent directory to path first
_root = Path(__file__).resolve().parent.parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

# Try to import ChatGroq but make the module optional for local development/tests.
try:
    from langchain_groq import ChatGroq
except Exception:  # pragma: no cover - third-party import may not be available in all environments
    ChatGroq = None


load_dotenv()
logger = logging.getLogger(__name__)


def get_llm(local: bool = False, temperature: float = 0.8,  gemini: bool = False):
    """Return a configured LLM instance.

    If `local` is True the function should return a local model (not implemented here).
    Otherwise it attempts to instantiate ChatGroq using GROQ_API_KEY and model_name
    from environment variables.

    Returns the LLM instance on success or None on failure.
    """
    if gemini:
        try:
            api_key = os.getenv("GOOGLE_API_KEY")
            llm = ChatGoogleGenerativeAI(model=os.getenv(
                "GOOGLE_MODEL"), google_api_key=api_key)
            return llm
        except Exception as e:
            print(f"Erorr IN Google Gemini LLm : {e}")
            return None
    else:
        if local:
            logger.info(
                "Local LLM requested but not implemented; returning None")
            return None

        if ChatGroq is None:
            logger.error("ChatGroq SDK is not installed or failed to import")
            return None

        try:
            api_key = os.environ.get("GROQ_API_KEY")
            model_name = os.environ.get("GROQ_MODEL")
            if not api_key or not model_name:
                logger.error(
                    "GROQ_API_KEY and/or model_name not set in environment")
                return None

            # Some type-checkers expect SecretStr for api_key. Try to wrap if pydantic is present.
            try:
                from pydantic import SecretStr  # type: ignore

                api_key_param = SecretStr(api_key)
            except Exception:
                # pydantic not available at type-check/runtime; cast to satisfy the ChatGroq signature
                api_key_param = cast(Any, api_key)

            llm = ChatGroq(api_key=api_key_param, model=model_name,
                           temperature=temperature)
            return llm
        except Exception as e:
            logger.exception("Error initializing ChatGroq LLM: %s", e)
            return None


def get_llm_with_tools(local: bool = False, temperature: float = 0.8, gemini: bool = False):
    """Return an LLM bound with tools. If tools or LLM can't be created, return None."""
    llm = get_llm(local=local, temperature=temperature, gemini=gemini)
    if llm is None:
        logger.error("LLM instance could not be created; cannot bind tools")
        return None

    try:
        tools = get_all_tools()

        if hasattr(llm, "bind_tools"):
            return llm.bind_tools(tools, tool_choice="auto")

        setattr(llm, "tools", tools)
        return llm
    except Exception as e:
        logger.exception("Failed to bind tools to LLM: %s", e)
        return None


def get_thinking_llm(local: bool = False, temperature: float = 0.8, gemini: bool = False):
    """Return a configured LLM instance.

        If `local` is True the function should return a local model (not implemented here).
        Otherwise it attempts to instantiate ChatGroq using GROQ_API_KEY and model_name
        from environment variables.

        Returns the LLM instance on success or None on failure.
        """
    if gemini:
        return get_llm(local=local, temperature=temperature, gemini=True)

    if local:
        # Placeholder for a local model (e.g., Ollama). Not implemented here.
        logger.info("Local LLM requested but not implemented; returning None")
        return None

    if ChatGroq is None:
        logger.error("ChatGroq SDK is not installed or failed to import")
        return None

    try:
        api_key = os.environ.get("GROQ_API_KEY")
        thinking_model_name = os.environ.get("model_name")
        if not api_key or not thinking_model_name:
            logger.error(
                "GROQ_API_KEY and/or model_name not set in environment")
            return None
        try:
            from pydantic import SecretStr

            api_key_param = SecretStr(api_key)
        except Exception:

            api_key_param = cast(Any, api_key)

        llm = ChatGroq(api_key=api_key_param, model=thinking_model_name,
                       temperature=temperature)
        return llm
    except Exception as e:
        logger.exception(
            "Error initializing ChatGroq thinking_model_name: %s", e)
        return None
