# Sunday LLM Agent

## Setup

1. Install dependencies:
   ```bash
   pip install -r ../requirement.txt
   pip install langchain_google_genai langchain_community
   ```

2. Set up environment variables:
   Create a `.env` file in the root directory or export the variable:
   ```bash
   export GOOGLE_API_KEY="your_api_key_here"
   ```

## Running the Agent

Run the main script:
```bash
python3 llm/main.py
```

## Running the API

Start the FastAPI server:
```bash
python3 llm/api.py
```
or directly with uvicorn:
```bash
uvicorn llm.api:app --reload
```

The API will be available at `http://localhost:8000`.
You can access the interactive documentation at `http://localhost:8000/docs`.

### Test the API
```bash
curl -X POST "http://localhost:8000/chat" \
     -H "Content-Type: application/json" \
     -d '{"message": "Hello Sunday", "thread_id": "test-1"}'
```
