#!/usr/bin/env python3
"""
Bountywork Automation Server
- Serves the site on localhost:3456
- Adds 2 new bounties from the pool every 4 hours
- Checks submitted Twitter/X proof links via oEmbed (no API key needed)
- Auto-marks bounties as complete when proof is verified
"""

import sys
import json
import os
import random
import threading
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler

# Force UTF-8 output so emojis don't crash on Windows consoles
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ─── CONFIG ───────────────────────────────────────────────────────────────────
BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
# On Railway, store data in /data volume so it persists across deploys
DATA_DIR      = os.environ.get("DATA_DIR", BASE_DIR)
DATA_FILE     = os.path.join(DATA_DIR, "bounties.json")
PORT          = int(os.environ.get("PORT", 3456))
CYCLE_HOURS   = 0.5       # how often to add bounties + check proofs (every 30 min)
NEW_PER_CYCLE = 2         # new bounties added each cycle

# ─── BOUNTY POOL ──────────────────────────────────────────────────────────────
# These get randomly added 2-at-a-time every 4 hours.
POOL = [
    # IRL Challenges
    {"cat":"irl","title":"Wear a $BOUNTYWORK Sign in Public",
     "desc":"Print '$BOUNTYWORK' on a sign and walk a busy public area for 30+ minutes. Film the reactions.",
     "reward":250000,"diff":"medium"},
    {"cat":"irl","title":"Do 100 Pushups on Video",
     "desc":"100 consecutive pushups on camera — no breaks over 5 seconds. Shout '$BOUNTYWORK' when done.",
     "reward":100000,"diff":"medium"},
    {"cat":"irl","title":"Cold Shower for 5 Minutes",
     "desc":"Cold water only, 5 straight minutes on camera. Shout '$BOUNTYWORK' at the end.",
     "reward":120000,"diff":"medium"},
    {"cat":"irl","title":"Eat a Full Raw Onion",
     "desc":"Eat an entire raw onion on video, no cutting into pieces. Say the coin name when done.",
     "reward":200000,"diff":"hard"},
    {"cat":"irl","title":"Ice Bath Challenge",
     "desc":"Sit in an ice bath for 2 full minutes on camera. Tag $BOUNTYWORK in the post.",
     "reward":300000,"diff":"hard"},
    {"cat":"irl","title":"Eat a Spoonful of Hot Sauce",
     "desc":"Down a full tablespoon of the hottest hot sauce you can find on camera. No chaser for 30 seconds.",
     "reward":150000,"diff":"medium"},
    {"cat":"irl","title":"Run a Mile Under 9 Minutes",
     "desc":"Film a timed mile run. Under 9:00 qualifies. Show the timer at start and end.",
     "reward":100000,"diff":"medium"},
    {"cat":"irl","title":"Get a $BOUNTYWORK Temp Tattoo",
     "desc":"Get a $BOUNTYWORK temporary tattoo and film yourself showing it to a stranger in public.",
     "reward":80000,"diff":"easy"},
    {"cat":"irl","title":"Dye Your Hair a Wild Color",
     "desc":"Dye your hair any non-natural color. Post a before/after. Must stay for 24+ hours.",
     "reward":400000,"diff":"hard"},
    {"cat":"irl","title":"Hold an Ice Cube for 2 Minutes",
     "desc":"Hold an ice cube in your bare hand for 2 straight minutes on camera. No gloves, no cuts.",
     "reward":80000,"diff":"easy"},
    {"cat":"irl","title":"Eat a Whole Lemon Without Reacting",
     "desc":"Eat an entire lemon — peel and all — on video without reacting. Stone cold face the whole time.",
     "reward":175000,"diff":"medium"},
    {"cat":"irl","title":"Do 50 Burpees Non-Stop",
     "desc":"50 burpees without stopping, full range of motion each rep. Say $BOUNTYWORK at the end.",
     "reward":120000,"diff":"medium"},
    {"cat":"irl","title":"Eat Dog Food",
     "desc":"Eat a spoonful of dog food on camera and say '$BOUNTYWORK to the moon'. No animals harmed.",
     "reward":180000,"diff":"medium"},
    {"cat":"irl","title":"Jump in a Lake/River Fully Clothed",
     "desc":"Jump into any natural body of water with all your clothes on. Film it, post it, tag $BOUNTYWORK.",
     "reward":220000,"diff":"medium"},
    {"cat":"irl","title":"Sleep in Your Car for One Night",
     "desc":"Sleep in your car for a full night on camera (or time-lapse). Morning video required as proof.",
     "reward":300000,"diff":"hard"},
    # Social
    {"cat":"social","title":"Make a $BOUNTYWORK Rap",
     "desc":"Write and perform a rap about $BOUNTYWORK. At least 16 bars. Post on X and TikTok.",
     "reward":200000,"diff":"medium"},
    {"cat":"social","title":"Get 100 Likes on a $BOUNTYWORK Post",
     "desc":"Post about $BOUNTYWORK on X and hit 100 organic likes. Screenshot the milestone.",
     "reward":150000,"diff":"medium"},
    {"cat":"social","title":"Post on 5 Different Platforms in One Day",
     "desc":"Post $BOUNTYWORK content on X, TikTok, Reddit, Instagram, and YouTube in the same day.",
     "reward":250000,"diff":"hard"},
    {"cat":"social","title":"Get a Crypto Influencer to Mention $BOUNTYWORK",
     "desc":"Get any crypto influencer with 5K+ followers to organically mention $BOUNTYWORK. Link required.",
     "reward":500000,"diff":"hard"},
    {"cat":"social","title":"Write a $BOUNTYWORK Poem",
     "desc":"Write an original poem about $BOUNTYWORK on X. At least 8 lines. Be creative.",
     "reward":50000,"diff":"easy"},
    {"cat":"social","title":"Make a Viral Meme Template",
     "desc":"Create a reusable meme template featuring $BOUNTYWORK branding. Must be posted publicly.",
     "reward":75000,"diff":"easy"},
    {"cat":"social","title":"Host a $BOUNTYWORK X Space",
     "desc":"Host a Twitter/X Spaces about $BOUNTYWORK with at least 20 listeners. Share the replay.",
     "reward":400000,"diff":"hard"},
    # Design
    {"cat":"design","title":"Animated Spinning Coin GIF",
     "desc":"Create a smooth looping animated GIF of the $BOUNTYWORK coin spinning. Post link publicly.",
     "reward":100000,"diff":"medium"},
    {"cat":"design","title":"Phone Wallpaper Pack (3 designs)",
     "desc":"Design 3 unique phone wallpapers (1080x1920) featuring $BOUNTYWORK. Share as public album.",
     "reward":80000,"diff":"easy"},
    {"cat":"design","title":"Merch Concept Design",
     "desc":"Design a $BOUNTYWORK T-shirt, hoodie, or cap concept with full mockup. Could become real merch!",
     "reward":200000,"diff":"medium"},
    {"cat":"design","title":"Animated TikTok Intro (3-5 sec)",
     "desc":"Create a high-quality 3-5 second animated intro clip for $BOUNTYWORK TikTok content.",
     "reward":175000,"diff":"medium"},
    # Community
    {"cat":"community","title":"Translate the Buy Guide to Another Language",
     "desc":"Translate the full How to Buy guide into any non-English language. Post publicly.",
     "reward":75000,"diff":"easy"},
    {"cat":"community","title":"Start a $BOUNTYWORK Telegram Group",
     "desc":"Create and grow a $BOUNTYWORK Telegram group to 50+ members. Share the link + member count.",
     "reward":300000,"diff":"hard"},
    # Dev
    {"cat":"dev","title":"Build a $BOUNTYWORK Discord Bot",
     "desc":"Build and deploy a Discord bot showing $BOUNTYWORK price, buy alerts, and a !buy command. Open source.",
     "reward":600000,"diff":"hard"},
    {"cat":"dev","title":"Build a Wallet Portfolio Tracker",
     "desc":"Build a mini web app: enter wallet, see $BOUNTYWORK holdings and P&L. Host it publicly.",
     "reward":500000,"diff":"hard"},
    {"cat":"dev","title":"Submit $BOUNTYWORK to DEXTools",
     "desc":"Get $BOUNTYWORK officially listed and verified on DEXTools with logo and metadata.",
     "reward":800000,"diff":"hard"},
    {"cat":"dev","title":"Create a $BOUNTYWORK Auto-Buy Script",
     "desc":"Write a public open-source script that auto-buys $BOUNTYWORK via Solana web3.js. GitHub required.",
     "reward":750000,"diff":"hard"},
]

