import os
import re
import sqlite3
import json
from functools import wraps
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from werkzeug.security import generate_password_hash, check_password_hash
import requests
from dotenv import load_dotenv
load_dotenv()


try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
except ImportError:
    Limiter = None


# OpenRouter API Setup
# Get a free key at https://openrouter.ai/keys
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "nvidia/nemotron-3.5-lightning:free")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Admin panel password — change this via environment variable before deploying.
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

app = Flask(__name__)

app.secret_key = os.getenv('SECRET_KEY', 'default_secret_key')

DB_PATH = os.path.join(os.path.dirname(__file__), "elearning.db")

# ---------------- RATE LIMITING ----------------
def _rate_limit_key():
    # Limit per logged-in student where possible, otherwise per IP.
    return f"user:{session['user_id']}" if "user_id" in session else get_remote_address()


if Limiter is not None:
    limiter = Limiter(key_func=_rate_limit_key, app=app, default_limits=[], storage_uri="memory://")
else:
    limiter = None


def ai_rate_limit(rule):
    """No-op decorator if flask-limiter isn't installed, so the app never crashes."""
    def decorator(f):
        if limiter is None:
            return f
        return limiter.limit(rule)(f)
    return decorator


# ---------------- SEED COURSE DATA (used once, to populate the DB on first run) ----------------
SEED_COURSES = [
    {
        "key": "cpp", "title": "C++ Programming", "icon": "code",
        "topics": [
            "C++ is a general-purpose programming language.",
            "Variables are containers used to store data values.",
            "Data types (int, float, char, bool) define what kind of data a variable can hold.",
            "Input/Output is handled using cin and cout.",
            "Operators (+, -, *, /, ==, &&) perform operations on values.",
            "If-else statements let a program make decisions.",
            "Switch statements handle multiple fixed choices.",
            "Loops (for, while) repeat a block of code.",
            "Functions let you package code so it can be reused.",
            "Arrays store multiple values of the same type together.",
        ],
        "questions": [
            {"q": "C++ is a?", "options": ["Programming Language", "Device"], "answer": 1},
            {"q": "Variables are used to?", "options": ["Print data", "Store data"], "answer": 2},
            {"q": "A loop is used to?", "options": ["Repeat code", "Stop program"], "answer": 1},
            {"q": "Functions are used to?", "options": ["Print output", "Reuse code"], "answer": 2},
            {"q": "Arrays are used to?", "options": ["Store multiple values", "Store a single value"], "answer": 1},
        ],
    },
    {
        "key": "physics", "title": "Physics", "icon": "atom",
        "topics": [
            "Physics is the study of matter and energy.",
            "Physical quantities are things that can be measured.",
            "Motion is a change in an object's position over time.",
            "Newton's laws describe the relationship between motion and force.",
            "Work is defined as Force multiplied by Distance.",
            "Energy is the ability to do work.",
            "Power is the rate at which work is done.",
            "Force can change an object's motion.",
            "Gravity is the force that pulls objects toward each other.",
            "Pressure equals Force divided by Area.",
        ],
        "questions": [
            {"q": "Physics studies?", "options": ["Matter & Energy", "Computers"], "answer": 1},
            {"q": "Motion is?", "options": ["Change in position", "Rest only"], "answer": 1},
            {"q": "Work is?", "options": ["Force only", "Force x Distance"], "answer": 2},
            {"q": "Energy is?", "options": ["Ability to do work", "Motion"], "answer": 1},
            {"q": "Power is?", "options": ["Energy", "Rate of work"], "answer": 2},
        ],
    },
    {
        "key": "ict", "title": "ICT", "icon": "monitor",
        "topics": [
            "ICT stands for Information and Communication Technology.",
            "A computer processes data into useful information.",
            "Hardware refers to the physical parts of a computer.",
            "Software refers to the instructions that tell hardware what to do.",
            "A keyboard is an input device.",
            "A monitor is an output device.",
            "Memory (RAM) stores data temporarily.",
            "Storage devices keep data permanently.",
            "The internet is a global network connecting computers.",
            "Computers are used daily in almost every field of life.",
        ],
        "questions": [
            {"q": "ICT stands for?", "options": ["Internet Tech", "Information Technology"], "answer": 2},
            {"q": "Keyboard is?", "options": ["Input device", "Output device"], "answer": 1},
            {"q": "Monitor is?", "options": ["Output device", "Input device"], "answer": 1},
            {"q": "Internet is?", "options": ["Software", "Global Network"], "answer": 2},
            {"q": "Memory stores?", "options": ["Temporary data", "Permanent data"], "answer": 1},
        ],
    },
]


