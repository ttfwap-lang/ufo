import json
import sys
import urllib.request

tok = open(r"C:\Users\lnxzf\Desktop\projects\ufo\ufo\ufo_bridge_token.txt").read().strip()
req = urllib.request.Request(
    "http://127.0.0.1:9301/result/horo-final-12",
    headers={"Authorization": "Bearer " + tok})
d = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
print("status:", d["status"], "| collector_rc:", (d.get("result") or {}).get("collector_rc"))
rep = (d.get("result") or {}).get("report") or {}
print("signs:", len(rep))
for k, v in rep.items():
    r = v.get("ratings") or {}
    print(f"  {k:12} Love {r.get('Love','?')}  Health {r.get('Health','?')}  "
          f"Career {r.get('Career','?')}  Lunar {r.get('Lunar','?')}")