# Keywords that must appear in the tweet for automatic approval
VERIFY_KEYWORDS = ["bountywork", "j4x1em", "$bounty", "bounty work"]


# ─── DATA HELPERS ─────────────────────────────────────────────────────────────
def load():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save(data):
    data["lastUpdated"] = datetime.now(timezone.utc).isoformat()
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ─── TWITTER VERIFICATION ─────────────────────────────────────────────────────
def verify_tweet(url: str) -> tuple[bool, str]:
    """
    Use Twitter's public oEmbed API (no auth needed) to fetch tweet content.
    Returns (verified: bool, reason: str)
    """
    if not url:
        return False, "No proof URL"

    # Normalize twitter.com → x.com
    url = url.strip().replace("twitter.com", "x.com")
    if "x.com" not in url and "twitter.com" not in url:
        return False, "URL is not a Twitter/X link"

    oembed_url = (
        "https://publish.twitter.com/oembed"
        f"?url={urllib.parse.quote(url, safe='')}"
        "&omit_script=true"
    )

    try:
        req = urllib.request.Request(
            oembed_url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; BountyworkBot/1.0)"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            html = data.get("html", "").lower()
            author = data.get("author_name", "")

            # Check for $BOUNTYWORK mention in tweet
            if any(kw in html for kw in VERIFY_KEYWORDS):
                return True, f"✅ Tweet verified — mentions $BOUNTYWORK (by {author})"
            else:
                return False, f"Tweet exists but doesn't mention $BOUNTYWORK (by {author})"

    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False, "Tweet not found (deleted or invalid URL)"
        return False, f"HTTP {e.code} from Twitter oEmbed"
    except Exception as e:
        return False, f"Check failed: {e}"


