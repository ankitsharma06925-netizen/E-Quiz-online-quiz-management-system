import csv
import io
from functools import wraps

from flask import Flask, render_template, request, session, jsonify
import mysql.connector
from mysql.connector import Error
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
app = Flask(__name__, template_folder='../templates')
app.secret_key = 'Ankit1234567'

# ---------- Database Configuration ----------
DB_CONFIG = {
    'host': 'sql12.freesqldatabase.com',
    'port':3306,
    'user': 'sql12836971',
    'password': 'eDtPclwG6p',
    'database': 'sql12836971'
}


def get_db_connection():
    try:
        return mysql.connector.connect(**DB_CONFIG)
    except Error as e:
        print(f"Database connection error: {e}")
        return None


def db_error_response():
    return jsonify({'error': 'Database connection failed. Check server MySQL configuration.'}), 500


# ---------- Auth decorators (return JSON errors instead of redirects) ----------
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Please log in to continue.'}), 401
        return f(*args, **kwargs)
    return decorated


def role_required(*roles):
    def wrapper(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if session.get('role') not in roles:
                return jsonify({'error': 'You do not have access to this resource.'}), 403
            return f(*args, **kwargs)
        return decorated
    return wrapper


def instructor_approved_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'instructor':
            return jsonify({'error': 'You do not have access to this resource.'}), 403
        if session.get('status') != 'approved':
            return jsonify({'error': 'Your instructor account is not approved yet.', 'status': session.get('status')}), 403
        return f(*args, **kwargs)
    return decorated


# ---------- Leaderboard helper ----------
def compute_leaderboard(quiz_id):
    """Best attempt per user for a quiz. Rank order: score desc, time asc, earliest attempt."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('''
        SELECT r.*, u.username
        FROM results r
        JOIN users u ON r.user_id = u.id
        WHERE r.quiz_id = %s
        ORDER BY r.taken_at ASC
    ''', (quiz_id,))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    best_per_user = {}
    for row in rows:
        uid = row['user_id']
        current = best_per_user.get(uid)
        if current is None:
            best_per_user[uid] = row
            continue
        better = row['score'] > current['score']
        tie_same_score = row['score'] == current['score']
        row_time = row['time_taken_seconds'] if row['time_taken_seconds'] is not None else float('inf')
        cur_time = current['time_taken_seconds'] if current['time_taken_seconds'] is not None else float('inf')
        if better or (tie_same_score and row_time < cur_time):
            best_per_user[uid] = row

    leaderboard = list(best_per_user.values())
    leaderboard.sort(key=lambda r: (
        -r['score'],
        r['time_taken_seconds'] if r['time_taken_seconds'] is not None else float('inf'),
        r['taken_at']
    ))
    result = []
    for idx, row in enumerate(leaderboard, start=1):
        result.append({
            'rank': idx,
            'user_id': row['user_id'],
            'username': row['username'],
            'score': row['score'],
            'total_questions': row['total_questions'],
            'time_taken_seconds': row['time_taken_seconds'],
            'taken_at': row['taken_at'].strftime('%b %d, %Y %I:%M %p') if row['taken_at'] else None
        })
    return result


# ============================================================
#  PAGE ROUTE (serves the single-page app shell)
# ============================================================
@app.route('/')
def index():
    return render_template('index.html')


# ============================================================
#  AUTH API
# ============================================================
@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.get_json(force=True)
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    confirm = data.get('confirm_password') or ''
    role = data.get('role', 'student')

    if role not in ('student', 'instructor'):
        role = 'student'
    if not username or not password:
        return jsonify({'error': 'Username and password are required.'}), 400
    if password != confirm:
        return jsonify({'error': 'Passwords do not match.'}), 400

    conn = get_db_connection()
    if not conn:
        return db_error_response()
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM users WHERE username = %s', (username,))
    if cursor.fetchone():
        cursor.close()
        conn.close()
        return jsonify({'error': 'Username already exists.'}), 400

    status = 'pending' if role == 'instructor' else 'approved'
    hashed_pw = generate_password_hash(password)
    cursor.execute(
        'INSERT INTO users (username, password, role, status) VALUES (%s, %s, %s, %s)',
        (username, hashed_pw, role, status)
    )
    conn.commit()
    cursor.close()
    conn.close()

    if role == 'instructor':
        return jsonify({'message': 'Registered! Your instructor account needs admin approval before you can log in.'})
    return jsonify({'message': 'Registration successful! Please log in.'})


@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json(force=True)
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''

    conn = get_db_connection()
    if not conn:
        return db_error_response()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT * FROM users WHERE username = %s', (username,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()

    if not user or not check_password_hash(user['password'], password):
        return jsonify({'error': 'Invalid username or password.'}), 401

    if user['role'] == 'instructor' and user['status'] == 'rejected':
        return jsonify({'error': 'Your instructor registration was rejected. Contact the admin.'}), 403

    session['user_id'] = user['id']
    session['username'] = user['username']
    session['role'] = user['role']
    session['status'] = user['status']

    return jsonify({'user': {
        'id': user['id'], 'username': user['username'],
        'role': user['role'], 'status': user['status']
    }})


@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({'message': 'Logged out.'})


@app.route('/api/me')
def api_me():
    if 'user_id' not in session:
        return jsonify({'user': None})
    return jsonify({'user': {
        'id': session['user_id'], 'username': session['username'],
        'role': session['role'], 'status': session.get('status')
    }})


# ============================================================
#  ADMIN API
# ============================================================
@app.route('/api/admin/stats')
@login_required
@role_required('admin')
def admin_stats():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT COUNT(*) AS c FROM users WHERE role='instructor' AND status='pending'")
    pending_count = cursor.fetchone()['c']
    cursor.execute("SELECT COUNT(*) AS c FROM users WHERE role='student'")
    student_count = cursor.fetchone()['c']
    cursor.execute("SELECT COUNT(*) AS c FROM users WHERE role='instructor' AND status='approved'")
    instructor_count = cursor.fetchone()['c']
    cursor.execute("SELECT COUNT(*) AS c FROM quizzes")
    quiz_count = cursor.fetchone()['c']
    cursor.execute("SELECT COUNT(*) AS c FROM results")
    attempt_count = cursor.fetchone()['c']
    cursor.close()
    conn.close()
    return jsonify({
        'pending_count': pending_count, 'student_count': student_count,
        'instructor_count': instructor_count, 'quiz_count': quiz_count,
        'attempt_count': attempt_count
    })


@app.route('/api/admin/instructors')
@login_required
@role_required('admin')
def admin_instructors():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('''
        SELECT u.id, u.username, u.status, u.created_at, COUNT(q.id) AS quiz_count
        FROM users u
        LEFT JOIN quizzes q ON q.created_by = u.id
        WHERE u.role = 'instructor'
        GROUP BY u.id
        ORDER BY FIELD(u.status, 'pending', 'approved', 'rejected'), u.created_at DESC
    ''')
    instructors = cursor.fetchall()
    for i in instructors:
        i['created_at'] = i['created_at'].strftime('%b %d, %Y') if i['created_at'] else ''
    cursor.close()
    conn.close()
    return jsonify({'instructors': instructors})


@app.route('/api/admin/instructors/<int:user_id>/approve', methods=['POST'])
@login_required
@role_required('admin')
def approve_instructor(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET status='approved' WHERE id=%s AND role='instructor'", (user_id,))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({'message': 'Instructor approved.'})


@app.route('/api/admin/instructors/<int:user_id>/reject', methods=['POST'])
@login_required
@role_required('admin')
def reject_instructor(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET status='rejected' WHERE id=%s AND role='instructor'", (user_id,))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({'message': 'Instructor rejected.'})


@app.route('/api/admin/quizzes')
@login_required
@role_required('admin')
def admin_quizzes():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('''
        SELECT q.*, COUNT(qs.id) AS question_count, u.username AS instructor_name
        FROM quizzes q
        LEFT JOIN questions qs ON qs.quiz_id = q.id
        LEFT JOIN users u ON u.id = q.created_by
        GROUP BY q.id
        ORDER BY q.is_default DESC, q.created_at DESC
    ''')
    quizzes = cursor.fetchall()
    for q in quizzes:
        q['created_at'] = q['created_at'].strftime('%b %d, %Y') if q['created_at'] else ''
    cursor.close()
    conn.close()
    return jsonify({'quizzes': quizzes})


@app.route('/api/admin/quizzes/<int:quiz_id>', methods=['DELETE'])
@login_required
@role_required('admin')
def admin_delete_quiz(quiz_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM quizzes WHERE id = %s', (quiz_id,))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({'message': 'Quiz deleted.'})


@app.route('/api/admin/results')
@login_required
@role_required('admin')
def admin_results():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('''
        SELECT r.*, u.username, q.title AS quiz_title
        FROM results r
        JOIN users u ON r.user_id = u.id
        JOIN quizzes q ON r.quiz_id = q.id
        ORDER BY r.taken_at DESC
    ''')
    results = cursor.fetchall()
    for r in results:
        r['taken_at'] = r['taken_at'].strftime('%b %d, %Y %I:%M %p') if r['taken_at'] else ''
    cursor.close()
    conn.close()
    return jsonify({'results': results})


# ============================================================
#  INSTRUCTOR API (approved instructors only)
# ============================================================
def _get_owned_quiz_or_none(quiz_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT * FROM quizzes WHERE id = %s AND created_by = %s', (quiz_id, session['user_id']))
    quiz = cursor.fetchone()
    cursor.close()
    conn.close()
    return quiz


@app.route('/api/instructor/quizzes')
@login_required
@instructor_approved_required
def instructor_quizzes():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('''
        SELECT q.*, COUNT(qs.id) AS question_count
        FROM quizzes q
        LEFT JOIN questions qs ON qs.quiz_id = q.id
        WHERE q.created_by = %s
        GROUP BY q.id
        ORDER BY q.created_at DESC
    ''', (session['user_id'],))
    quizzes = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify({'quizzes': quizzes})


@app.route('/api/instructor/quizzes', methods=['POST'])
@login_required
@instructor_approved_required
def add_quiz():
    data = request.get_json(force=True)
    title = (data.get('title') or '').strip()
    description = (data.get('description') or '').strip()
    time_limit_minutes = data.get('time_limit_minutes')
    time_limit_minutes = int(time_limit_minutes) if str(time_limit_minutes).isdigit() and int(time_limit_minutes) > 0 else None

    if not title:
        return jsonify({'error': 'Quiz title is required.'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO quizzes (title, description, created_by, is_default, time_limit_minutes) VALUES (%s, %s, %s, FALSE, %s)',
        (title, description, session['user_id'], time_limit_minutes)
    )
    conn.commit()
    new_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return jsonify({'message': 'Quiz created.', 'quiz_id': new_id})


@app.route('/api/instructor/quizzes/<int:quiz_id>', methods=['PUT'])
@login_required
@instructor_approved_required
def edit_quiz(quiz_id):
    if not _get_owned_quiz_or_none(quiz_id):
        return jsonify({'error': 'Quiz not found.'}), 404

    data = request.get_json(force=True)
    title = (data.get('title') or '').strip()
    description = (data.get('description') or '').strip()
    time_limit_minutes = data.get('time_limit_minutes')
    time_limit_minutes = int(time_limit_minutes) if str(time_limit_minutes).isdigit() and int(time_limit_minutes) > 0 else None

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE quizzes SET title=%s, description=%s, time_limit_minutes=%s WHERE id=%s',
        (title, description, time_limit_minutes, quiz_id)
    )
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({'message': 'Quiz updated.'})


@app.route('/api/instructor/quizzes/<int:quiz_id>', methods=['DELETE'])
@login_required
@instructor_approved_required
def delete_quiz(quiz_id):
    if not _get_owned_quiz_or_none(quiz_id):
        return jsonify({'error': 'Quiz not found.'}), 404
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM quizzes WHERE id = %s', (quiz_id,))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({'message': 'Quiz deleted.'})


@app.route('/api/instructor/quizzes/<int:quiz_id>/questions')
@login_required
@instructor_approved_required
def manage_questions(quiz_id):
    quiz = _get_owned_quiz_or_none(quiz_id)
    if not quiz:
        return jsonify({'error': 'Quiz not found.'}), 404
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT * FROM questions WHERE quiz_id = %s', (quiz_id,))
    questions = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify({'quiz': quiz, 'questions': questions})


@app.route('/api/instructor/quizzes/<int:quiz_id>/questions', methods=['POST'])
@login_required
@instructor_approved_required
def add_question(quiz_id):
    if not _get_owned_quiz_or_none(quiz_id):
        return jsonify({'error': 'Quiz not found.'}), 404

    data = request.get_json(force=True)
    fields = ['question_text', 'option_a', 'option_b', 'option_c', 'option_d']
    values = [(data.get(f) or '').strip() for f in fields]
    correct_option = (data.get('correct_option') or '').strip().upper()

    if not all(values) or correct_option not in ('A', 'B', 'C', 'D'):
        return jsonify({'error': 'All fields are required and correct_option must be A-D.'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO questions (quiz_id, question_text, option_a, option_b, option_c, option_d, correct_option)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    ''', (quiz_id, *values, correct_option))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({'message': 'Question added.'})


@app.route('/api/instructor/quizzes/<int:quiz_id>/questions/upload', methods=['POST'])
@login_required
@instructor_approved_required
def upload_questions_csv(quiz_id):
    if not _get_owned_quiz_or_none(quiz_id):
        return jsonify({'error': 'Quiz not found.'}), 404

    file = request.files.get('csv_file')
    if not file or file.filename == '':
        return jsonify({'error': 'Please choose a CSV file to upload.'}), 400

    filename = secure_filename(file.filename)
    if not filename.lower().endswith('.csv'):
        return jsonify({'error': 'Only .csv files are supported.'}), 400

    try:
        stream = io.StringIO(file.stream.read().decode('utf-8-sig'), newline=None)
        reader = csv.DictReader(stream)
        required_cols = {'question_text', 'option_a', 'option_b', 'option_c', 'option_d', 'correct_option'}
        if not reader.fieldnames or not required_cols.issubset(set(h.strip() for h in reader.fieldnames)):
            return jsonify({'error': f'CSV must contain headers: {", ".join(sorted(required_cols))}'}), 400

        rows_to_insert = []
        errors = []
        for i, row in enumerate(reader, start=2):
            q_text = (row.get('question_text') or '').strip()
            a = (row.get('option_a') or '').strip()
            b = (row.get('option_b') or '').strip()
            c = (row.get('option_c') or '').strip()
            d = (row.get('option_d') or '').strip()
            correct = (row.get('correct_option') or '').strip().upper()

            if not all([q_text, a, b, c, d]):
                errors.append(f'Row {i}: missing a value.')
                continue
            if correct not in ('A', 'B', 'C', 'D'):
                errors.append(f'Row {i}: correct_option must be A-D (got "{correct}").')
                continue
            rows_to_insert.append((quiz_id, q_text, a, b, c, d, correct))

        if rows_to_insert:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.executemany('''
                INSERT INTO questions (quiz_id, question_text, option_a, option_b, option_c, option_d, correct_option)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            ''', rows_to_insert)
            conn.commit()
            cursor.close()
            conn.close()

        return jsonify({
            'message': f'Imported {len(rows_to_insert)} question(s).',
            'imported': len(rows_to_insert),
            'errors': errors
        })
    except UnicodeDecodeError:
        return jsonify({'error': 'Could not read the file. Save it as UTF-8 CSV and try again.'}), 400
    except Exception as e:
        return jsonify({'error': f'Failed to process CSV: {e}'}), 400


@app.route('/api/instructor/questions/<int:question_id>', methods=['DELETE'])
@login_required
@instructor_approved_required
def delete_question(question_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('''
        SELECT qs.quiz_id FROM questions qs
        JOIN quizzes q ON q.id = qs.quiz_id
        WHERE qs.id = %s AND q.created_by = %s
    ''', (question_id, session['user_id']))
    row = cursor.fetchone()
    if not row:
        cursor.close()
        conn.close()
        return jsonify({'error': 'Question not found.'}), 404

    cursor2 = conn.cursor()
    cursor2.execute('DELETE FROM questions WHERE id = %s', (question_id,))
    conn.commit()
    cursor.close()
    cursor2.close()
    conn.close()
    return jsonify({'message': 'Question removed.'})


@app.route('/api/instructor/quizzes/<int:quiz_id>/leaderboard')
@login_required
@instructor_approved_required
def instructor_leaderboard(quiz_id):
    if not _get_owned_quiz_or_none(quiz_id):
        return jsonify({'error': 'Quiz not found.'}), 404
    return jsonify({'leaderboard': compute_leaderboard(quiz_id)})


# ============================================================
#  STUDENT API
# ============================================================
@app.route('/api/student/quizzes')
@login_required
@role_required('student')
def student_quizzes():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('''
        SELECT q.*, COUNT(qs.id) AS question_count, u.username AS instructor_name
        FROM quizzes q
        LEFT JOIN questions qs ON qs.quiz_id = q.id
        LEFT JOIN users u ON u.id = q.created_by
        GROUP BY q.id
        HAVING question_count > 0
        ORDER BY q.is_default DESC, q.created_at DESC
    ''')
    quizzes = cursor.fetchall()
    cursor.execute('SELECT quiz_id FROM results WHERE user_id = %s', (session['user_id'],))
    taken = {row['quiz_id'] for row in cursor.fetchall()}
    for q in quizzes:
        q['taken'] = q['id'] in taken
    cursor.close()
    conn.close()
    return jsonify({'quizzes': quizzes})


@app.route('/api/student/quizzes/<int:quiz_id>')
@login_required
@role_required('student')
def get_quiz_for_taking(quiz_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT id, title, description, time_limit_minutes FROM quizzes WHERE id = %s', (quiz_id,))
    quiz = cursor.fetchone()
    cursor.execute('SELECT id, question_text, option_a, option_b, option_c, option_d FROM questions WHERE quiz_id = %s', (quiz_id,))
    questions = cursor.fetchall()  # correct_option intentionally excluded
    cursor.close()
    conn.close()

    if not quiz or not questions:
        return jsonify({'error': 'This quiz is not available.'}), 404

    return jsonify({'quiz': quiz, 'questions': questions})


@app.route('/api/student/quizzes/<int:quiz_id>/submit', methods=['POST'])
@login_required
@role_required('student')
def submit_quiz(quiz_id):
    data = request.get_json(force=True)
    answers = data.get('answers', {})  # {question_id (str): "A"/"B"/"C"/"D"}
    time_taken_seconds = data.get('time_taken_seconds')
    time_taken_seconds = int(time_taken_seconds) if str(time_taken_seconds).isdigit() else None

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT id, correct_option FROM questions WHERE quiz_id = %s', (quiz_id,))
    questions = cursor.fetchall()

    if not questions:
        cursor.close()
        conn.close()
        return jsonify({'error': 'This quiz is not available.'}), 404

    score = 0
    for q in questions:
        submitted = answers.get(str(q['id']))
        if submitted == q['correct_option']:
            score += 1

    cursor2 = conn.cursor()
    cursor2.execute(
        'INSERT INTO results (user_id, quiz_id, score, total_questions, time_taken_seconds) VALUES (%s, %s, %s, %s, %s)',
        (session['user_id'], quiz_id, score, len(questions), time_taken_seconds)
    )
    conn.commit()
    cursor.close()
    cursor2.close()
    conn.close()

    leaderboard = compute_leaderboard(quiz_id)
    my_rank = next((row['rank'] for row in leaderboard if row['user_id'] == session['user_id']), None)

    return jsonify({
        'score': score,
        'total': len(questions),
        'percentage': round((score / len(questions)) * 100, 2),
        'rank': my_rank,
        'total_participants': len(leaderboard)
    })


@app.route('/api/student/results')
@login_required
@role_required('student')
def my_results():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('''
        SELECT r.*, q.title AS quiz_title
        FROM results r
        JOIN quizzes q ON r.quiz_id = q.id
        WHERE r.user_id = %s
        ORDER BY r.taken_at DESC
    ''', (session['user_id'],))
    results = cursor.fetchall()
    for r in results:
        r['taken_at'] = r['taken_at'].strftime('%b %d, %Y %I:%M %p') if r['taken_at'] else ''
    cursor.close()
    conn.close()
    return jsonify({'results': results})


# ============================================================
#  SHARED: leaderboard viewable by any logged-in user
# ============================================================
@app.route('/api/quizzes/<int:quiz_id>/leaderboard')
@login_required
def shared_leaderboard(quiz_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT id, title FROM quizzes WHERE id = %s', (quiz_id,))
    quiz = cursor.fetchone()
    cursor.close()
    conn.close()
    if not quiz:
        return jsonify({'error': 'Quiz not found.'}), 404
    return jsonify({'quiz': quiz, 'leaderboard': compute_leaderboard(quiz_id)})


if __name__ == '__main__':
    app.run(debug=True)
