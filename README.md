---
title: Job Agent
emoji: 🤖
colorFrom: green
colorTo: blue
sdk: docker
pinned: false
license: mit
---

# Job Agent — AI Job Search & CV Generator

An AI-powered agent that searches **LinkedIn, Indeed, Glassdoor, and Monster** — scores each job with **Claude AI** — generates tailored CVs — and exports everything.

Upload **any CV** (any background, any person) and the agent automatically extracts your profile, searches for matching jobs, scores them, and generates cover letters.

---

## 🚀 Deploy on Hugging Face Spaces (Free, 24/7)

### Live Demo

[![Live Demo](https://img.shields.io/badge/%F0%9F%A4%97%20Live%20Demo-View%20on%20HF-blue)](https://huggingface.co/spaces/gouklkrishan/job-agent)

**[huggingface.co/spaces/Gouklkrishan/job-agent](https://huggingface.co/spaces/gouklkrishan/job-agent)** — accessible from any device (phone, tablet, laptop).

### Deploy Your Own

1. **[Create a new Space](https://huggingface.co/new-space?docker=python&template=docker)** on Hugging Face
2. Set **Space name** (e.g., `job-agent`), **Space SDK**: Docker
3. Clone it: `git clone https://huggingface.co/spaces/YOUR_USERNAME/job-agent`

### Push your code to the Space

```bash
# Clone your Space
git clone https://huggingface.co/spaces/YOUR_USERNAME/job-agent
cd job-agent

# Copy all files from this project
# (copy Dockerfile, agent/, profiles/, requirements.txt, etc.)

# Or push directly from GitHub — see Auto-Deploy section below

# Push
git add .
git commit -m "Initial deploy"
git push
```

### Set your API Key

In your Space's **Settings → Repository Secrets**:
- `OPENROUTER_API_KEY` → Your OpenRouter API key (get one at https://openrouter.ai)

### Optional: Enable Google Sign-In

1. Get your Google OAuth credentials from [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. In your Space's **Settings → Repository Secrets**, add:
   - `GOOGLE_CLIENT_ID` → Your Google OAuth client ID
   - `GOOGLE_CLIENT_SECRET` → Your Google OAuth client secret
   - `APP_URL` → `https://YOUR_USERNAME-job-agent.hf.space` (your Space's URL)
3. In your Google Cloud Console, add this **Authorized redirect URI**:  
   `https://YOUR_USERNAME-job-agent.hf.space/login/google/callback`

Then restart your Space — the **Sign in with Google** button will be active.

### Optional: Auto-Deploy from GitHub

Set up CI/CD so your Space updates automatically every time you push code to GitHub:

1. Get a **Hugging Face token** at **[hf.co/settings/tokens](https://huggingface.co/settings/tokens)** → **New token** → Scope: **write**
2. In your **GitHub repo → Settings → Secrets and variables → Actions**, add:
   - **Repository secret**: `HF_TOKEN` → paste your HF token
   - **Repository variable** (optional if your Space name isn't `job-agent`): `HF_SPACE_NAME` → `your-space-name`
   - **Repository variable** (optional if your GitHub username ≠ HF username): `HF_SPACE_OWNER` → `your-hf-username`
3. Push to `main` — the workflow in `.github/workflows/ci.yml` will:
   - ✅ Run tests (Python 3.10, 3.11, 3.12)
   - ✅ Lint with flake8, black, isort
   - ✅ Build Docker image
   - 🚀 Deploy to your Hugging Face Space

No more manual `git push` to HF — just push to GitHub and it auto-deploys.

### That's it!

Your Space will build and start. Open the **App** tab to see the dashboard.  
Upload any CV and click **Run Agent** — it works from any device.

---

## 🏠 Local Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Set your API key
```bash
export OPENROUTER_API_KEY="sk-or-..."
```
Get a free key at https://openrouter.ai



### 3. Run the dashboard
```bash
python -m agent dashboard
```

Open http://127.0.0.1:8080 in your browser.  
Upload any CV and click **Run Agent**.

---

## 🎮 Usage

### Web Dashboard (recommended)
```bash
python -m agent dashboard
```
- Upload any CV (PDF) — the agent auto-extracts your full profile
- Set your API key in the browser
- Click **Run Agent** — watch live terminal output
- Download generated CVs and job listings
- View scoring history with filters

### Command Line (headless)
```bash
python -m agent run --headless
```

### Options
```
--headless      Run browser invisibly (default: False)
--profile       Path to profile JSON (default: profiles/profile.json)
--resume        Path to resume PDF (default: resume.pdf)
--max-jobs      Max jobs to search per platform (0 = unlimited)
```

---

## ✨ Features

- **Auto-Profile Extraction** — Upload any CV; the agent reads it with AI and extracts name, skills, experience, education, and target roles automatically
- **Multi-Platform Search** — LinkedIn, Indeed, Glassdoor, Monster
- **AI Scoring** — Claude scores each job (0-100) and writes tailored cover letters
- **Title-Only Scoring** — AI-related jobs without descriptions still get scored
- **Custom Keywords** — Configurable AI keyword list in `profile.json`
- **CV Generation** — Generates tailored CV PDFs for top matches
- **Word Export** — Exports job listings to `.docx`
- **Scoring History** — View past results with filters (score, platform, status, type)
- **Mark as Applied** — Track which jobs you've applied to
- **Any Background** — Works for AI Engineer, Data Analyst, Accountant, Designer — any CV

---

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENROUTER_API_KEY` | Your OpenRouter API key | Required |
| `DASHBOARD_HOST` | Web dashboard host | `127.0.0.1` (or `0.0.0.0` on HF Spaces) |
| `DASHBOARD_PORT` | Web dashboard port | `8080` (or `7860` on HF Spaces) |
| `HEADLESS` | Run browser invisibly | `false` |
| `MIN_SCORE` | Minimum AI score for high match | `70` |
| `MAX_JOB_SEARCH` | Max jobs per platform | `0` (unlimited) |

---

## Project Structure

```
job-agent/
├── agent/
│   ├── main.py          ← Main agent (run, dashboard commands)
│   ├── ai.py            ← Claude integration (scoring, profile extraction)
│   ├── config.py        ← Configuration management
│   ├── dashboard.py     ← Web GUI (Flask)
│   ├── scrapers.py      ← Browser-based job scrapers (Playwright)
│   ├── tracker.py       ← Results tracking & history
│   ├── models.py        ← Data models (Job, Platform)
│   ├── utils.py         ← Resume parsing, utilities
│   └── word_exporter.py ← DOCX export
├── profiles/
│   └── profile.json     ← Auto-filled from CV (was: manual profile)
├── logs/
│   ├── applications.json ← Scoring history
│   └── sessions/        ← Saved browser sessions
├── Dockerfile           ← For Hugging Face Spaces & Docker deployment
├── requirements.txt
└── README.md
```

---

## Notes

- **LinkedIn** requires you to be logged in — open the dashboard browser, log into LinkedIn, then run the agent
- **Playwright** is used for browser automation — installs Chromium automatically
- **Rate limiting**: Adaptive delays between requests to avoid account bans
- **All data stays local** (or on your HF Space) — no third-party servers