# ─── AUTOMATION CYCLE ─────────────────────────────────────────────────────────
def run_cycle(label="scheduled"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'='*55}")
    print(f"[{ts}] 🔄 Bounty cycle ({label})")
    print(f"{'='*55}")

    data = load()
    changed = False

    # ── 1. Check pending submissions ──────────────────────────
    pending = [b for b in data["bounties"] if b.get("pendingHunter") and not b.get("completed")]
    print(f"  Pending proofs to check: {len(pending)}")

    for bounty in pending:
        hunter = bounty["pendingHunter"]
        proof  = hunter.get("proof", "")
        print(f"\n  🔍 '{bounty['title']}'")
        print(f"     Hunter : {hunter.get('name','?')}")
        print(f"     Proof  : {proof}")

        ok, reason = verify_tweet(proof)
        print(f"     Result : {reason}")

        if ok:
            bounty["completed"]    = True
            bounty["hunter"]       = hunter
            bounty["pendingHunter"] = None
            changed = True
            print(f"     → Marked COMPLETE ✅")
        else:
            print(f"     → Still pending ⏳")

    # ── 2. Add new bounties from pool ─────────────────────────
    existing_titles = {b["title"] for b in data["bounties"]}
    available = [b for b in POOL if b["title"] not in existing_titles]

    if not available:
        # Pool exhausted — reset and reshuffle
        available = list(POOL)
        print(f"\n  Pool exhausted — reshuffling all {len(POOL)} bounties")

    random.shuffle(available)
    new_bounties = available[:NEW_PER_CYCLE]
    max_id = max((b["id"] for b in data["bounties"]), default=0)

    for i, template in enumerate(new_bounties):
        entry = {
            **template,
            "id": max_id + i + 1,
            "completed": False,
            "hunter": None,
            "pendingHunter": None,
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
        data["bounties"].append(entry)
        print(f"\n  ➕ New bounty: [{entry['cat'].upper()}] {entry['title']} — {entry['reward']//1000}K $B")
        changed = True

    if changed:
        save(data)

    total  = len(data["bounties"])
    open_  = sum(1 for b in data["bounties"] if not b["completed"] and not b.get("pendingHunter"))
    pend_  = sum(1 for b in data["bounties"] if b.get("pendingHunter"))
    done_  = sum(1 for b in data["bounties"] if b["completed"])
    print(f"\n  📊 Board: {total} total | {open_} open | {pend_} pending | {done_} done")
    print(f"  Next cycle in {CYCLE_HOURS}h\n")


def scheduler_loop():
    """Background thread: run a cycle every CYCLE_HOURS."""
    while True:
        time.sleep(CYCLE_HOURS * 3600)
        run_cycle("scheduled")


# ─── HTTP SERVER ──────────────────────────────────────────────────────────────
MIME = {
    ".html": "text/html; charset=utf-8",
    ".css":  "text/css",
    ".js":   "application/javascript",
    ".json": "application/json",
    ".png":  "image/png",
    ".ico":  "image/x-icon",
    ".svg":  "image/svg+xml",
}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # suppress default logs

    # ── helpers ──────────────────────────────────────────────
    def cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def json_response(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.cors()
        self.end_headers()
        self.wfile.write(body)

    def file_response(self, filepath):
        try:
            with open(filepath, "rb") as f:
                body = f.read()
            ext = os.path.splitext(filepath)[1].lower()
            ctype = MIME.get(ext, "application/octet-stream")
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.cors()
            self.end_headers()
            self.wfile.write(body)
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()

    def read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    # ── routes ───────────────────────────────────────────────
    def do_OPTIONS(self):
        self.send_response(200)
        self.cors()
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/api/bounties":
            self.json_response(200, load())

        elif path in ("/", "/index.html", ""):
            self.file_response(os.path.join(BASE_DIR, "index.html"))

        else:
            filename = path.lstrip("/")
            self.file_response(os.path.join(BASE_DIR, filename))

    def do_POST(self):
        path = self.path.split("?")[0]

        # ── Submit a claim ──────────────────────────────────
        if path == "/api/submit":
            body       = self.read_body()
            bounty_id  = body.get("id")
            hunter     = body.get("hunter", {})
            data       = load()

            for bounty in data["bounties"]:
                if bounty["id"] == bounty_id:
                    if bounty.get("completed"):
                        self.json_response(400, {"ok": False, "error": "Bounty already completed"})
                        return
                    if bounty.get("pendingHunter"):
                        self.json_response(400, {"ok": False, "error": "A claim is already under review"})
                        return

                    bounty["pendingHunter"] = hunter
                    save(data)

                    # Kick off an immediate Twitter check in the background
                    threading.Thread(target=run_cycle, args=("instant check",), daemon=True).start()

                    self.json_response(200, {
                        "ok": True,
                        "message": "Claim submitted! Running Twitter verification now — check back in a minute."
                    })
                    return

            self.json_response(404, {"ok": False, "error": "Bounty not found"})

        # ── Admin: force a cycle now ────────────────────────
        elif path == "/api/cycle":
            threading.Thread(target=run_cycle, args=("manual trigger",), daemon=True).start()
            self.json_response(200, {"ok": True, "message": "Cycle triggered"})

        else:
            self.json_response(404, {"ok": False, "error": "Unknown endpoint"})


# ─── ENTRY POINT ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 55)
    print("🎯  BOUNTYWORK AUTOMATION SERVER")
    print("=" * 55)
    print(f"  Data file : {DATA_FILE}")
    print(f"  Port      : {PORT}")
    print(f"  Cycle     : every {CYCLE_HOURS} hours")
    print(f"  Pool size : {len(POOL)} bounties")
    print("=" * 55)

    # Init bounties.json — copy seed file from repo if not in data dir yet
    if not os.path.exists(DATA_FILE):
        src = os.path.join(BASE_DIR, "bounties.json")
        if os.path.exists(src) and src != DATA_FILE:
            import shutil
            shutil.copy(src, DATA_FILE)
            print(f"Copied seed bounties.json -> {DATA_FILE}")
        else:
            save({"version": 2, "lastUpdated": datetime.now(timezone.utc).isoformat(), "bounties": []})

    # Run an immediate startup cycle
    run_cycle("startup")

    # Launch background scheduler
    t = threading.Thread(target=scheduler_loop, daemon=True)
    t.start()

    # Start HTTP server
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"\n✅  Server running → http://localhost:{PORT}")
    print(f"📋  Bounty board  → http://localhost:{PORT}/bounties.html")
    print(f"\n  Press Ctrl+C to stop.\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑  Server stopped.")
