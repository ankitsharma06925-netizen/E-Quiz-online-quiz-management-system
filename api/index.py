import csv
import io
import os

from flask import Flask, request, jsonify, session, send_from_directory, render_template
from werkzeug.security import generate_password_hash, check_password_hash
import mysql.connector
from mysql.connector import pooling
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

TEMPLATES_DIR = os.path.join(CURRENT_DIR, "..", "templates")

app = Flask(__name__, template_folder=TEMPLATES_DIR)
app.secret_key = "123456789"
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

DB_CONFIG = {
    "host": "mysql-399982eb-quiz-management.f.aivencloud.com",
    "user": "avnadmin",
    "password": "AVNS_YK6_DeQmwJt7qSfRrWc",
    "database": "equiz",
}

pool = pooling.MySQLConnectionPool(pool_name="equiz_pool", pool_size=5, **DB_CONFIG)

DEPARTMENTS = ["Computer Science", "Physics", "General Science", "Geography"]


def get_db():
    return pool.get_connection()


def query(sql, params=None, fetchone=False, fetchall=False, commit=False, last_id=False):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute(sql, params or ())
    result = None
    if fetchone:
        result = cur.fetchone()
    elif fetchall:
        result = cur.fetchall()
    if commit:
        conn.commit()
        if last_id:
            result = cur.lastrowid
    cur.close()
    conn.close()
    return result


def valid_department(d):
    return d in DEPARTMENTS


def public_user(u):
    if not u:
        return None
    return {
        "id": u["id"],
        "username": u["username"],
        "first_name": u["first_name"],
        "last_name": u["last_name"],
        "role": u["role"],
        "status": u["status"],
        "department": u["department"],
        "semester": u["semester"],
    }


def current_user():
    uid = session.get("user_id")
    role = session.get("role")

    # Change "admins" to "admin"
    if role == "admin":
        admin = query("SELECT * FROM admin WHERE id=%s", (uid,), fetchone=True)
        if admin:
            admin["role"] = "admin"
        return admin

    uid = session.get("user_id")
    if not uid:
        return None
    return query("SELECT * FROM users WHERE id=%s AND is_active=1", (uid,), fetchone=True)


def login_required(role=None):
    def wrapper(fn):
        def inner(*args, **kwargs):
            user = current_user()
            if not user:
                return jsonify({"error": "Not logged in"}), 401
            if role and user["role"] != role:
                return jsonify({"error": "Forbidden"}), 403
            return fn(user, *args, **kwargs)
        inner.__name__ = fn.__name__
        return inner
    return wrapper


@app.route("/")
def index():
    return render_template("index.html")


# ===================================================
# AUTH
# ===================================================

@app.route("/api/me")
def me():
    return jsonify({"user": public_user(current_user())})


@app.route("/api/departments")
def departments():
    return jsonify({"departments": DEPARTMENTS})


