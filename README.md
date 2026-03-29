# arXiv AI Daily Digest

Fetches the day's arXiv papers across cs.AI, cs.LG, cs.CL, and cs.CV, summarizes them with Gemini, and emails you a digest. Runs as a GCP Cloud Function triggered by Cloud Scheduler every weekday at 4 PM Mountain Time.

## Prerequisites

- [Google Cloud CLI (`gcloud`)](https://cloud.google.com/sdk/docs/install) — authenticated (`gcloud auth login`)
- A GCP account with a billing-enabled project (the free tier covers normal usage)
- A [Gemini API key](https://aistudio.google.com/app/apikey) (free tier available)
- A Gmail account with [2-Step Verification](https://myaccount.google.com/security) enabled and an [App Password](https://myaccount.google.com/apppasswords) generated for this app
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (for local development only)

## Setup

**1. Clone and configure**

```bash
git clone <repo-url>
cd arxiv-summarizer
cp .env.example .env
```

Edit `.env` and fill in your values:

```
GCP_PROJECT_ID=your-unique-project-id
GCP_REGION=us-central1
GEMINI_API_KEY=...
GMAIL_USER=you@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
RECIPIENT_EMAIL=you@example.com
```

**2. Deploy to GCP**

```bash
bash deploy.sh
```

The script will:
- Create the GCP project and enable required APIs
- Deploy the Cloud Function (gen2, Python 3.12)
- Create a Cloud Scheduler job to trigger it Mon–Fri at 4 PM Mountain Time
- Pause once to let you link billing — follow the prompt

**3. Test it**

Trigger a run immediately:

```bash
gcloud scheduler jobs run arxiv-daily-digest --location=<GCP_REGION>
```

Check logs:

```bash
gcloud functions logs read arxiv-summarizer --gen2 --region=<GCP_REGION> --limit=50
```

## Local development

Install dependencies:

```bash
uv venv && uv pip install -r requirements.txt
```

Run directly (calls Gemini and sends a real email):

```bash
source .env
uv run python -c "from main import summarize_arxiv; summarize_arxiv(None)"
```

Or simulate the HTTP trigger:

```bash
source .env
uv run functions-framework --target=summarize_arxiv --port=8080
# in another terminal:
curl http://localhost:8080
```

## Environment variables

| Variable | Description |
|---|---|
| `GCP_PROJECT_ID` | GCP project ID to create/use |
| `GCP_REGION` | Region for the function and scheduler (e.g. `us-central1`) |
| `FUNCTION_NAME` | Cloud Function name (default: `arxiv-summarizer`) |
| `GEMINI_API_KEY` | API key from Google AI Studio |
| `GMAIL_USER` | Gmail address used to send the digest |
| `GMAIL_APP_PASSWORD` | Gmail App Password (not your account password) |
| `RECIPIENT_EMAIL` | Address that receives the digest |
