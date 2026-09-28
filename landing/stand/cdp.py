"""Drive one headless Chrome over CDP: cdp.py start <profile> | shot <url> <out.png> [w h scale] [js-before] | eval <js> | stop"""
import base64
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import websockets.sync.client as ws

import os

S = Path(os.environ.get("MENSARIUM_STAND", "/tmp/mensarium-stand"))
CH = os.environ.get("CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
PORT = int(os.environ.get("CDP_PORT", "9223"))
PIDF = S / "chrome.pid"


def start(profile):
    (S / "chrome" / profile).mkdir(parents=True, exist_ok=True)
    for f in (S / "chrome" / profile).glob("Singleton*"):
        f.unlink()
    p = subprocess.Popen([CH, "--headless=new", f"--user-data-dir={S / 'chrome' / profile}", "--no-first-run", "--hide-scrollbars",
                          f"--remote-debugging-port={PORT}", "--window-size=1440,900", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    PIDF.write_text(str(p.pid))
    for _ in range(40):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=1)
            break
        except Exception:
            time.sleep(0.25)
    print("chrome", p.pid)


def page():
    tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
    tab = next(t for t in tabs if t["type"] == "page")
    return ws.connect(tab["webSocketDebuggerUrl"], max_size=64 * 1024 * 1024)


class Cdp:
    def __init__(self):
        self.c = page()
        self.n = 0

    def call(self, method, **params):
        self.n += 1
        self.c.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            m = json.loads(self.c.recv())
            if m.get("id") == self.n:
                if "error" in m:
                    raise RuntimeError(m["error"])
                return m.get("result", {})

    def eval(self, js):
        r = self.call("Runtime.evaluate", expression=js, returnByValue=True, awaitPromise=True)
        return r.get("result", {}).get("value")


def shot(url, out, w=1440, h=900, scale=2, js="", wait=3.0):
    d = Cdp()
    d.call("Emulation.setDeviceMetricsOverride", width=int(w), height=int(h), deviceScaleFactor=float(scale), mobile=int(w) < 700)
    d.call("Page.navigate", url=url)
    time.sleep(wait)
    if js:
        d.eval(js)
        time.sleep(1.2)
    print("at", d.eval("location.href"), "|", (d.eval("document.body.innerText") or "")[:80].replace("\n", " "))
    data = d.call("Page.captureScreenshot", format="png")["data"]
    Path(out).write_bytes(base64.b64decode(data))
    print("saved", out)


def stop():
    if PIDF.exists():
        subprocess.run(["kill", PIDF.read_text().strip()])
        PIDF.unlink()


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "start":
        start(sys.argv[2])
    elif cmd == "shot":
        a = sys.argv[2:]
        shot(a[0], a[1], *(a[2:5] if len(a) > 4 else ()), js=(a[5] if len(a) > 5 else ""))
    elif cmd == "snap":
        # screenshot the current page as it is, after an optional script and a pause in ms
        d = Cdp()
        if len(sys.argv) > 3 and sys.argv[3]:
            d.eval(sys.argv[3])
        time.sleep(float(sys.argv[4]) / 1000 if len(sys.argv) > 4 else 0)
        Path(sys.argv[2]).write_bytes(base64.b64decode(d.call("Page.captureScreenshot", format="png")["data"]))
        print("saved", sys.argv[2])
    elif cmd == "eval":
        d = Cdp()
        if len(sys.argv) > 3:
            d.call("Emulation.setDeviceMetricsOverride", width=int(sys.argv[3]), height=int(sys.argv[4]), deviceScaleFactor=1, mobile=int(sys.argv[3]) < 700)
            time.sleep(0.8)
        print(d.eval(sys.argv[2]))
    elif cmd == "stop":
        stop()
