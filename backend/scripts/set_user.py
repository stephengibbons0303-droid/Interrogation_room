"""Create a local account, or reset its password if it already exists.

There is no password-reset flow in the app yet, so this is the way to get back
into a local account. Local development only.

    python backend/scripts/set_user.py <email> <password> [--role admin]

Passwords are bcrypt-hashed the same way registration does it - the plaintext
is never stored.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from db import SessionLocal, User, init_db          # noqa: E402
from security import get_password_hash              # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("email")
    ap.add_argument("password")
    ap.add_argument("--role", default="learner")
    args = ap.parse_args()

    if len(args.password) < 8:
        print("Password must be at least 8 characters (registration enforces this).")
        return 1

    init_db()
    db = SessionLocal()
    try:
        email = args.email.lower().strip()
        user = db.query(User).filter(User.email == email).first()
        if user:
            user.hashed_password = get_password_hash(args.password)
            user.role = args.role
            action = "password reset"
        else:
            user = User(email=email,
                        hashed_password=get_password_hash(args.password),
                        role=args.role)
            db.add(user)
            action = "created"
        db.commit()
        print(f"{action}: {email} (role={args.role})")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
