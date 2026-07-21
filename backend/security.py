"""Password hashing and JWT token management.

Deliberately mirrors SAIF's app/auth/security.py - same function signatures,
same claim shape ({"sub", "email", "role"} plus "exp" and "type"), same HS256
default. When the SimDeck handshake is built, the token-exchange endpoint is
then the only new piece rather than a parallel auth model.

Two intentional differences:

  * SECRET_KEY is this app's own, not SAIF's. Sharing one would make a
    SAIF-issued token work here for free, but it would also mean a leak in
    either app compromises both. Separate keys keep the blast radius contained.

  * bcrypt is used directly rather than through passlib. passlib 1.7.4 reads
    bcrypt.__about__.__version__, which bcrypt >= 4.1 removed - hence SAIF's
    bcrypt==4.1.3 pin. Going direct avoids the pin (chromadb here needs bcrypt
    5.x) and still produces standard $2b$ hashes, so hashes remain verifiable
    by SAIF's passlib and vice versa.
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from jose import JWTError, jwt

SECRET_KEY = os.getenv("SECRET_KEY", "CHANGE-THIS-IN-PRODUCTION-USE-LONG-RANDOM-STRING")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"),
                              hashed_password.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def get_password_hash(password: str) -> str:
    """Generate password hash."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token."""
    to_encode = data.copy()
    delta = expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({
        "exp": datetime.now(timezone.utc).replace(tzinfo=None) + delta,
        "type": "access",
    })
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(data: dict) -> str:
    """Create JWT refresh token."""
    to_encode = data.copy()
    to_encode.update({
        "exp": datetime.now(timezone.utc).replace(tzinfo=None)
               + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        "type": "refresh",
    })
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """Decode and validate JWT token."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None