# ---------------- DATABASE ----------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            class_name TEXT NOT NULL,
            roll TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            course_key TEXT NOT NULL,
            learning_status TEXT DEFAULT 'Not Started',
            score INTEGER DEFAULT 0,
            grade TEXT DEFAULT '-',
            attempts INTEGER DEFAULT 0,
            updated_at TEXT,
            UNIQUE(user_id, course_key),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS courses (
            key TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            icon TEXT DEFAULT 'book'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_key TEXT NOT NULL,
            position INTEGER NOT NULL,
            text TEXT NOT NULL,
            FOREIGN KEY(course_key) REFERENCES courses(key) ON DELETE CASCADE
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_key TEXT NOT NULL,
            position INTEGER NOT NULL,
            question_text TEXT NOT NULL,
            option1 TEXT NOT NULL,
            option2 TEXT NOT NULL,
            correct_answer INTEGER NOT NULL,
            FOREIGN KEY(course_key) REFERENCES courses(key) ON DELETE CASCADE
        )
    """)
    conn.commit()

    # Seed course data only the very first time (if courses table is empty).
    existing = conn.execute("SELECT COUNT(*) AS c FROM courses").fetchone()["c"]
    if existing == 0:
        for c in SEED_COURSES:
            conn.execute("INSERT INTO courses (key, title, icon) VALUES (?, ?, ?)",
                        (c["key"], c["title"], c["icon"]))
            for i, topic in enumerate(c["topics"]):
                conn.execute("INSERT INTO topics (course_key, position, text) VALUES (?, ?, ?)",
                            (c["key"], i, topic))
            for i, q in enumerate(c["questions"]):
                conn.execute("""
                    INSERT INTO questions (course_key, position, question_text, option1, option2, correct_answer)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (c["key"], i, q["q"], q["options"][0], q["options"][1], q["answer"]))
        conn.commit()

    conn.close()


def slugify(text):
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "course"


def get_courses_dict():
    """Rebuilds the COURSES-shaped dict from the database, so the rest of the app
    (dashboard, quiz, AI tutor) doesn't need to know courses now live in the DB."""
    conn = get_db()
    courses_rows = conn.execute("SELECT * FROM courses ORDER BY rowid").fetchall()
    result = {}
    for c in courses_rows:
        topics = conn.execute("SELECT text FROM topics WHERE course_key = ? ORDER BY position",
                              (c["key"],)).fetchall()
        questions = conn.execute("SELECT * FROM questions WHERE course_key = ? ORDER BY position",
                                 (c["key"],)).fetchall()
        result[c["key"]] = {
            "title": c["title"],
            "icon": c["icon"],
            "topics": [t["text"] for t in topics],
            "questions": [
                {"q": q["question_text"], "options": [q["option1"], q["option2"]], "answer": q["correct_answer"]}
                for q in questions
            ],
        }
    conn.close()
    return result


def calculate_grade(score):
    if score == 5:
        return "A"
    elif score >= 3:
        return "B"
    elif score >= 1:
        return "C"
    return "F"


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return wrapper


