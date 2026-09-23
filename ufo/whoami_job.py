"""Report the identity + integrity level + session the job runs under."""
import ctypes, os
from ctypes import wintypes

print("cwd:", os.getcwd())
try:
    print("whoami:", os.popen("whoami").read().strip())
except Exception as e:
    print("whoami failed:", e)

sid = wintypes.DWORD()
ctypes.windll.kernel32.GetCurrentProcessId()
advapi = ctypes.windll.advapi32
kernel = ctypes.windll.kernel32

# Token info
hToken = wintypes.HANDLE()
if advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(hToken)):
    # TokenElevation (20)
    elev = wintypes.DWORD()
    n = wintypes.DWORD()
    advapi.GetTokenInformation(hToken, 20, ctypes.byref(elev), ctypes.sizeof(elev), ctypes.byref(n))
    print("elevated:", bool(elev.value))
    # TokenIntegrityLevel (25)
    buf = ctypes.create_string_buffer(1024)
    if advapi.GetTokenInformation(hToken, 25, buf, 1024, ctypes.byref(n)):
        # SID: revision(1) subauthcount(1) authority(6) subauths...
        p = ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))
        count = p[1]
        sid_str = f"S-{p[0]}-{p[2]}"
        for i in range(count):
            v = int.from_bytes(bytes(p[8 + i * 4: 12 + i * 4]), "little")
            sid_str += f"-{v}"
        print("integrity SID:", sid_str)
    # TokenUser
    if advapi.GetTokenInformation(hToken, 1, buf, 1024, ctypes.byref(n)):
        p = ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))
        count = p[1]
        sub = int.from_bytes(bytes(p[8:12]), "little")
        print("user SID: S-1-5-21-...-%d (subauth last=%d)" % (sub, sub))
else:
    print("OpenProcessToken failed")

# Session id
sid = wintypes.DWORD()
ctypes.windll.kernel32.ProcessIdToSessionId(kernel.GetCurrentProcessId(), ctypes.byref(sid))
print("session id:", sid.value)

# Window station / desktop
h_ws = ctypes.windll.user32.GetProcessWindowStation()
h_dk = ctypes.windll.user32.GetThreadDesktop(kernel.GetCurrentThreadId())
def obj_name(h):
    b = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetUserObjectInformationW(h, 2, b, 512, ctypes.byref(wintypes.DWORD()))
    return b.value
print("window station:", obj_name(h_ws), "desktop:", obj_name(h_dk))