"""Security utilities — encryption, rate limiting, CORS config."""

import hashlib
import logging
import os
import time
from collections import defaultdict

logger = logging.getLogger(__name__)

# ── Fernet encryption for auth tokens ──

_ENCRYPT_KEY = os.environ.get("MGMT_ENCRYPT_KEY", "")
_fernet = None


def _get_fernet():
    """Lazy-initialize Fernet cipher from MGMT_ENCRYPT_KEY."""
    global _fernet
    if _fernet is not None:
        return _fernet
    if not _ENCRYPT_KEY:
        logger.warning("MGMT_ENCRYPT_KEY not set — auth tokens stored in plaintext")
        return None
    try:
        from cryptography.fernet import Fernet
        # Accept either a raw Fernet key or derive one from a passphrase
        if len(_ENCRYPT_KEY) == 44 and _ENCRYPT_KEY.endswith("="):
            key = _ENCRYPT_KEY.encode()
        else:
            # Derive a Fernet-compatible key from an arbitrary passphrase
            import base64
            dk = hashlib.pbkdf2_hmac("sha256", _ENCRYPT_KEY.encode(), b"aghub-salt", 100_000)
            key = base64.urlsafe_b64encode(dk)
        _fernet = Fernet(key)
        logger.info("Token encryption enabled")
        return _fernet
    except ImportError:
        logger.warning("cryptography package not installed — tokens stored in plaintext")
        return None


def encrypt_token(plaintext: str) -> str:
    """Encrypt a token. Returns ciphertext or plaintext if encryption unavailable."""
    f = _get_fernet()
    if f is None:
        return plaintext
    return f.encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    """Decrypt a token. Returns plaintext."""
    f = _get_fernet()
    if f is None:
        return ciphertext
    try:
        return f.decrypt(ciphertext.encode()).decode()
    except Exception:
        # May be stored unencrypted (pre-migration data)
        return ciphertext


# ── Rate limiting (in-memory, per-IP) ──


class RateLimiter:
    """Simple in-memory rate limiter."""

    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str) -> bool:
        """Check if a request is allowed for the given key."""
        now = time.time()
        timestamps = self._requests[key]
        # Remove expired timestamps
        self._requests[key] = [t for t in timestamps if now - t < self.window]
        if len(self._requests[key]) >= self.max_requests:
            return False
        self._requests[key].append(now)
        return True


# Global rate limiters
auth_limiter = RateLimiter(max_requests=10, window_seconds=60)  # 10 req/min for auth
usage_limiter = RateLimiter(max_requests=60, window_seconds=60)  # 60 req/min for usage


# ── CORS config ──


def get_cors_origins() -> list[str]:
    """Get allowed CORS origins based on environment."""
    env = os.environ.get("MGMT_ENV", "development")
    if env == "production":
        domain = os.environ.get("MGMT_DOMAIN", "agenthub.cloud")
        return [
            f"https://{domain}",
            f"https://control.{domain}",
            f"https://*.{domain}",
        ]
    return ["*"]  # Development: allow all
