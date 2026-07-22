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
import secrets
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import bcrypt
from jose import JWTError, jwt

# Any token signed with a known key is forgeable: anyone who can reach the port
# could mint {"sub": <any user id>} and drive that account. So there is NO
# hard-coded fallback. The old default was a literal committed string, which is
# exactly a published signing key.
#
# Resolution order:
#   1. SECRET_KEY from the environment  - the production path; set it explicitly,
#      and set the SAME value on every host if you ever run more than one.
#   2. a random key persisted to backend/.secret_key (gitignored) - the local
#      path. Generated once on first boot, then stable across restarts so a dev
#      is not logged out every time the server bounces. Never committed.
_PLACEHOLDER = "CHANGE-THIS-IN-PRODUCTION-USE-LONG-RANDOM-STRING"
_KEY_FILE = Path(__file__).resolve().parent / ".secret_key"


def _load_secret_key() -> str:
    env = os.getenv("SECRET_KEY")
    if env and env != _PLACEHOLDER:
        return env
    if env == _PLACEHOLDER:
        warnings.warn(
            "SECRET_KEY is set to the old placeholder value; ignoring it and using "
            "a generated key. Set a real SECRET_KEY in the environment.", stacklevel=2)
    try:
        existing = _KEY_FILE.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except FileNotFoundError:
        pass
    generated = secrets.token_hex(32)
    try:
        _KEY_FILE.write_text(generated, encoding="utf-8")
        try:                                    # best-effort lockdown; no-op on Windows
            os.chmod(_KEY_FILE, 0o600)
        except (OSError, NotImplementedError):
            pass
    except OSError as e:
        warnings.warn(
            f"Could not persist a signing key to {_KEY_FILE} ({e}); using an "
            "in-memory key. Tokens will not survive a restart. Set SECRET_KEY to fix.",
            stacklevel=2)
    return generated


SECRET_KEY = _load_secret_key()
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