@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json(force=True)
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    confirm = data.get("confirm_password") or ""
    role = data.get("role")
    first_name = (data.get("first_name") or "").strip()
    last_name = (data.get("last_name") or "").strip()
    department = data.get("department")
    semester_raw = data.get("semester")

    if not username or not password or not first_name or not last_name:
        return jsonify({"error": "First name, last name, username and password are required"}), 400
    if password != confirm:
        return jsonify({"error": "Passwords do not match"}), 400
    if role not in ("student", "instructor"):
        return jsonify({"error": "Invalid role"}), 400
    if not valid_department(department):
        return jsonify({"error": "Please select a valid department"}), 400

    semester = None
    if role == "student":
        try:
            semester = int(semester_raw)
        except (TypeError, ValueError):
            return jsonify({"error": "Please select a valid semester"}), 400
        if semester < 1 or semester > 8:
            return jsonify({"error": "Please select a valid semester"}), 400

    existing = query("SELECT id FROM users WHERE username=%s", (username,), fetchone=True)
    if existing:
        return jsonify({"error": "Username already taken"}), 400

    status = "pending" if role == "instructor" else None
    query(
        "INSERT INTO users (username, password_hash, first_name, last_name, role, status, department, semester, is_active) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,1)",
        (username, generate_password_hash(password), first_name, last_name, role, status, department, semester),
        commit=True,
    )
    msg = ("Account created. Wait for admin approval before logging in."
           if role == "instructor" else "Account created. You can now log in.")
    return jsonify({"message": msg})


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(force=True)
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    # 1. Look up user in the users table
    user = query("SELECT * FROM users WHERE username=%s", (username,), fetchone=True)
    
    if user:
        if not check_password_hash(user['password_hash'], password):
            return jsonify({"error": "Invalid username or password"}), 401
            
        if not user.get("is_active", True):
            return jsonify({"error": "This account has been deactivated. Contact the admin."}), 403
            
        if user.get("role") == "Instructor" and user.get("status") == "rejected":
            return jsonify({"error": "Your instructor account was rejected."}), 403
            
        # Log regular user in
        session["user_id"] = user["id"]
        session["role"] = user["role"]
        return jsonify({"user": public_user(user)})

    # 2. Fallback: Look up user in the dedicated admins table
    admin = query("SELECT * FROM admin WHERE username=%s", (username,), fetchone=True)
    
    if admin:
        if check_password_hash(admin["password_hash"], password):
            # Log admin in
            session["user_id"] = admin["id"]
            session["role"] = "admin"
            
            # Send back the clean admin profile dictionary
            return jsonify({
                "user": {
                    "id": admin["id"], 
                    "username": admin["username"], 
                    "role": "admin"
                }
            })
            
    # 3. If it matches neither table or checking credentials fails
    return jsonify({"error": "Invalid username or password"}), 401

  
    


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({})


# ===================================================
# ADMIN
# ===================================================

@app.route("/api/admin/stats")
@login_required("admin")
def admin_stats(user):
    pending = query("SELECT COUNT(*) c FROM users WHERE role='instructor' AND status='pending'", fetchone=True)["c"]
    instructors = query("SELECT COUNT(*) c FROM users WHERE role='instructor' AND status='approved' AND is_active=1", fetchone=True)["c"]
    students = query("SELECT COUNT(*) c FROM users WHERE role='student' AND is_active=1", fetchone=True)["c"]
    quizzes = query("SELECT COUNT(*) c FROM quizzes", fetchone=True)["c"]
    attempts = query("SELECT COUNT(*) c FROM attempts", fetchone=True)["c"]
    return jsonify({
        "pending_count": pending, "instructor_count": instructors,
        "student_count": students, "quiz_count": quizzes, "attempt_count": attempts
    })


@app.route("/api/admin/accounts")
@login_required("admin")
def admin_accounts(user):
    rows = query("""
        SELECT id, username, first_name, last_name, role, status, department, semester, is_active, created_at
        FROM users WHERE role IN ('instructor','student')
        ORDER BY created_at DESC
    """, fetchall=True)
    for r in rows:
        r["created_at"] = r["created_at"].strftime("%Y-%m-%d")
        r["is_active"] = bool(r["is_active"])
    return jsonify({"accounts": rows})


@app.route("/api/admin/instructors/<int:uid>/approve", methods=["POST"])
@login_required("admin")
def approve_instructor(user, uid):
    query("UPDATE users SET status='approved' WHERE id=%s AND role='instructor'", (uid,), commit=True)
    return jsonify({})


@app.route("/api/admin/instructors/<int:uid>/reject", methods=["POST"])
@login_required("admin")
def reject_instructor(user, uid):
    query("UPDATE users SET status='rejected' WHERE id=%s AND role='instructor'", (uid,), commit=True)
    return jsonify({})


@app.route("/api/admin/accounts/<int:uid>/toggle-active", methods=["POST"])
@login_required("admin")
def toggle_active(user, uid):
    target = query("SELECT id, is_active FROM users WHERE id=%s AND role IN ('instructor','student')", (uid,), fetchone=True)
    if not target:
        return jsonify({"error": "Account not found"}), 404
    new_status = 0 if target["is_active"] else 1
    query("UPDATE users SET is_active=%s WHERE id=%s", (new_status, uid), commit=True)
    return jsonify({"is_active": bool(new_status)})


