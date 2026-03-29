

# To run locally with uv:
## one-time setup
```bash
uv venv && uv pip install -r requirements.txt
```
## run it directly
```bash
source .env
uv run python -c "from main import summarize_arxiv; summarize_arxiv(None)"
```
Or to simulate the actual HTTP trigger:

```bash
source .env
uv run functions-framework --target=summarize_arxiv --port=8080
## in another terminal:
curl http://localhost:8080

```