# ---------------- AI HELPER ----------------
def call_openrouter(messages, max_tokens=600, force_json=False):
    """Shared helper for talking to OpenRouter's chat completions endpoint."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return None, "AI is not configured. Set the OPENROUTER_API_KEY environment variable."

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": messages,
        "max_tokens": max_tokens
    }

    if force_json:
        payload["response_format"] = {"type": "json_object"}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:5000",
        "X-Title": "EduNova AI"
    }

    try:
        resp = requests.post(
            OPENROUTER_URL,
            headers=headers,
            json=payload,
            timeout=30,
        )
        result = resp.json()
        if resp.status_code != 200:
            return None, result.get("error", {}).get("message", "Unknown error from OpenRouter API.")
        choices = result.get("choices", [])
        if not choices:
            return None, "The AI didn't return a response."
        content = choices[0].get("message", {}).get("content", "").strip()
        return content, None
    except requests.exceptions.RequestException as e:
        return None, f"Network error contacting AI service: {str(e)}"


def get_wrong_answer_explanations(course_title, wrong_items):
    """Calls OpenRouter once for ALL wrong answers in a quiz attempt."""
    if not wrong_items:
        return []
    if not os.environ.get("OPENROUTER_API_KEY"):
        return None

    numbered = "\n".join(
        f'{i+1}. Question: "{item["question"]}" | Student answered: "{item["your_answer"]}" | '
        f'Correct answer: "{item["correct_answer"]}"'
        for i, item in enumerate(wrong_items)
    )
    system_prompt = (
        f"You are a tutor reviewing a student's {course_title} quiz. For each incorrect answer below, "
        "write a very short (max 20 words) explanation of why the correct answer is right. "
        'Respond ONLY with a JSON object of the form {"explanations": ["...", "...", ...]} '
        "with exactly one string per numbered item, in the same order. No other text."
    )
    content, err = call_openrouter(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": numbered},
        ],
        max_tokens=400,
        force_json=True,
    )
    if err or not content:
        return None
    try:
        parsed = json.loads(content)
        explanations = parsed.get("explanations", [])
        if len(explanations) != len(wrong_items):
            return None
        return explanations
    except (json.JSONDecodeError, AttributeError):
        return None


def generate_ai_quiz(course_title, topics, n=5):
    """Asks OpenRouter to write n fresh two-option MCQs based on the course's topic notes."""
    if not os.environ.get("OPENROUTER_API_KEY") or not topics:
        return None

    notes = "\n".join(f"- {t}" for t in topics)
    system_prompt = (
        f"You are writing a {n}-question multiple-choice quiz for {course_title} students, "
        "based ONLY on the notes below. Each question must have exactly 2 short options "
        "(one correct, one plausible-but-wrong), and cover a different note where possible. "
        "Keep questions and options short and unambiguous.\n\n"
        f"Notes:\n{notes}\n\n"
        'Respond ONLY with a JSON object: {"questions": [{"question": "...", '
        '"option1": "...", "option2": "...", "correct_answer": 1}, ...]} — exactly '
        f"{n} items, correct_answer is 1 or 2. No other text."
    )
    content, err = call_openrouter(
        messages=[{"role": "system", "content": system_prompt},
                  {"role": "user", "content": f"Write the {n}-question quiz now."}],
        max_tokens=900,
        force_json=True,
    )
    if err or not content:
        return None
    try:
        parsed = json.loads(content)
        raw_questions = parsed.get("questions", [])
        questions = []
        for item in raw_questions:
            q_text = (item.get("question") or "").strip()
            opt1 = (item.get("option1") or "").strip()
            opt2 = (item.get("option2") or "").strip()
            answer = item.get("correct_answer")
            if q_text and opt1 and opt2 and answer in (1, 2):
                questions.append({"q": q_text, "options": [opt1, opt2], "answer": answer})
        return questions if len(questions) == n else None
    except (json.JSONDecodeError, AttributeError, TypeError):
        return None

