"""Add a hashed local test account; print its password once."""
import hashlib
import json
import os
import secrets
import sys
from pathlib import Path

path = Path(__file__).parent / ".env.local"
username = sys.argv[1] if len(sys.argv) > 1 else "persona-test"
lines = path.read_text().splitlines() if path.exists() else [
    f"SESSION_SECRET={secrets.token_urlsafe(48)}",
    "DATABASE_URL=postgresql://app:app@localhost:5432/app",
    "FRONTEND_ORIGIN=http://localhost:3000",
]
values = dict(line.split("=", 1) for line in lines if "=" in line and not line.startswith("#"))
accounts = json.loads(values.get("TEST_ACCOUNTS_JSON", "{}").strip("'"))
if values.get("TEST_USERNAME") and values.get("TEST_PASSWORD_HASH"):
    accounts.setdefault(values["TEST_USERNAME"], values["TEST_PASSWORD_HASH"])
if username in accounts:
    raise SystemExit(f"Account {username} already exists")
password = secrets.token_urlsafe(12)
salt = secrets.token_bytes(16)
rounds = 600_000
hashed = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, rounds)
accounts[username] = f"pbkdf2_sha256${rounds}${salt.hex()}${hashed.hex()}"
lines = [line for line in lines if not line.startswith(("TEST_USERNAME=", "TEST_PASSWORD_HASH=", "TEST_ACCOUNTS_JSON="))]
path.write_text("TEST_ACCOUNTS_JSON=" + json.dumps(accounts, separators=(",", ":")) + "\n" + "\n".join(lines) + "\n")
os.chmod(path, 0o600)
print(f"Username: {username}\nPassword: {password}")
