"""Shared helpers used across graph nodes."""


def extract_text(content) -> str:
    """Extract plain text from LLM response content.

    Gemini returns content as a list of dicts:
        [{"type": "text", "text": "...", "extras": {"signature": "..."}}]
    Groq/OpenAI returns a plain string.

    This normalises both to a clean string.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(p for p in parts if p)
    return str(content)
