import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import jwt

from app.core.config import settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

hashed = hash_password("Correct-Horse-9")
print("hash starts with $argon2id:", hashed.startswith("$argon2id$"))
print("right password verifies:", verify_password("Correct-Horse-9", hashed))
print("wrong password rejected:", not verify_password("wrong", hashed))

uid = uuid.uuid4()
token = create_access_token(uid)
print("valid token decodes:", decode_access_token(token) == uid)
print("tampered token rejected:", decode_access_token(token + "x") is None)

expired = jwt.encode(
    {"sub": str(uid), "type": "access", "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
    settings.jwt_secret_key,
    algorithm=settings.jwt_algorithm,
)
print("expired token rejected:", decode_access_token(expired) is None)