"""
One-time helper to create an admin account.
Admins are NOT created through the public /register page (by design,
so random visitors can't grant themselves admin rights).

Usage:
    python create_admin.py
"""
import getpass
import sys
import mysql.connector
from werkzeug.security import generate_password_hash

# Keep this in sync with DB_CONFIG in app.py
DB_CONFIG = {
    'host': 'sql12.freesqldatabase.com',
    'port':3306,
    'user': 'sql12836971',
    'password': 'eDtPclwG6p',
    'database': 'sql12836971'
}


def main():
    username = input("Admin username: ").strip()
    password = getpass.getpass("Admin password: ")
    confirm = getpass.getpass("Confirm password: ")

    if not username or not password:
        print("Username and password are required.")
        sys.exit(1)
    if password != confirm:
        print("Passwords do not match.")
        sys.exit(1)

    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
    if cursor.fetchone():
        print(f"Username '{username}' already exists.")
        cursor.close()
        conn.close()
        sys.exit(1)

    hashed = generate_password_hash(password)
    cursor.execute(
        "INSERT INTO users (username, password, role, status) VALUES (%s, %s, 'admin', 'approved')",
        (username, hashed)
    )
    conn.commit()
    cursor.close()
    conn.close()
    print(f"Admin account '{username}' created successfully. You can now log in.")


if __name__ == '__main__':
    main()
