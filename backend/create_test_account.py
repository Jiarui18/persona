"""Run once to create local hashed test-account configuration."""
import hashlib
import os
import secrets
from pathlib import Path

path = Path(__file__).parent / ".env.local"
if path.exists():
    raise SystemExit(f"{path} already exists; refusing to replace the test account")
username = "persona-test"
password = secrets.token_urlsafe(12)
salt = secrets.token_bytes(16)
rounds = 600_000
hashed = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, rounds)
secret = secrets.token_urlsafe(48)
path.write_text(
    f"TEST_USERNAME={username}\n"
    f"TEST_PASSWORD_HASH=pbkdf2_sha256${rounds}${salt.hex()}${hashed.hex()}\n"
    f"SESSION_SECRET={secret}\n"
    "DATABASE_URL=postgresql://app:app@localhost:5432/app\n"
    "FRONTEND_ORIGIN=http://localhost:3000\n"
)
os.chmod(path, 0o600)
print(f"Created {path}\nUsername: {username}\nPassword: {password}")
