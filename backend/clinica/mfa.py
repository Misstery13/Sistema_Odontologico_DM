"""TOTP (RFC 6238): códigos de 6 dígitos cada 30 s, compatibles con Google Authenticator, Authy, Microsoft Authenticator."""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

import segno

STEP_SECONDS = 30


def new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def code_at(secret, step):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    return f"{(struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 1_000_000:06d}"


def verify(secret, code, last_step, now=None):
    """Devuelve el paso válido (para impedir reutilizar el mismo código) o None. Tolera ±1 paso de desfase de reloj."""
    code = str(code).strip()
    current = int((now or time.time()) // STEP_SECONDS)
    for step in (current - 1, current, current + 1):
        if step > last_step and hmac.compare_digest(code_at(secret, step), code):
            return step
    return None


def provisioning_qr(secret, username, issuer):
    uri = f"otpauth://totp/{quote(issuer)}:{quote(username)}?secret={secret}&issuer={quote(issuer)}&digits=6&period={STEP_SECONDS}"
    return segno.make(uri, error="m").svg_data_uri(scale=5, dark="#1a1a1a")