@app.route("/api/admin/accounts/<int:uid>", methods=["DELETE"])
@login_required("admin")
def delete_account(user, uid):
    target = query("SELECT id, is_active FROM users WHERE id=%s AND role IN ('instructor','student')", (uid,), fetchone=True)
    if not target:
        return jsonify({"error": "Account not found"}), 404
    if target["is_active"]:
        return jsonify({"error": "Deactivate the account before deleting it"}), 400
    query("DELETE FROM users WHERE id=%s", (uid,), commit=True)
    return jsonify({})


@app.route("/api/admin/quizzes")
@login_required("admin")
def admin_quizzes(user):
    rows = query("""
        SELECT q.id, q.title, q.description, q.department, q.time_limit_minutes, q.passing_cutoff, q.is_default,
               u.username AS instructor_name,
               (SELECT COUNT(*) FROM questions WHERE quiz_id=q.id) AS question_count
        FROM quizzes q LEFT JOIN users u ON u.id = q.instructor_id
        ORDER BY q.created_at DESC
    """, fetchall=True)
    return jsonify({"quizzes": rows})


@app.route("/api/admin/quizzes/<int:qid>", methods=["DELETE"])
@login_required("admin")
def admin_delete_quiz(user, qid):
    query("DELETE FROM quizzes WHERE id=%s", (qid,), commit=True)
    return jsonify({})


@app.route("/api/admin/results")
@login_required("admin")
def admin_results(user):
    rows = query("""
        SELECT u.username, u.first_name, u.last_name, q.title AS quiz_title,
               a.score, a.marks_obtained, a.total_questions, a.passed,
               a.time_taken_seconds, a.taken_at
        FROM attempts a
        JOIN users u ON u.id = a.user_id
        JOIN quizzes q ON q.id = a.quiz_id
        ORDER BY a.taken_at DESC
    """, fetchall=True)
    for r in rows:
        r["taken_at"] = r["taken_at"].strftime("%Y-%m-%d %H:%M")
    return jsonify({"results": rows})


# ===================================================
# INSTRUCTOR
# ===================================================

def get_owned_quiz(user, qid):
    quiz = query("SELECT * FROM quizzes WHERE id=%s", (qid,), fetchone=True)
    if not quiz or (user["role"] == "instructor" and quiz["instructor_id"] != user["id"]):
        return None
    return quiz


@app.route("/api/instructor/quizzes")
@login_required("instructor")
def instructor_quizzes(user):
    rows = query("""
        SELECT q.id, q.title, q.description, q.department, q.time_limit_minutes, q.passing_cutoff,
               (SELECT COUNT(*) FROM questions WHERE quiz_id=q.id) AS question_count
        FROM quizzes q WHERE q.instructor_id=%s ORDER BY q.created_at DESC
    """, (user["id"],), fetchall=True)
    return jsonify({"quizzes": rows})


@app.route("/api/instructor/quizzes", methods=["POST"])
@login_required("instructor")
def create_quiz(user):
    data = request.get_json(force=True)
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "Title is required"}), 400

    timer = data.get("time_limit_minutes") or None
    timer = int(timer) if timer not in (None, "") else None

    cutoff = data.get("passing_cutoff")
    try:
        cutoff = float(cutoff) if cutoff not in (None, "") else None
    except ValueError:
        cutoff = None
    if cutoff is not None and (cutoff < 0 or cutoff > 100):
        return jsonify({"error": "Passing cutoff must be between 0 and 100"}), 400

    qid = query(
        "INSERT INTO quizzes (instructor_id, title, description, department, time_limit_minutes, passing_cutoff) "
        "VALUES (%s,%s,%s,%s,%s,%s)",
        (user["id"], title, data.get("description") or "", user["department"], timer, cutoff),
        commit=True, last_id=True
    )
    return jsonify({"quiz_id": qid})


