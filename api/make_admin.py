"""Create (or promote) an administrator account.

    MLFL_ADMIN_EMAIL=admin@example.com MLFL_ADMIN_PASSWORD=... python -m api.make_admin

The password is read from the environment so it never lands in the repo or in
shell history as an argument. Re-running resets the password and the role.
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import select

from api.db import SessionLocal
from api.models import User, UserRole
from api.security import hash_password


def main() -> None:
    email = os.environ.get("MLFL_ADMIN_EMAIL", "").strip().lower()
    password = os.environ.get("MLFL_ADMIN_PASSWORD", "")
    if not email or len(password) < 10:
        sys.exit("Set MLFL_ADMIN_EMAIL and MLFL_ADMIN_PASSWORD (>= 10 chars).")

    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(
                email=email,
                password_hash=hash_password(password),
                full_name="Administrator",
                role=UserRole.ADMIN,
            )
            db.add(user)
        else:
            user.password_hash = hash_password(password)
            user.role = UserRole.ADMIN
        db.commit()
        print(f"[make_admin] {email} is now an administrator")
    finally:
        db.close()


if __name__ == "__main__":
    main()
