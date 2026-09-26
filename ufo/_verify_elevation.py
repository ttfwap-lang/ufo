"""Report the integrity level of whoever executes this.

Used to verify the permanent hidden-elevation daemon: it must report SYSTEM
(and the machine account LENOVO$), because anything less means RULE 7 is
quietly not delivering elevation.
"""
import ctypes
import json
import os
import sys

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "_verify_elevation.json")


def integrity_level() -> str:
    """Map the process token's integrity SID to a human label."""
    advapi = ctypes.windll.advapi32
    kernel32 = ctypes.windll.kernel32
    # argtypes matter: without them ctypes marshals the HANDLE/token pointers
    # as 32-bit ints on x64 and OpenProcessToken fails spuriously.
    advapi.OpenProcessToken.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                        ctypes.POINTER(ctypes.c_void_p)]
    advapi.OpenProcessToken.restype = ctypes.c_long
    advapi.GetTokenInformation.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                           ctypes.c_void_p, ctypes.c_uint32,
                                           ctypes.POINTER(ctypes.c_uint32)]
    advapi.GetTokenInformation.restype = ctypes.c_long

    token = ctypes.c_void_p()
    if not advapi.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008,
                                   ctypes.byref(token)):
        return "OpenProcessToken failed"

    # TokenIntegrityLevel = 25
    size = ctypes.c_uint32(0)
    advapi.GetTokenInformation(token, 25, None, 0, ctypes.byref(size))
    if size.value == 0:
        return "GetTokenInformation (size) failed"
    buf = ctypes.create_string_buffer(size.value)
    if not advapi.GetTokenInformation(token, 25, buf, size, ctypes.byref(size)):
        return "GetTokenInformation failed"

    # TOKEN_MANDATORY_LABEL is { SID_AND_ATTRIBUTES Label; } and
    # SID_AND_ATTRIBUTES is { PSID Sid; DWORD Attributes; }. The buffer holds a
    # POINTER to the SID label at offset 0, so the label must be dereferenced
    # through it. Casting the buffer directly reads the pointer's own bytes and
    # produces a garbage RID - which is how a real SYSTEM token gets reported
    # as UNPROTECTED.
    class SID(ctypes.Structure):
        _fields_ = [("Revision", ctypes.c_ubyte),
                    ("SubAuthorityCount", ctypes.c_ubyte),
                    ("IdentifierAuthority", ctypes.c_ubyte * 6),
                    ("SubAuthority", ctypes.c_uint32 * 8)]

    class SID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", ctypes.c_uint32)]

    class TOKEN_MANDATORY_LABEL(ctypes.Structure):
        _fields_ = [("Label", SID_AND_ATTRIBUTES)]

    label = ctypes.cast(buf, ctypes.POINTER(TOKEN_MANDATORY_LABEL)).contents
    if not label.Label.Sid:
        return "TOKEN_MANDATORY_LABEL carried a null SID"
    sid = ctypes.cast(label.Label.Sid, ctypes.POINTER(SID)).contents
    rid = sid.SubAuthority[0] if sid.SubAuthorityCount else 0
    kernel32.CloseHandle(token)

    return {
        0x1000: "LOW",
        0x2000: "MEDIUM (NOT elevated)",
        0x3000: "HIGH (elevated admin)",
        0x4000: "SYSTEM",
    }.get(rid, f"UNKNOWN (RID 0x{rid:04x})")


def main() -> None:
    info = {
        "integrity": integrity_level(),
        "is_user_an_admin": bool(ctypes.windll.shell32.IsUserAnAdmin()),
        "user": os.environ.get("USERNAME"),
        "domain": os.environ.get("USERDOMAIN"),
        "executable": sys.executable,
        "pid": os.getpid(),
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2)
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