@app.route("/api/instructor/quizzes/<int:qid>", methods=["PUT"])
@login_required("instructor")
def update_quiz(user, qid):
    quiz = get_owned_quiz(user, qid)
    if not quiz:
        return jsonify({"error": "Quiz not found"}), 404
    data = request.get_json(force=True)

    timer = data.get("time_limit_minutes") or None
    timer = int(timer) if timer not in (None, "") else None

    cutoff = data.get("passing_cutoff")
    try:
        cutoff = float(cutoff) if cutoff not in (None, "") else None
    except ValueError:
        cutoff = None
    if cutoff is not None and (cutoff < 0 or cutoff > 100):
        return jsonify({"error": "Passing cutoff must be between 0 and 100"}), 400

    query(
        "UPDATE quizzes SET title=%s, description=%s, time_limit_minutes=%s, passing_cutoff=%s WHERE id=%s",
        (data.get("title", quiz["title"]), data.get("description", quiz["description"]), timer, cutoff, qid),
        commit=True
    )
    return jsonify({})


@app.route("/api/instructor/quizzes/<int:qid>", methods=["DELETE"])
@login_required("instructor")
def delete_quiz(user, qid):
    quiz = get_owned_quiz(user, qid)
    if not quiz:
        return jsonify({"error": "Quiz not found"}), 404
    query("DELETE FROM quizzes WHERE id=%s", (qid,), commit=True)
    return jsonify({})


@app.route("/api/instructor/quizzes/<int:qid>/questions")
@login_required("instructor")
def instructor_questions(user, qid):
    quiz = get_owned_quiz(user, qid)
    if not quiz:
        return jsonify({"error": "Quiz not found"}), 404
    questions = query("SELECT * FROM questions WHERE quiz_id=%s ORDER BY id", (qid,), fetchall=True)
    return jsonify({"quiz": quiz, "questions": questions})


@app.route("/api/instructor/quizzes/<int:qid>/questions", methods=["POST"])
@login_required("instructor")
def add_question(user, qid):
    quiz = get_owned_quiz(user, qid)
    if not quiz:
        return jsonify({"error": "Quiz not found"}), 404
    d = request.get_json(force=True)
    required = ["question_text", "option_a", "option_b", "option_c", "option_d", "correct_option"]
    if not all(d.get(f) for f in required) or d["correct_option"] not in ("A", "B", "C", "D"):
        return jsonify({"error": "All fields are required and correct_option must be A-D"}), 400

    neg = d.get("negative_marks")
    try:
        neg = abs(float(neg)) if neg not in (None, "") else 0
    except (TypeError, ValueError):
        neg = 0

    query(
        "INSERT INTO questions (quiz_id, question_text, option_a, option_b, option_c, option_d, correct_option, negative_marks) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (qid, d["question_text"], d["option_a"], d["option_b"], d["option_c"], d["option_d"], d["correct_option"], neg),
        commit=True
    )
    return jsonify({})


@app.route("/api/instructor/questions/<int:qid>", methods=["DELETE"])
@login_required("instructor")
def delete_question(user, qid):
    q = query(
        "SELECT q.*, quiz.instructor_id FROM questions q JOIN quizzes quiz ON quiz.id=q.quiz_id WHERE q.id=%s",
        (qid,), fetchone=True
    )
    if not q or q["instructor_id"] != user["id"]:
        return jsonify({"error": "Question not found"}), 404
    query("DELETE FROM questions WHERE id=%s", (qid,), commit=True)
    return jsonify({})


