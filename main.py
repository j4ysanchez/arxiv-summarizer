import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone
from html import escape

import arxiv
import google.generativeai as genai
import functions_framework

CATEGORIES = ["cs.AI", "cs.LG", "cs.CL", "cs.CV"]
MAX_PAPERS = 150
MAX_PAPERS_TO_SUMMARIZE = 50  # cap sent to Gemini to stay within token limits


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_papers() -> list[dict]:
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=36)  # buffer to catch late-posted papers

    date_filter = (
        f"submittedDate:[{since.strftime('%Y%m%d%H%M%S')} "
        f"TO {now.strftime('%Y%m%d%H%M%S')}]"
    )
    cat_filter = " OR ".join(f"cat:{cat}" for cat in CATEGORIES)
    query = f"({cat_filter}) AND {date_filter}"

    client = arxiv.Client(num_retries=3, delay_seconds=3)
    search = arxiv.Search(
        query=query,
        max_results=MAX_PAPERS,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending,
    )

    papers = []
    seen = set()
    for result in client.results(search):
        if result.entry_id in seen:
            continue
        seen.add(result.entry_id)
        papers.append({
            "title": result.title.strip(),
            "authors": [a.name for a in result.authors[:3]],
            "more_authors": max(0, len(result.authors) - 3),
            "abstract": result.summary.replace("\n", " ").strip(),
            "url": result.entry_id,
            "categories": result.categories[:3],
            "published": result.published.strftime("%Y-%m-%d"),
        })

    return papers


# ---------------------------------------------------------------------------
# Summarize
# ---------------------------------------------------------------------------

def build_prompt(papers: list[dict]) -> str:
    lines = []
    for i, p in enumerate(papers[:MAX_PAPERS_TO_SUMMARIZE], 1):
        lines.append(f"[{i}] {p['title']}\nAbstract: {p['abstract'][:600]}")
    paper_block = "\n\n".join(lines)

    return f"""You are an AI research digest editor. Below are today's arXiv papers in AI/ML.

Your task:
1. Write a 3-4 sentence "Today's Highlights" paragraph identifying the most significant trends or breakthroughs.
2. Select the 10 most noteworthy papers and write a 2-3 sentence summary for each explaining what it does and why it matters.

Format your response EXACTLY as shown (do not deviate):
---HIGHLIGHTS---
[your highlights paragraph]
---PAPERS---
[1] Title: [paper title]
Summary: [2-3 sentence summary]

[2] Title: [paper title]
Summary: [2-3 sentence summary]
---END---

Papers:
{paper_block}"""


def call_gemini(papers: list[dict]) -> str:
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    model = genai.GenerativeModel("gemini-2.5-flash")
    response = model.generate_content(build_prompt(papers))
    return response.text


def parse_gemini_response(text: str) -> tuple[str, list[dict]]:
    highlights = ""
    featured = []

    try:
        h_start = text.index("---HIGHLIGHTS---") + len("---HIGHLIGHTS---")
        p_start = text.index("---PAPERS---")
        end = text.index("---END---")

        highlights = text[h_start:p_start].strip()
        papers_section = text[p_start + len("---PAPERS---"):end].strip()

        for block in re.split(r"\[\d+\]", papers_section):
            if not block.strip():
                continue
            title_m = re.search(r"Title:\s*(.+)", block)
            summary_m = re.search(r"Summary:\s*(.+)", block, re.DOTALL)
            if title_m and summary_m:
                featured.append({
                    "title": title_m.group(1).strip(),
                    "summary": re.sub(r"\s+", " ", summary_m.group(1)).strip(),
                })
    except ValueError:
        highlights = text  # fallback: dump raw response as highlights

    return highlights, featured


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def _find_url(title: str, all_papers: list[dict]) -> str:
    needle = title.lower()[:50]
    for p in all_papers:
        if needle in p["title"].lower():
            return p["url"]
    return "#"


