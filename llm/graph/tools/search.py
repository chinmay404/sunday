from langchain_community.tools import DuckDuckGoSearchRun
from langchain_core.tools import tool


search = DuckDuckGoSearchRun()


@tool
def get_search(querry: str):
    """Search the internet for any query. Returns top results."""
    if search:
        return search.invoke(querry)
    return "Search tool unavailable right now."
