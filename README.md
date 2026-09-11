# QuizMaster — Online Quiz Management System (Admin / Instructor / Student)

A full-stack quiz platform built with **Flask**, **MySQL**, **HTML**, and **CSS**.

## Roles & Workflow

**Admin**
- The only role that can approve or reject instructor sign-ups
- Views system-wide stats, all quizzes, and all results
- Can delete any quiz (including the default question bank)
- Created via a one-time script (`create_admin.py`), not the public sign-up form

**Instructor**
- Registers through the public sign-up page, but the account starts as **pending**
- Cannot log in to build quizzes until an admin approves the account (rejected accounts are blocked at login with a message)
- Once approved: create quizzes, set an optional **timer** (minutes), and add questions either
  - **manually**, one at a time, or
  - **in bulk via CSV upload** (template provided — see `sample_questions.csv`)
- Can view a **leaderboard** for each of their own quizzes

**Student**
- Registers and can log in immediately (no approval needed)
- Sees every available quiz: the built-in **default Computer Science MCQ bank** plus any quiz published by an approved instructor
- Takes a quiz (with a live countdown if the instructor set a timer — auto-submits at zero)
- Gets an instant score and their **rank** among everyone else who has taken that quiz
- Can view the full leaderboard and their personal result history at any time

## Tech Stack
- **Backend:** Python 3 + Flask
- **Database:** MySQL (via `mysql-connector-python`)
- **Frontend:** Jinja2 templates + plain HTML/CSS + a little vanilla JS for the countdown timer
- **Auth:** Flask sessions + hashed passwords (`werkzeug.security`)

## Project Structure
```
quiz_management/
├── app.py                     # Flask app: routes, DB logic, leaderboard ranking
├── create_admin.py            # One-time CLI script to create the first admin account
├── schema.sql                 # MySQL schema + seeded default CS quiz (15 MCQs)
├── sample_questions.csv       # Example file in the format instructors should upload
├── requirements.txt
├── static/
│   └── style.css
└── templates/
    ├── base.html
    ├── index.html / login.html / register.html / pending_approval.html
    ├── admin_dashboard.html / admin_instructors.html / admin_quizzes.html / admin_results.html
    ├── instructor_dashboard.html / add_quiz.html / edit_quiz.html
    ├── manage_questions.html / add_question.html / upload_csv.html
    ├── student_dashboard.html / take_quiz.html / quiz_result.html / my_results.html
    └── leaderboard.html        # shared by instructor / student / admin views
```

## Setup

### 1. Create the database and seed the default quiz bank
```bash
mysql -u root -p < schema.sql
```
This creates all 4 tables (`users`, `quizzes`, `questions`, `results`) and inserts the built-in **"Computer Science Fundamentals"** quiz with 15 questions and a 15-minute timer, so students have something to try immediately.

### 2. Install dependencies
```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure database credentials
Edit `DB_CONFIG` near the top of **both** `app.py` and `create_admin.py`:
```python
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'your_mysql_password',   # <-- change this
    'database': 'quiz_management'
}
```
Also change `app.secret_key` in `app.py` to a random, private string before deploying anywhere.

### 4. Create your admin account
```bash
python create_admin.py
```
You'll be prompted for a username and password. This is intentionally kept out of the public registration form so random visitors can't grant themselves admin rights.

### 5. Run the app
```bash
python app.py
```
Visit **http://127.0.0.1:5000**.

### 6. Try the full workflow
1. **Log in as admin** (the account you just created).
2. Open a second browser/incognito window → **Sign Up** → register an **Instructor** account. Notice you can't log in yet — it's pending.
3. Back in the admin window, go to **Instructors** and click **Approve**.
4. Log in as the instructor → **+ New Quiz** → give it a title, description, and optional timer → add a few questions manually, or go to **Upload CSV** and use `sample_questions.csv` as a template.
5. Sign up a **Student** account (no approval needed) → log in → the student sees both the default CS quiz and the instructor's new quiz.
6. Take a quiz → see your score and rank instantly → check the **Leaderboard** to see everyone else's results.

## How ranking works
Each attempt is stored, but the leaderboard shows each student's **best attempt** per quiz: highest score first, then fastest completion time as a tiebreaker, then earliest submission. This is computed in the Flask app (not raw SQL), so it works on any MySQL version without needing window functions.

## Notes & Possible Next Steps
- Passwords are hashed with `werkzeug.security`; never stored in plain text.
- CSV upload validates headers and each row, reporting how many questions were imported and listing any skipped rows with a reason.
- Session stores the instructor's approval status at login time — if an admin approves/revokes access while the instructor is already logged in, they'll need to log out and back in to see the change take effect (a nice enhancement would be checking status fresh on every request).
- To harden this for production: move `DB_CONFIG` and `secret_key` into environment variables, add CSRF protection (`Flask-WTF`), limit students to one attempt if that's a rule you want to enforce, and add pagination once result tables grow large.
