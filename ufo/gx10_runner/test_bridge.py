import urllib.request
import urllib.error

BASES = ["http://100.113.176.84:9301", "http://100.81.31.74:9301",
         "http://192.168.4.103:9301"]
tok = open("/home/flak3dd/ufo-tg-runner-bootstrap/ufo_bridge_token.txt").read().strip()

for base in BASES:
    try:
        with urllib.request.urlopen(base + "/health", timeout=6) as r:
            print(f"{base} health OK:", r.read().decode()[:80])
    except Exception as e:
        print(f"{base} health FAIL: {type(e).__name__} {e}")
        continue
    try:
        req = urllib.request.Request(base + "/result/probe",
                                     headers={"Authorization": "Bearer " + tok})
        with urllib.request.urlopen(req, timeout=6) as r:
            print(f"{base} auth OK:", r.read().decode()[:80])
    except urllib.error.HTTPError as e:
        print(f"{base} auth -> HTTP {e.code} (expected: 404 = auth OK)")
    except Exception as e:
        print(f"{base} auth FAIL: {type(e).__name__} {e}")
