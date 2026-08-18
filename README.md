# EduNova AI
### An Intelligent E-Learning & Assessment Platform

A Flask conversion of the original C++ console e-learning system, with a modern web UI,
persistent accounts (SQLite), and an AI Tutor powered by Groq's free API.

## Features
- Register / log in / forgot password (passwords hashed with Werkzeug)
- **Show/hide password** eye button on every password field
- Three courses: C++, Physics, ICT — each with learning notes + a 5-question timed quiz
  (now stored in the database, not hardcoded — see Admin panel below)
- **AI-generated quiz questions**: every time a student starts a quiz, Groq writes a
  fresh set of questions from that course's notes — different each attempt, so answers
  can't just be memorized/shared. If Groq isn't configured or a generation fails, it
  automatically falls back to the fixed question set from the database, so the quiz
  never breaks
- Auto-grading (A/B/C/F) with a per-question review of right/wrong answers
- **AI-generated explanations** for wrong quiz answers — after submitting, each missed
  question gets a short "why this is the answer" from the AI, right on the result page
- Progress saved per student in SQLite (survives restarts)
- Profile page with course history
- **AI Tutor**: a chat page where students can ask questions and get answers powered by
  Groq's free tier — very fast responses (Groq runs on custom LPU chips), open-source
  Llama models, no billing needed
- **Rate limiting** on the AI Tutor and quiz-explanation calls, so one student can't burn
  through the whole class's free Groq quota by spamming requests
- **Admin panel** (`/admin/login`) for teachers to add/edit/delete courses, topics, and
  quiz questions — no code editing required

## 1. Install dependencies
```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Set up the Admin panel password
The admin panel is protected by a single shared password (separate from student
accounts). Set it via environment variable — the default is `admin123`, **change this
before deploying anywhere real**:

```bash
export ADMIN_PASSWORD="pick-a-strong-password"
```

Then visit `/admin/login` (also linked in the site footer) to add courses, topics, and
quiz questions. Anything you add there shows up immediately for students — no restart or
code changes needed.

## 3. Get a free Groq API key (for the AI Tutor + answer explanations)
1. Go to **https://console.groq.com/keys**
2. Sign in with email, Google, or GitHub — no credit card required
3. Click "Create API Key" and copy it (starts with `gsk_...`)

Groq's free tier (as of mid-2026) gives a real ongoing daily quota, roughly 1,000
requests/day and ~12,000 tokens/minute on the default model (`llama-3.3-70b-versatile`),
which is plenty for a class-sized AI Tutor. Limits are per-organization, not per key, and
can change — check current numbers at https://console.groq.com/settings/limits.

Set the key as an environment variable — **never hard-code it in the source file**:

```bash
export GROQ_API_KEY="gsk_...."      # Windows: set GROQ_API_KEY=gsk_....
```

Or create a `.env` file in this folder:
```
GROQ_API_KEY=gsk_....
SECRET_KEY=some-long-random-string
```
and load it by adding `from dotenv import load_dotenv; load_dotenv()` at the top of `app.py`
(python-dotenv is already in requirements.txt).

If no key is set, the whole app still works — the AI Tutor page just shows a notice that
it isn't configured, instead of crashing.

You can swap the model any time with the `GROQ_MODEL` environment variable — e.g.
`llama-3.1-8b-instant` for higher daily request limits but slightly lower quality, or
`openai/gpt-oss-120b` for stronger reasoning at a lower token cap.

### Want to use Claude or Gemini instead later?
The AI Tutor logic lives entirely in `api_ai_tutor()` in `app.py`. Swapping providers is
a small, self-contained change — the rest of the app (auth, courses, quizzes, progress)
doesn't touch this code at all.

## 4. Run it
```bash
python app.py
```
Visit **http://localhost:5000** (students) or **http://localhost:5000/admin/login** (admin)

## 5. Push this project to GitHub

```bash
cd edunova_ai                     # this folder
git init
git add .
git commit -m "Initial commit — EduNova AI"
```

Then on **github.com**: click **New repository** → name it (e.g. `edunova-ai`) → **don't**
check "Add a README" (you already have one) → Create repository. GitHub will show you a
remote URL — copy it, then:

```bash
git remote add origin https://github.com/YOUR-USERNAME/edunova-ai.git
git branch -M main
git push -u origin main
```

The `.gitignore` file already included makes sure `.env`, `elearning.db`, and `venv/`
never get pushed — so your API keys and admin password stay off GitHub even if you use a
`.env` file locally. **Double-check** with `git status` before your first commit that none
of those show up as "to be committed."

## 6. Deploy live, for free — Render

Render currently has the most straightforward free path for a Flask app like this one
(as of mid-2026). Free-tier limits change over time on every host, so it's worth a quick
check on Render's pricing page before you commit, but the steps below are stable:

1. Go to **https://render.com** → sign up with your GitHub account
2. **New +** → **Web Service** → pick the `edunova-ai` repo you just pushed
3. Fill in:
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app` (already set for you via the included `Procfile`)
   - **Instance Type:** Free
4. Under **Environment Variables**, add:
   - `GROQ_API_KEY` → your Groq key
   - `ADMIN_PASSWORD` → your own strong password
   - `SECRET_KEY` → any long random string (e.g. generate one with `python -c "import secrets; print(secrets.token_hex(32))"`)
5. Click **Create Web Service**. First deploy takes a couple of minutes — Render gives
   you a live URL like `https://edunova-ai.onrender.com` when it's done.

**Two free-tier things to know:**
- The free instance **sleeps after ~15 minutes of no traffic** — the next visitor waits
  roughly 30–60 seconds for it to wake up. Fine for a class project/demo; upgrade to a
  paid instance later if you need it always-on.
- Render's free disk is **ephemeral** — every redeploy wipes it, which means the SQLite
  file (`elearning.db`, with all your students and their progress) resets too. For a
  quick demo this is fine. For a real class you'll want a small persistent database
  instead — Render's own free PostgreSQL, or a free Postgres from Neon/Supabase, and a
  short code change from `sqlite3` to `psycopg2` in `get_db()`. Ask me if you want that
  change made before you deploy for real.

### Alternatives to Render
- **Railway** (railway.app) — similar Git-push workflow, good if you also want a managed
  database in the same place; free usage is credit-based rather than unlimited hours
- **PythonAnywhere** — very beginner-friendly browser-based setup, but the free tier
  blocks outbound internet calls, which would break the AI Tutor/quiz-generation features
  that call the Groq API — only use this one if you're fine running without AI features
- **Fly.io / Google Cloud Run** — more control via Docker, worth it once you outgrow the
  simple platforms above

## 7. Deploying for real — other suggestions
- Switch SQLite to PostgreSQL if you expect many concurrent students — the built-in
  `Flask-Limiter` rate limiter also currently stores counts in memory, which resets on
  restart and doesn't share state across multiple server processes; swap its
  `storage_uri` to Redis for production
- Put `SECRET_KEY`, `GROQ_API_KEY`, and `ADMIN_PASSWORD` in your host's environment
  variable settings, never in the code or in git
- Render/Railway both give you HTTPS on the free tier automatically

## Suggested next improvements
1. **Email verification** on registration instead of trusting name+roll for password reset
2. **Randomize** the admin-written fixed question set too (currently only the AI-generated
   quiz path is naturally different each time)
3. **Leaderboard** per class to add friendly competition
4. **Multi-admin accounts** with individual logins instead of one shared password
5. **Export progress** to PDF/Excel for teachers (there are ready-made skills for this if
   you build with Claude again)
6. **Difficulty control** for AI-generated quizzes (easy/medium/hard prompt variants)
