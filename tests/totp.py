"""Código MFA vigente de los usuarios demo (secreto fijo de `manage.py seed`), o de cualquier secreto dado.

Uso:  python tests/totp.py [SECRETO]
"""
import base64
import hashlib
import hmac
import struct
import sys
import time

DEMO_MFA_SECRET = "ODONTODMDEMOMFA2"


def totp(secret, at=None):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", int((at or time.time()) // 30)), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    return f"{(struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 1_000_000:06d}"


if __name__ == "__main__":
    secret = sys.argv[1] if len(sys.argv) > 1 else DEMO_MFA_SECRET
    print(f"{totp(secret)}  (vence en {30 - int(time.time()) % 30} s)")