# ---------------- AUTH ROUTES ----------------
@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        class_name = request.form.get("class_name", "").strip()
        roll = request.form.get("roll", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if not all([name, class_name, roll, password, confirm]):
            flash("Please fill in all fields.", "error")
            return render_template("register.html")
        if len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
            return render_template("register.html")
        if password != confirm:
            flash("Passwords do not match.", "error")
            return render_template("register.html")

        conn = get_db()
        existing = conn.execute("SELECT id FROM users WHERE roll = ?", (roll,)).fetchone()
        if existing:
            flash("A student with this roll number already exists.", "error")
            conn.close()
            return render_template("register.html")

        conn.execute(
            "INSERT INTO users (name, class_name, roll, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
            (name, class_name, roll, generate_password_hash(password), datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()
        flash("Registration successful! Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        roll = request.form.get("roll", "").strip()
        password = request.form.get("password", "")

        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE roll = ?", (roll,)).fetchone()
        conn.close()

        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["name"] = user["name"]
            return redirect(url_for("dashboard"))

        flash("Invalid roll number or password.", "error")
    return render_template("login.html")


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        roll = request.form.get("roll", "").strip()
        new_password = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")

        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE roll = ? AND name = ?", (roll, name)).fetchone()

        if not user:
            flash("No matching student found.", "error")
            conn.close()
            return render_template("forgot_password.html")
        if len(new_password) < 8:
            flash("Password must be at least 8 characters.", "error")
            conn.close()
            return render_template("forgot_password.html")
        if new_password != confirm:
            flash("Passwords do not match.", "error")
            conn.close()
            return render_template("forgot_password.html")

        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                     (generate_password_hash(new_password), user["id"]))
        conn.commit()
        conn.close()
        flash("Password reset successful! Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("forgot_password.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


# ---------------- DASHBOARD / PROFILE ----------------
@app.route("/dashboard")
@login_required
def dashboard():
    courses = get_courses_dict()
    conn = get_db()
    rows = conn.execute("SELECT * FROM progress WHERE user_id = ?", (session["user_id"],)).fetchall()
    conn.close()
    progress_map = {r["course_key"]: r for r in rows}
    return render_template("dashboard.html", courses=courses, progress=progress_map)


@app.route("/profile")
@login_required
def profile():
    courses = get_courses_dict()
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    rows = conn.execute("SELECT * FROM progress WHERE user_id = ?", (session["user_id"],)).fetchall()
    conn.close()
    return render_template("profile.html", user=user, progress=rows, courses=courses)


# ---------------- LEARNING + QUIZ ----------------
@app.route("/course/<course_key>")
@login_required
def course_view(course_key):
    courses = get_courses_dict()
    if course_key not in courses:
        return redirect(url_for("dashboard"))
    return render_template("course.html", course=courses[course_key], course_key=course_key)


@app.route("/course/<course_key>/complete-learning", methods=["POST"])
@login_required
def complete_learning(course_key):
    courses = get_courses_dict()
    if course_key not in courses:
        return redirect(url_for("dashboard"))
    conn = get_db()
    conn.execute("""
        INSERT INTO progress (user_id, course_key, learning_status, updated_at)
        VALUES (?, ?, 'Completed', ?)
        ON CONFLICT(user_id, course_key)
        DO UPDATE SET learning_status = 'Completed', updated_at = excluded.updated_at
    """, (session["user_id"], course_key, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return redirect(url_for("quiz_view", course_key=course_key))


@app.route("/course/<course_key>/quiz")
@login_required
@ai_rate_limit("20 per hour")
def quiz_view(course_key):
    courses = get_courses_dict()
    if course_key not in courses:
        return redirect(url_for("dashboard"))
    conn = get_db()
    row = conn.execute("SELECT * FROM progress WHERE user_id = ? AND course_key = ?",
                       (session["user_id"], course_key)).fetchone()
    conn.close()
    if not row or row["learning_status"] != "Completed":
        flash("Please complete the learning section first.", "error")
        return redirect(url_for("course_view", course_key=course_key))

    course = courses[course_key]
    ai_questions = generate_ai_quiz(course["title"], course["topics"], n=len(course["questions"]) or 5)
    is_ai_generated = ai_questions is not None
    quiz_questions = ai_questions if is_ai_generated else course["questions"]

    # Stash the exact questions shown so grading checks against these, not whatever
    # the DB/AI happens to hold a moment later.
    session.setdefault("active_quizzes", {})
    session["active_quizzes"][course_key] = quiz_questions
    session.modified = True

    return render_template("quiz.html", course=course, course_key=course_key,
                          quiz_questions=quiz_questions, is_ai_generated=is_ai_generated)


@app.route("/course/<course_key>/quiz/submit", methods=["POST"])
@login_required
def submit_quiz(course_key):
    courses = get_courses_dict()
    if course_key not in courses:
        return redirect(url_for("dashboard"))

    # Grade against the exact question set the student was shown (AI-generated or not) —
    # falls back to the current DB questions if the session expired for some reason.
    active = session.get("active_quizzes", {})
    questions = active.get(course_key) or courses[course_key]["questions"]

    score = 0
    review = []
    for i, q in enumerate(questions):
        selected = request.form.get(f"q{i}")
        selected_int = int(selected) if selected else None
        correct = selected_int == q["answer"]
        if correct:
            score += 1
        review.append({
            "question": q["q"],
            "your_answer": q["options"][selected_int - 1] if selected_int else "No answer",
            "correct_answer": q["options"][q["answer"] - 1],
            "correct": correct,
        })

    if course_key in active:
        del active[course_key]
        session["active_quizzes"] = active
        session.modified = True

    grade = calculate_grade(score)

    conn = get_db()
    conn.execute("""
        UPDATE progress
        SET score = ?, grade = ?, attempts = attempts + 1, updated_at = ?
        WHERE user_id = ? AND course_key = ?
    """, (score, grade, datetime.now().isoformat(), session["user_id"], course_key))
    conn.commit()
    conn.close()

    # AI-generated explanations for wrong answers only (never blocks the result page on failure).
    wrong_items = [item for item in review if not item["correct"]]
    explanations = get_wrong_answer_explanations(courses[course_key]["title"], wrong_items)
    if explanations is not None:
        exp_iter = iter(explanations)
        for item in review:
            if not item["correct"]:
                item["explanation"] = next(exp_iter, None)

    return render_template("result.html", course=courses[course_key], course_key=course_key,
                          score=score, grade=grade, total=len(questions), review=review)


# ---------------- AI TUTOR ----------------
@app.route("/ai-tutor")
@login_required
def ai_tutor_page():
    courses = get_courses_dict()
    return render_template("ai_tutor.html", courses=courses,
                          ai_enabled=bool(os.environ.get("OPENROUTER_API_KEY")))


@app.route("/api/ai-tutor", methods=["POST"])
@login_required
@ai_rate_limit("15 per hour")
def api_ai_tutor():
    if not os.environ.get("OPENROUTER_API_KEY"):
        return jsonify({"error": "AI Tutor is not configured. Set the OPENROUTER_API_KEY environment variable on the server."}), 503

    data = request.get_json(force=True)
    message = (data.get("message") or "").strip()
    course_key = data.get("course_key", "")

    if not message:
        return jsonify({"error": "Message is empty."}), 400
    if len(message) > 1500:
        return jsonify({"error": "That message is too long. Try asking something shorter."}), 400

    courses = get_courses_dict()
    course_title = courses.get(course_key, {}).get("title", "general studies")
    system_prompt = (
        f"You are a friendly, patient AI tutor helping a student learn {course_title}. "
        "Explain concepts simply with short examples, use bullet points where helpful, "
        "and keep answers focused and not overly long. If asked something unrelated to "
        "studies, gently redirect the student back to their coursework."
    )

    answer_text, err = call_openrouter(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message},
        ],
        max_tokens=600,
    )
    if err:
        return jsonify({"error": f"AI request failed: {err}"}), 502
    return jsonify({"reply": answer_text or "Sorry, I couldn't generate a response to that. Try asking differently."})


if Limiter is not None:
    @app.errorhandler(429)
    def rate_limit_exceeded(e):
        if request.path.startswith("/api/"):
            return jsonify({"error": "You've asked a lot of questions! Please wait a bit before asking another."}), 429
        flash("You've hit the AI Tutor's usage limit for now — please try again shortly.", "error")
        return redirect(url_for("ai_tutor_page"))


# ---------------- ADMIN PANEL ----------------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        password = request.form.get("password", "")
        if password == ADMIN_PASSWORD:
            session["is_admin"] = True
            return redirect(url_for("admin_dashboard"))
        flash("Incorrect admin password.", "error")
    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("index"))


@app.route("/admin")
@admin_required
def admin_dashboard():
    conn = get_db()
    courses = conn.execute("""
        SELECT c.*,
            (SELECT COUNT(*) FROM topics t WHERE t.course_key = c.key) AS topic_count,
            (SELECT COUNT(*) FROM questions q WHERE q.course_key = c.key) AS question_count
        FROM courses c ORDER BY c.rowid
    """).fetchall()
    student_count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    conn.close()
    return render_template("admin_dashboard.html", courses=courses, student_count=student_count)


@app.route("/admin/course/add", methods=["POST"])
@admin_required
def admin_add_course():
    title = request.form.get("title", "").strip()
    icon = request.form.get("icon", "book").strip() or "book"
    if not title:
        flash("Course title is required.", "error")
        return redirect(url_for("admin_dashboard"))

    conn = get_db()
    base_key = slugify(title)
    key = base_key
    suffix = 2
    while conn.execute("SELECT 1 FROM courses WHERE key = ?", (key,)).fetchone():
        key = f"{base_key}-{suffix}"
        suffix += 1

    conn.execute("INSERT INTO courses (key, title, icon) VALUES (?, ?, ?)", (key, title, icon))
    conn.commit()
    conn.close()
    flash(f'Course "{title}" created.', "success")
    return redirect(url_for("admin_course_edit", course_key=key))


@app.route("/admin/course/<course_key>")
@admin_required
def admin_course_edit(course_key):
    conn = get_db()
    course = conn.execute("SELECT * FROM courses WHERE key = ?", (course_key,)).fetchone()
    if not course:
        conn.close()
        flash("Course not found.", "error")
        return redirect(url_for("admin_dashboard"))
    topics = conn.execute("SELECT * FROM topics WHERE course_key = ? ORDER BY position", (course_key,)).fetchall()
    questions = conn.execute("SELECT * FROM questions WHERE course_key = ? ORDER BY position", (course_key,)).fetchall()
    conn.close()
    return render_template("admin_course.html", course=course, topics=topics, questions=questions)


@app.route("/admin/course/<course_key>/update", methods=["POST"])
@admin_required
def admin_update_course(course_key):
    title = request.form.get("title", "").strip()
    icon = request.form.get("icon", "").strip() or "book"
    if title:
        conn = get_db()
        conn.execute("UPDATE courses SET title = ?, icon = ? WHERE key = ?", (title, icon, course_key))
        conn.commit()
        conn.close()
        flash("Course details updated.", "success")
    return redirect(url_for("admin_course_edit", course_key=course_key))


@app.route("/admin/course/<course_key>/delete", methods=["POST"])
@admin_required
def admin_delete_course(course_key):
    conn = get_db()
    conn.execute("DELETE FROM courses WHERE key = ?", (course_key,))
    conn.execute("DELETE FROM topics WHERE course_key = ?", (course_key,))
    conn.execute("DELETE FROM questions WHERE course_key = ?", (course_key,))
    conn.execute("DELETE FROM progress WHERE course_key = ?", (course_key,))
    conn.commit()
    conn.close()
    flash("Course deleted.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/course/<course_key>/topic/add", methods=["POST"])
@admin_required
def admin_add_topic(course_key):
    text = request.form.get("text", "").strip()
    if text:
        conn = get_db()
        next_pos = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 AS p FROM topics WHERE course_key = ?",
                                (course_key,)).fetchone()["p"]
        conn.execute("INSERT INTO topics (course_key, position, text) VALUES (?, ?, ?)",
                    (course_key, next_pos, text))
        conn.commit()
        conn.close()
    return redirect(url_for("admin_course_edit", course_key=course_key))


@app.route("/admin/course/<course_key>/topic/<int:topic_id>/delete", methods=["POST"])
@admin_required
def admin_delete_topic(course_key, topic_id):
    conn = get_db()
    conn.execute("DELETE FROM topics WHERE id = ? AND course_key = ?", (topic_id, course_key))
    conn.commit()
    conn.close()
    return redirect(url_for("admin_course_edit", course_key=course_key))


@app.route("/admin/course/<course_key>/question/add", methods=["POST"])
@admin_required
def admin_add_question(course_key):
    question_text = request.form.get("question_text", "").strip()
    option1 = request.form.get("option1", "").strip()
    option2 = request.form.get("option2", "").strip()
    correct_answer = request.form.get("correct_answer", "1")

    if question_text and option1 and option2:
        conn = get_db()
        next_pos = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 AS p FROM questions WHERE course_key = ?",
                                (course_key,)).fetchone()["p"]
        conn.execute("""
            INSERT INTO questions (course_key, position, question_text, option1, option2, correct_answer)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (course_key, next_pos, question_text, option1, option2, int(correct_answer)))
        conn.commit()
        conn.close()
    return redirect(url_for("admin_course_edit", course_key=course_key))


@app.route("/admin/course/<course_key>/question/<int:question_id>/delete", methods=["POST"])
@admin_required
def admin_delete_question(course_key, question_id):
    conn = get_db()
    conn.execute("DELETE FROM questions WHERE id = ? AND course_key = ?", (question_id, course_key))
    conn.commit()
    conn.close()
    return redirect(url_for("admin_course_edit", course_key=course_key))


init_db()  # runs on import too, so gunicorn/production servers create tables correctly

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)