def build_html(date_str: str, highlights: str, featured: list[dict], papers: list[dict]) -> str:
    featured_html = ""
    for paper in featured:
        url = _find_url(paper["title"], papers)
        featured_html += f"""
        <div style="margin-bottom:20px;padding:16px;background:#f8f9fa;border-left:4px solid #4285f4;border-radius:4px;">
            <h3 style="margin:0 0 8px 0;font-size:15px;">
                <a href="{url}" style="color:#1a73e8;text-decoration:none;">{escape(paper['title'])}</a>
            </h3>
            <p style="margin:0;color:#444;font-size:14px;line-height:1.6;">{escape(paper['summary'])}</p>
        </div>"""

    all_rows = ""
    for p in papers:
        cats = " · ".join(p["categories"])
        authors = ", ".join(p["authors"])
        if p["more_authors"]:
            authors += f" +{p['more_authors']} more"
        all_rows += f"""
        <tr>
            <td style="padding:10px 0;border-bottom:1px solid #eee;vertical-align:top;">
                <a href="{p['url']}" style="color:#1a73e8;text-decoration:none;font-weight:500;font-size:13px;">{escape(p['title'])}</a><br>
                <span style="color:#666;font-size:12px;">{escape(authors)}</span><br>
                <span style="color:#999;font-size:11px;">{cats}</span>
            </td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:700px;margin:0 auto;padding:20px;color:#222;">

  <div style="background:#4285f4;padding:24px 28px;border-radius:10px;margin-bottom:28px;">
    <h1 style="color:#fff;margin:0;font-size:22px;font-weight:600;">arXiv AI Daily Digest</h1>
    <p style="color:rgba(255,255,255,0.85);margin:6px 0 0;font-size:14px;">
      {date_str} &nbsp;·&nbsp; {len(papers)} papers &nbsp;·&nbsp; cs.AI · cs.LG · cs.CL · cs.CV
    </p>
  </div>

  <h2 style="font-size:17px;color:#333;border-bottom:2px solid #4285f4;padding-bottom:8px;">Today's Highlights</h2>
  <p style="color:#444;font-size:14px;line-height:1.8;">{escape(highlights)}</p>

  <h2 style="font-size:17px;color:#333;border-bottom:2px solid #4285f4;padding-bottom:8px;margin-top:32px;">
    Featured Papers
  </h2>
  {featured_html}

  <h2 style="font-size:17px;color:#333;border-bottom:2px solid #4285f4;padding-bottom:8px;margin-top:32px;">
    All Papers ({len(papers)})
  </h2>
  <table style="width:100%;border-collapse:collapse;">{all_rows}</table>

  <p style="color:#bbb;font-size:11px;text-align:center;margin-top:36px;">
    arXiv AI Summarizer · Powered by Gemini 1.5 Flash
  </p>
</body>
</html>"""


def send_email(subject: str, html_body: str) -> None:
    sender = os.environ["GMAIL_USER"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ["RECIPIENT_EMAIL"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"arXiv Digest <{sender}>"
    msg["To"] = recipient
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, recipient, msg.as_string())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

@functions_framework.http
def summarize_arxiv(request):
    try:
        print("Fetching papers from arXiv...")
        papers = fetch_papers()

        if not papers:
            print("No papers found — arXiv may not have posted today (weekend/holiday).")
            return "No papers found", 200

        print(f"Found {len(papers)} papers. Summarizing with Gemini...")
        raw = call_gemini(papers)
        highlights, featured = parse_gemini_response(raw)

        date_str = datetime.now(timezone.utc).strftime("%A, %B %d, %Y")
        subject = f"arXiv AI Digest — {datetime.now(timezone.utc).strftime('%b %d, %Y')} ({len(papers)} papers)"
        html = build_html(date_str, highlights, featured, papers)

        print("Sending email...")
        send_email(subject, html)

        msg = f"Sent digest: {len(papers)} papers, {len(featured)} featured."
        print(msg)
        return msg, 200

    except Exception as e:
        print(f"Error: {e}")
        raise
