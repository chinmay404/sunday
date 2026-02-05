from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import requests

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = os.getenv("NOTION_VERSION", "2022-06-28")


class NotionClient:
    """Lightweight Notion API client using requests."""

    def __init__(self, token: Optional[str] = None):
        token = token or os.getenv("NOTION_API_KEY")
        if not token:
            raise ValueError("NOTION_API_KEY not found in environment")
        self.token = token

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def request(
        self,
        method: str,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{NOTION_API_BASE}{path}"
        response = requests.request(
            method=method,
            url=url,
            headers=self._headers(),
            json=json,
            params=params,
            timeout=20,
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"Notion API error {response.status_code}: {response.text}"
            )
        return response.json()

    def retrieve_database(self, database_id: str) -> Dict[str, Any]:
        return self.request("GET", f"/databases/{database_id}")

    def query_database(
        self,
        database_id: str,
        filter: Optional[Dict[str, Any]] = None,
        sorts: Optional[List[Dict[str, Any]]] = None,
        page_size: Optional[int] = None,
        start_cursor: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if filter:
            payload["filter"] = filter
        if sorts:
            payload["sorts"] = sorts
        if page_size:
            payload["page_size"] = page_size
        if start_cursor:
            payload["start_cursor"] = start_cursor
        return self.request("POST", f"/databases/{database_id}/query", json=payload)

    def create_page(
        self,
        parent: Dict[str, Any],
        properties: Dict[str, Any],
        children: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"parent": parent, "properties": properties}
        if children:
            payload["children"] = children
        return self.request("POST", "/pages", json=payload)

    def update_page(self, page_id: str, properties: Dict[str, Any]) -> Dict[str, Any]:
        payload = {"properties": properties}
        return self.request("PATCH", f"/pages/{page_id}", json=payload)

    def retrieve_page(self, page_id: str) -> Dict[str, Any]:
        return self.request("GET", f"/pages/{page_id}")

    def append_blocks(
        self, block_id: str, children: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        payload = {"children": children}
        return self.request("PATCH", f"/blocks/{block_id}/children", json=payload)

    def list_block_children(
        self,
        block_id: str,
        page_size: Optional[int] = None,
        start_cursor: Optional[str] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if page_size:
            params["page_size"] = page_size
        if start_cursor:
            params["start_cursor"] = start_cursor
        return self.request("GET", f"/blocks/{block_id}/children", params=params)

    def search(
        self,
        query: Optional[str] = None,
        filter: Optional[Dict[str, Any]] = None,
        sort: Optional[Dict[str, Any]] = None,
        page_size: Optional[int] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if query:
            payload["query"] = query
        if filter:
            payload["filter"] = filter
        if sort:
            payload["sort"] = sort
        if page_size:
            payload["page_size"] = page_size
        return self.request("POST", "/search", json=payload)
