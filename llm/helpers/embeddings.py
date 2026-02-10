import os
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from dotenv import load_dotenv

def get_embeddings():
    """
    Returns the configured Google Gemini Embeddings model.
    Ensure GOOGLE_API_KEY is set in your environment variables.
    """
    # Load environment variables if not already loaded
    if "GOOGLE_API_KEY" not in os.environ:
        load_dotenv()
        
    if "GOOGLE_API_KEY" not in os.environ:
        raise ValueError("GOOGLE_API_KEY not found in environment variables. Please set it to use Google Gemini Embeddings.")

    return GoogleGenerativeAIEmbeddings(model="gemini-embedding-001")
