from langchain_community.tools import DuckDuckGoSearchRun
from langchain_core.tools import tool


search = DuckDuckGoSearchRun()


@tool
def get_search(querry: str):
    """To Search Any querry Online Given By User use this tool 

    Args:
        querry (str)

    """
    if search:
        return search.invoke(querry)
    return "Tool Faced Some Issue tell about this to user "