@app.route("/api/instructor/quizzes/<int:qid>/questions/upload", methods=["POST"])
@login_required("instructor")
def upload_questions(user, qid):
    quiz = get_owned_quiz(user, qid)
    if not quiz:
        return jsonify({"error": "Quiz not found"}), 404
    file = request.files.get("csv_file")
    if not file:
        return jsonify({"error": "No file uploaded"}), 400

    stream = io.StringIO(file.stream.read().decode("utf-8"))
    reader = csv.DictReader(stream)
    required_cols = {"question_text", "option_a", "option_b", "option_c", "option_d", "correct_option"}
    if not required_cols.issubset(set(reader.fieldnames or [])):
        return jsonify({"error": "CSV is missing required columns"}), 400

    added, errors = 0, []
    for i, row in enumerate(reader, start=2):
        opt = (row.get("correct_option") or "").strip().upper()
        if opt not in ("A", "B", "C", "D") or not all((row.get(c) or "").strip() for c in required_cols):
            errors.append(f"Row {i}: invalid or incomplete")
            continue
        neg_raw = (row.get("negative_marks") or "").strip()
        try:
            neg = abs(float(neg_raw)) if neg_raw else 0
        except ValueError:
            neg = 0
        query(
            "INSERT INTO questions (quiz_id, question_text, option_a, option_b, option_c, option_d, correct_option, negative_marks) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (qid, row["question_text"], row["option_a"], row["option_b"], row["option_c"], row["option_d"], opt, neg),
            commit=True
        )
        added += 1

    return jsonify({"message": f"{added} questions added.", "errors": errors})


@app.route("/api/instructor/quizzes/<int:qid>/leaderboard")
@login_required("instructor")
def instructor_leaderboard(user, qid):
    quiz = get_owned_quiz(user, qid)
    if not quiz:
        return jsonify({"error": "Quiz not found"}), 404
    return jsonify(build_leaderboard(qid, quiz["title"]))


# ===================================================
# LEADERBOARD (shared)
# ===================================================
def build_leaderboard(qid, title):
    rows = query("""
        SELECT
            user_id,
            username,
            first_name,
            last_name,
            score,
            marks_obtained,
            total_questions,
            passed,
            time_taken_seconds,
            taken_at
        FROM (
            SELECT
                a.user_id,
                u.username,
                u.first_name,
                u.last_name,
                a.score,
                a.marks_obtained,
                a.total_questions,
                a.passed,
                a.time_taken_seconds,
                a.taken_at,
                ROW_NUMBER() OVER (
                    PARTITION BY a.user_id
                    ORDER BY a.taken_at ASC
                ) AS attempt_no
            FROM attempts a
            JOIN users u ON u.id = a.user_id
            WHERE a.quiz_id = %s
        ) ranked_attempts
        WHERE attempt_no = 1
        ORDER BY marks_obtained DESC, time_taken_seconds ASC
    """, (qid,), fetchall=True)

    for i, r in enumerate(rows, start=1):
        r["rank"] = i

        if r["taken_at"]:
            r["taken_at"] = r["taken_at"].strftime("%Y-%m-%d %H:%M")

    return {
        "quiz": {
            "title": title
        },
        "leaderboard": rows
    }
@app.route("/api/quizzes/<int:qid>/leaderboard", methods=["GET"])
def get_leaderboard(qid):

    # Get quiz information
    quiz = query("""
        SELECT id, title
        FROM quizzes
        WHERE id = %s
    """, (qid,), fetchall=True)

    # Quiz doesn't exist
    if not quiz:
        return jsonify({
            "success": False,
            "error": "Quiz not found"
        }), 404

    # Get first quiz row
    quiz = quiz[0]

    # Build leaderboard
    result = build_leaderboard(
        qid,
        quiz["title"]
    )

    return jsonify({
        "success": True,
        **result
    }), 200


# ===================================================
# STUDENT
# ===================================================

@app.route("/api/student/quizzes")
@login_required("student")
def student_quizzes(user):
    department = request.args.get("department") or user["department"]
    if not valid_department(department):
        department = user["department"]

    rows = query("""
        SELECT q.id, q.title, q.description, q.department, q.time_limit_minutes, q.passing_cutoff, q.is_default,
               (SELECT COUNT(*) FROM questions WHERE quiz_id=q.id) AS question_count,
               EXISTS(SELECT 1 FROM attempts a WHERE a.quiz_id=q.id AND a.user_id=%s) AS taken
        FROM quizzes q WHERE q.department=%s ORDER BY q.created_at DESC
    """, (user["id"], department), fetchall=True)
    for r in rows:
        r["taken"] = bool(r["taken"])
    return jsonify({"quizzes": rows, "department": department})


