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
