"""Vérification des identifiants de connexion."""
from __future__ import annotations

import hashlib
import hmac
import secrets as token_tools
import sys

ITERATIONS = 240_000
DEFAULT_USERNAME = "youssouf"
DEFAULT_PASSWORD_HASH = "7a8c029f75b888af65346ee1d7ceee2b$196fb28d2bf3d5dde33ee2964587f7ab659083b88d17972230a12d0fb59fbdcc"


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or token_tools.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), ITERATIONS)
    return f"{salt}${digest.hex()}"


def verify_credentials(
    username: str,
    password: str,
    expected_username: str = DEFAULT_USERNAME,
    expected_hash: str = DEFAULT_PASSWORD_HASH,
) -> bool:
    salt = expected_hash.split("$", 1)[0]
    password_ok = hmac.compare_digest(hash_password(password, salt), expected_hash)
    username_ok = hmac.compare_digest(username.strip().encode(), expected_username.encode())
    return password_ok and username_ok


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit('Usage : python auth.py "nouveau_mot_de_passe"')
    print(hash_password(sys.argv[1]))
