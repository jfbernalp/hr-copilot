"""
auth.py
-------
Autenticación local para HR Copilot (laboratorio).

- Hash de contraseñas con hashlib.pbkdf2_hmac (stdlib — sin dependencias nuevas).
- Rate-limit en memoria: 5 intentos fallidos → bloqueo de 5 minutos por usuario.
- La tabla `users` la crea/puebla setup/seed_users.py.
"""

import os
import time
import hmac
import hashlib

_ITERATIONS  = 60_000
MAX_ATTEMPTS = 5
LOCK_SECONDS = 300

# username → (intentos_fallidos, bloqueado_hasta_ts)
_attempts: dict = {}


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITERATIONS)
    return digest.hex(), salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITERATIONS)
    return hmac.compare_digest(digest.hex(), password_hash)


def check_login(conn, username: str, password: str):
    """Valida credenciales contra la tabla users.

    Devuelve (ok, user_dict | None, mensaje_error | None).
    user_dict: {username, role, full_name}.
    """
    username = (username or "").strip().lower()
    if not username or not password:
        return False, None, "Ingresa usuario y contraseña."

    now = time.time()
    fails, locked_until = _attempts.get(username, (0, 0.0))
    if locked_until > now:
        mins = int((locked_until - now) / 60) + 1
        return False, None, f"Cuenta bloqueada por intentos fallidos. Intenta de nuevo en {mins} min."

    row = conn.execute(
        "SELECT password_hash, salt, role, full_name, active FROM users WHERE username = ?",
        (username,),
    ).fetchone()

    if row and row[4] and verify_password(password, row[0], row[1]):
        _attempts.pop(username, None)
        return True, {"username": username, "role": row[2], "full_name": row[3]}, None

    fails += 1
    if fails >= MAX_ATTEMPTS:
        _attempts[username] = (fails, now + LOCK_SECONDS)
        return False, None, "Demasiados intentos fallidos. Cuenta bloqueada por 5 minutos."
    _attempts[username] = (fails, 0.0)
    return False, None, f"Usuario o contraseña incorrectos ({MAX_ATTEMPTS - fails} intentos restantes)."
