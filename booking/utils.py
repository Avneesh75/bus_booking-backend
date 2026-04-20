import time
import os
import uuid as _uuid_lib


def uuid7():
    """
    Generate a UUID version 7 (time-ordered, draft-ietf-uuidrev-rfc4122bis).

    Layout:
      bits  0-47  : Unix timestamp in milliseconds  (48 bits)
      bits 48-51  : version = 0111                  (4 bits)
      bits 52-63  : random_a                         (12 bits)
      bits 64-65  : variant = 10                     (2 bits)
      bits 66-127 : random_b                         (62 bits)
    """
    ms   = int(time.time() * 1000)
    rand = int.from_bytes(os.urandom(10), 'big')

    hi = (ms << 16) | (0x7 << 12) | ((rand >> 50) & 0xFFF)
    lo = (0x2 << 62) | (rand & 0x3FFFFFFFFFFFFFFF)

    return _uuid_lib.UUID(bytes=hi.to_bytes(8, 'big') + lo.to_bytes(8, 'big'))