@app.route("/api/student/quizzes/<int:qid>")
@login_required("student")
def student_take_quiz(user, qid):
    quiz = query(
        "SELECT id, title, time_limit_minutes, passing_cutoff FROM quizzes WHERE id=%s",
        (qid,), fetchone=True
    )
    if not quiz:
        return jsonify({"error": "Quiz not found"}), 404
    questions = query(
        "SELECT id, question_text, option_a, option_b, option_c, option_d FROM questions WHERE quiz_id=%s ORDER BY id",
        (qid,), fetchall=True
    )
    return jsonify({"quiz": quiz, "questions": questions})


@app.route("/api/student/quizzes/<int:qid>/submit", methods=["POST"])
@login_required("student")
def submit_quiz(user, qid):
    data = request.get_json(force=True)
    answers = data.get("answers") or {}
    time_taken = data.get("time_taken_seconds")

    quiz = query("SELECT id, passing_cutoff FROM quizzes WHERE id=%s", (qid,), fetchone=True)
    if not quiz:
        return jsonify({"error": "Quiz not found"}), 404

    questions = query(
        "SELECT id, correct_option, negative_marks FROM questions WHERE quiz_id=%s", (qid,), fetchall=True
    )
    total = len(questions)
    score = 0
    marks = 0.0
    review = []

    for q in questions:
        selected = answers.get(str(q["id"]))
        if not selected:
            status, awarded = "skipped", 0.0
        elif selected == q["correct_option"]:
            status, awarded = "correct", 1.0
            score += 1
        else:
            status, awarded = "incorrect", -float(q["negative_marks"] or 0)
        marks += awarded
        review.append({
            "question_id": q["id"], "status": status, "selected": selected,
            "correct_option": q["correct_option"], "marks_awarded": awarded
        })

    percentage = round((marks / total) * 100, 2) if total else 0
    passed = None
    if quiz["passing_cutoff"] is not None:
        passed = percentage >= float(quiz["passing_cutoff"])

    attempt_id = query(
        "INSERT INTO attempts (user_id, quiz_id, score, marks_obtained, total_questions, passing_cutoff, passed, time_taken_seconds) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (user["id"], qid, score, marks, total, quiz["passing_cutoff"], passed, time_taken),
        commit=True, last_id=True
    )
    for r in review:
        query(
            "INSERT INTO attempt_answers (attempt_id, question_id, selected_option, is_correct, marks_awarded) "
            "VALUES (%s,%s,%s,%s,%s)",
            (attempt_id, r["question_id"], r["selected"], r["status"] == "correct", r["marks_awarded"]),
            commit=True
        )

    board = query(
        "SELECT user_id, marks_obtained, time_taken_seconds FROM attempts WHERE quiz_id=%s "
        "ORDER BY marks_obtained DESC, time_taken_seconds ASC",
        (qid,), fetchall=True
    )
    rank = next(
        (i + 1 for i, r in enumerate(board)
         if r["user_id"] == user["id"] and float(r["marks_obtained"]) == round(marks, 2)
         and r["time_taken_seconds"] == time_taken),
        None
    )

    return jsonify({
        "score": score, "total": total, "marks_obtained": round(marks, 2),
        "percentage": percentage, "passing_cutoff": quiz["passing_cutoff"], "passed": passed,
        "rank": rank, "total_participants": len(board),
        "review": [{"question_id": r["question_id"], "status": r["status"]} for r in review]
    })


@app.route("/api/student/results")
@login_required("student")
def student_results(user):
    rows = query("""
        SELECT a.quiz_id, q.title AS quiz_title, a.score, a.marks_obtained, a.total_questions,
               a.passed, a.time_taken_seconds, a.taken_at
        FROM attempts a JOIN quizzes q ON q.id = a.quiz_id
        WHERE a.user_id=%s ORDER BY a.taken_at DESC
    """, (user["id"],), fetchall=True)
    for r in rows:
        r["taken_at"] = r["taken_at"].strftime("%Y-%m-%d %H:%M")
    return jsonify({"results": rows})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
