"""Prints the current Steam Guard code for the shared secret in $STEAM_SHARED_SECRET."""

import base64
import hashlib
import hmac
import os
import struct
import time

ALPHABET = "23456789BCDFGHJKMNPQRTVWXY"

secret = base64.b64decode(os.environ["STEAM_SHARED_SECRET"])
digest = hmac.new(secret, struct.pack(">Q", int(time.time()) // 30), hashlib.sha1).digest()
offset = digest[19] & 0x0F
value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
code = ""
for _ in range(5):
    value, i = divmod(value, len(ALPHABET))
    code += ALPHABET[i]
print(code)
