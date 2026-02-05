import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from langchain_core.tools import tool

# Add repo root to path to allow importing from integrations
current_dir = Path(__file__).resolve().parent
repo_root = current_dir.parents[2]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from integrations.notion.notion_client import NotionClient

# Load env variables
load_dotenv(repo_root / ".env")


def _parse_json(value: Any, label: str) -> Optional[Any]:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        try:
            return json.loads(value)
        except Exception as exc:
            raise ValueError(f"{label} must be valid JSON: {exc}")
    raise ValueError(f"{label} must be a JSON string or object")


def _chunk_list(items: List[Any], size: int) -> List[List[Any]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _rich_text(text: str) -> List[Dict[str, Any]]:
    return [{"type": "text", "text": {"content": text}}]


def _build_title_property(title: str) -> Dict[str, Any]:
    return {"title": _rich_text(title)}


def _extract_title_from_page(page: Dict[str, Any]) -> str:
    properties = page.get("properties", {})
    for prop in properties.values():
        if prop.get("type") == "title":
            title_parts = prop.get("title", [])
            if title_parts:
                return "".join(part.get("plain_text", "") for part in title_parts).strip() or "Untitled"
    return "Untitled"


def _extract_title_from_database(database: Dict[str, Any]) -> str:
    title_parts = database.get("title", [])
    if not title_parts:
        return "Untitled"
    return "".join(part.get("plain_text", "") for part in title_parts).strip() or "Untitled"


def _get_database_title_property(database: Dict[str, Any]) -> Optional[str]:
    properties = database.get("properties", {})
    for name, prop in properties.items():
        if prop.get("type") == "title":
            return name
    return None


def _apply_simple_properties(
    database: Dict[str, Any],
    properties: Dict[str, Any],
    tags: Optional[str],
    tags_property: str,
) -> None:
    if not tags:
        return
    props = database.get("properties", {})
    prop = props.get(tags_property)
    if not prop or prop.get("type") != "multi_select":
        return
    tags_list = [t.strip() for t in tags.split(",") if t.strip()]
    if not tags_list:
        return
    properties[tags_property] = {
        "multi_select": [{"name": tag} for tag in tags_list]
    }


def _markdown_to_blocks(markdown: str) -> List[Dict[str, Any]]:
    lines = markdown.splitlines()
    blocks: List[Dict[str, Any]] = []
    i = 0

    while i < len(lines):
        line = lines[i].rstrip()
        if not line:
            i += 1
            continue

        if line.startswith("```"):
            language = line[3:].strip() or "plain text"
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                code_lines.append(lines[i])
                i += 1
            code_text = "\n".join(code_lines)
            blocks.append(
                {
                    "object": "block",
                    "type": "code",
                    "code": {
                        "rich_text": _rich_text(code_text),
                        "language": language,
                    },
                }
            )
            while i < len(lines) and lines[i].startswith("```"):
                i += 1
            continue

        if line.startswith("### "):
            blocks.append(
                {
                    "object": "block",
                    "type": "heading_3",
                    "heading_3": {"rich_text": _rich_text(line[4:].strip())},
                }
            )
            i += 1
            continue

        if line.startswith("## "):
            blocks.append(
                {
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {"rich_text": _rich_text(line[3:].strip())},
                }
            )
            i += 1
            continue

        if line.startswith("# "):
            blocks.append(
                {
                    "object": "block",
                    "type": "heading_1",
                    "heading_1": {"rich_text": _rich_text(line[2:].strip())},
                }
            )
            i += 1
            continue

        todo_match = re.match(r"^- \[( |x|X)\] (.*)$", line)
        if todo_match:
            checked = todo_match.group(1).lower() == "x"
            text = todo_match.group(2).strip()
            blocks.append(
                {
                    "object": "block",
                    "type": "to_do",
                    "to_do": {"rich_text": _rich_text(text), "checked": checked},
                }
            )
            i += 1
            continue

        bullet_match = re.match(r"^[-*] (.*)$", line)
        if bullet_match:
            text = bullet_match.group(1).strip()
            blocks.append(
                {
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {"rich_text": _rich_text(text)},
                }
            )
            i += 1
            continue

        numbered_match = re.match(r"^\d+\. (.*)$", line)
        if numbered_match:
            text = numbered_match.group(1).strip()
            blocks.append(
                {
                    "object": "block",
                    "type": "numbered_list_item",
                    "numbered_list_item": {"rich_text": _rich_text(text)},
                }
            )
            i += 1
            continue

        blocks.append(
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": _rich_text(line)},
            }
        )
        i += 1

    return blocks


def _summarize_blocks(blocks: List[Dict[str, Any]], limit: int = 20) -> str:
    summary_lines = []
    for block in blocks[:limit]:
        block_type = block.get("type", "unknown")
        content = ""
        data = block.get(block_type, {})
        rich = data.get("rich_text") or []
        if rich:
            content = "".join(part.get("plain_text", "") for part in rich).strip()
        summary_lines.append(f"- {block_type}: {content}")
    if len(blocks) > limit:
        summary_lines.append(f"...and {len(blocks) - limit} more blocks")
    return "\n".join(summary_lines) if summary_lines else "(no blocks)"


