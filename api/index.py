"""
Run this once to create the first admin account.
Usage:  python create_admin.py
Admin accounts only need a username and password (no name/department/semester).
"""

import getpass
import mysql.connector
from werkzeug.security import generate_password_hash

DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "Ankit@123",
    "database": "equiz",
}


def main():
    print("=== Create Admin Account ===")
    username = input("Username: ").strip()
    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")

    if not username or not password:
        print("Username and password are required.")
        return
    if password != confirm:
        print("Passwords do not match.")
        return

    conn = mysql.connector.connect(**DB_CONFIG)
    cur = conn.cursor()

    cur.execute("SELECT id FROM admin WHERE username=%s", (username,))
    if cur.fetchone():
        print(f"Username '{username}' is already taken.")
        cur.close()
        conn.close()
        return

    cur.execute(
        "INSERT INTO admin (username, password_hash) "
        "VALUES (%s, %s)",
        (username, generate_password_hash(password)),
    )
    conn.commit()
    cur.close()
    conn.close()

    print(f"Admin account '{username}' created successfully. You can now log in.")


if __name__ == "__main__":
    main()