@tool
def notion_create_note(
    title: str,
    content: Optional[str] = None,
    database_id: Optional[str] = None,
    page_id: Optional[str] = None,
    properties_json: Optional[str] = None,
    blocks_json: Optional[str] = None,
    tags: Optional[str] = None,
    tags_property: str = "Tags",
    title_property: Optional[str] = None,
) -> str:
    """Create a Notion page (note) with optional markdown or raw blocks."""
    try:
        client = NotionClient()

        target_database = database_id or os.getenv("NOTION_DATABASE_ID")
        if target_database:
            parent = {"database_id": target_database}
            database = client.retrieve_database(target_database)
            title_prop = title_property or _get_database_title_property(database)
            if not title_prop:
                return "Error: Could not find the title property for the database. Provide title_property."
            properties: Dict[str, Any] = {title_prop: _build_title_property(title)}
            _apply_simple_properties(database, properties, tags, tags_property)
        elif page_id:
            parent = {"page_id": page_id}
            properties = {"title": _build_title_property(title)}
        else:
            return "Error: Provide database_id or page_id, or set NOTION_DATABASE_ID."

        extra_properties = _parse_json(properties_json, "properties_json")
        if extra_properties:
            properties.update(extra_properties)

        blocks = _parse_json(blocks_json, "blocks_json")
        if blocks is None and content:
            blocks = _markdown_to_blocks(content)

        children_chunks: List[List[Dict[str, Any]]] = []
        if blocks:
            if not isinstance(blocks, list):
                return "Error: blocks_json must be a JSON list of block objects."
            children_chunks = _chunk_list(blocks, 100)

        first_children = children_chunks[0] if children_chunks else None
        page = client.create_page(parent=parent, properties=properties, children=first_children)
        page_id = page.get("id")
        page_url = page.get("url", "")

        for chunk in children_chunks[1:]:
            client.append_blocks(page_id, chunk)

        return f"Created note '{title}' (ID: {page_id}) {page_url}".strip()
    except Exception as exc:
        return f"Failed to create note: {exc}"


@tool
def notion_append_content(
    page_id: str,
    content: Optional[str] = None,
    blocks_json: Optional[str] = None,
) -> str:
    """Append markdown or raw blocks to a Notion page."""
    try:
        client = NotionClient()
        blocks = _parse_json(blocks_json, "blocks_json")
        if blocks is None and content:
            blocks = _markdown_to_blocks(content)
        if not blocks:
            return "No content to append."
        if not isinstance(blocks, list):
            return "Error: blocks_json must be a JSON list of block objects."

        chunks = _chunk_list(blocks, 100)
        for chunk in chunks:
            client.append_blocks(page_id, chunk)
        return f"Appended {len(blocks)} block(s) to page {page_id}."
    except Exception as exc:
        return f"Failed to append content: {exc}"


@tool
def notion_update_page_properties(page_id: str, properties_json: str) -> str:
    """Update page properties from a JSON payload."""
    try:
        client = NotionClient()
        properties = _parse_json(properties_json, "properties_json")
        if not properties:
            return "No properties provided."
        if not isinstance(properties, dict):
            return "Error: properties_json must be a JSON object."
        page = client.update_page(page_id, properties)
        title = _extract_title_from_page(page)
        return f"Updated page '{title}' (ID: {page_id})."
    except Exception as exc:
        return f"Failed to update page: {exc}"


@tool
def notion_get_page(page_id: str) -> str:
    """Get basic info for a Notion page."""
    try:
        client = NotionClient()
        page = client.retrieve_page(page_id)
        title = _extract_title_from_page(page)
        url = page.get("url", "")
        created = page.get("created_time", "")
        return f"Page '{title}' (ID: {page_id}) {url} Created: {created}".strip()
    except Exception as exc:
        return f"Failed to retrieve page: {exc}"


@tool
def notion_get_page_content(page_id: str, limit: int = 20) -> str:
    """Summarize top-level blocks on a page (up to limit)."""
    try:
        client = NotionClient()
        response = client.list_block_children(page_id, page_size=min(limit, 100))
        blocks = response.get("results", [])
        return _summarize_blocks(blocks, limit=limit)
    except Exception as exc:
        return f"Failed to retrieve page content: {exc}"


@tool
def notion_query_database(
    database_id: str,
    filter_json: Optional[str] = None,
    sorts_json: Optional[str] = None,
    limit: int = 10,
) -> str:
    """Query a Notion database with optional JSON filter/sorts."""
    try:
        client = NotionClient()
        filter_payload = _parse_json(filter_json, "filter_json")
        sorts_payload = _parse_json(sorts_json, "sorts_json")
        data = client.query_database(
            database_id=database_id,
            filter=filter_payload,
            sorts=sorts_payload,
            page_size=min(limit, 100),
        )
        results = data.get("results", [])
        if not results:
            return "No results found."
        lines = [f"Found {len(results)} page(s):"]
        for page in results:
            title = _extract_title_from_page(page)
            page_id = page.get("id", "")
            url = page.get("url", "")
            lines.append(f"- {title} (ID: {page_id}) {url}")
        return "\n".join(lines)
    except Exception as exc:
        return f"Failed to query database: {exc}"


@tool
def notion_search(
    query: str,
    filter_json: Optional[str] = None,
    limit: int = 10,
) -> str:
    """Search Notion (pages/databases) with optional JSON filter."""
    try:
        client = NotionClient()
        filter_payload = _parse_json(filter_json, "filter_json")
        data = client.search(query=query, filter=filter_payload, page_size=min(limit, 100))
        results = data.get("results", [])
        if not results:
            return "No results found."
        lines = [f"Found {len(results)} result(s):"]
        for item in results:
            obj_type = item.get("object")
            if obj_type == "database":
                title = _extract_title_from_database(item)
            else:
                title = _extract_title_from_page(item)
            item_id = item.get("id", "")
            url = item.get("url", "")
            lines.append(f"- {obj_type}: {title} (ID: {item_id}) {url}")
        return "\n".join(lines)
    except Exception as exc:
        return f"Failed to search Notion: {exc}"
