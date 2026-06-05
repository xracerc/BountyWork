#!/usr/bin/env python3
"""
Bountywork Cards Server
- Generates Rare cards every 20 min, Epic every 30 min, Legendary every 75 min
- Pull rates: Legendary 5%, Epic 25%, Rare 45%, Uncommon 20%, Common 5%
- 40-pull limit per user then 30-minute cooldown
- User accounts (username only)
- Public flex wall
"""
import sys, json, os, random, threading, time, hashlib
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.environ.get("DATA_DIR", BASE_DIR)
USERS_FILE = os.path.join(DATA_DIR, "users.json")
POOL_FILE  = os.path.join(DATA_DIR, "pool.json")
CHAT_FILE  = os.path.join(DATA_DIR, "chat.json")
PORT       = int(os.environ.get("PORT", 3457))

MAX_PULLS    = 40
COOLDOWN_SEC = 30 * 60     # 30 minutes
RARE_SEC     = 20 * 60     # new rare every 20 min
EPIC_SEC     = 30 * 60     # new epic every 30 min
LEG_SEC      = 75 * 60     # new legendary every 75 min

# ── Pull weights ──────────────────────────────────────────────────────────────
# Roll 0-100; cumulative thresholds:
#   LEGENDARY < 0.2  (0.2%)
#   EPIC      < 10   (9.8%)
#   RARE      < 50   (40%)
#   UNCOMMON  < 85   (35%)
#   COMMON    < 100  (15%)
PULL_TIERS = [
    ("LEGENDARY", 0.2),
    ("EPIC",      10.0),
    ("RARE",      50.0),
    ("UNCOMMON",  85.0),
    ("COMMON",    100.0),
]

# ── Card templates ────────────────────────────────────────────────────────────
TEMPLATES = {
  "LEGENDARY": [
    {"bounty":"The Tattoo Saint",    "emoji":"💉","desc":'"Got $BOUNTYWORK permanently tattooed. Forever in the hunt."',              "reward":"2M $B"},
    {"bounty":"The Sky Diver",       "emoji":"🪂","desc":'"Skydived with $BOUNTYWORK written across their suit. Absolute legend."',   "reward":"1.5M $B"},
    {"bounty":"The Fire Walker",     "emoji":"🔥","desc":'"Walked barefoot on hot coals for $BOUNTYWORK. Zero hesitation."',          "reward":"1.2M $B"},
    {"bounty":"The Rainbow Mane",    "emoji":"🌈","desc":'"Dyed all their hair 7 colours for $BOUNTYWORK. No regrets."',              "reward":"900K $B"},
    {"bounty":"The Bald Sacrifice",  "emoji":"🪒","desc":'"Shaved it all off on camera. No wig. No mercy."',                          "reward":"500K $B","proof":"https://x.com/ayushquantt/status/2062585750206525537"},
    {"bounty":"The Brow Eraser",     "emoji":"😶","desc":'"Both eyebrows. Gone. A true soldier of the hunt."',                        "reward":"400K $B","proof":"https://x.com/ayushquantt/status/2062662989589746140"},
  ],
  "EPIC": [
    {"bounty":"The Toilet Dive",     "emoji":"🚽","desc":'"Full head submerge, toilet and all. Absolute menace energy."',            "reward":"350K $B","proof":"https://x.com/ayushquantt/status/2062687785811587393"},
    {"bounty":"The Spicy Legend",    "emoji":"🌶️","desc":'"Ate the nuclear ramen challenge on camera. Cried. Finished anyway."',     "reward":"450K $B"},
    {"bounty":"The Mud Runner",      "emoji":"🏃","desc":'"Ran a full mile through mud in $BOUNTYWORK gear. Undefeated."',           "reward":"400K $B"},
    {"bounty":"The Fast King",       "emoji":"⏱️","desc":'"Fasted 24 straight hours for $BOUNTYWORK. Pure dedication."',            "reward":"380K $B"},
    {"bounty":"The Karaoke Degen",   "emoji":"🎤","desc":'"Sang a crypto rap in public. People clapped. Legend unlocked."',          "reward":"360K $B"},
    {"bounty":"The Rooftop Screamer","emoji":"📣","desc":'"Screamed $BOUNTYWORK from a rooftop 100 times. Neighbours heard it."',    "reward":"340K $B"},
    {"bounty":"The Cold Plunge",     "emoji":"❄️","desc":'"Jumped into a frozen lake for $BOUNTYWORK. Got out grinning."',           "reward":"400K $B"},
    {"bounty":"The Ice Bath King",   "emoji":"🧊","desc":'"Two minutes in an ice bath. Didn\'t flinch once. Built different."',      "reward":"300K $B"},
  ],
  "RARE": [
    {"bounty":"The Powder Bomb",     "emoji":"💨","desc":'"Entire bag. Head to toe. Became a ghost for $BOUNTYWORK."',               "reward":"200K $B","proof":"https://x.com/ayushquantt/status/2062663328246149169"},
    {"bounty":"The Raw Deal",        "emoji":"🥚","desc":'"Cracked it open. Downed it raw. Pure bounty energy."',                   "reward":"150K $B"},
    {"bounty":"The Onion Eater",     "emoji":"🧅","desc":'"A whole raw onion. No reaction. Zero tears. Absolute psycho (respect)."',"reward":"200K $B"},
    {"bounty":"The 100 Pushup",      "emoji":"💪","desc":'"100 consecutive pushups on cam. Screamed $BOUNTYWORK on the last one."',  "reward":"100K $B"},
    {"bounty":"The Donut Destroyer", "emoji":"🍩","desc":'"Ate a dozen donuts in one sitting. For the bags."',                      "reward":"175K $B"},
    {"bounty":"The Vlog God",        "emoji":"📹","desc":'"Documented 7 days of the $BOUNTYWORK grind. Every single day."',         "reward":"160K $B"},
    {"bounty":"The Speed Cube",      "emoji":"🧩","desc":'"Solved a Rubik\'s cube while explaining $BOUNTYWORK. One take."',        "reward":"140K $B"},
    {"bounty":"The Gym Streak",      "emoji":"🏋️","desc":'"Hit the gym 7 days straight, posted about $BOUNTYWORK each time."',     "reward":"130K $B"},
    {"bounty":"The Street Poster",   "emoji":"📌","desc":'"Printed $BOUNTYWORK flyers and plastered them across the city."',         "reward":"120K $B"},
    {"bounty":"The Podcast Guest",   "emoji":"🎙️","desc":'"Got on a crypto podcast and talked $BOUNTYWORK for 20 minutes."',       "reward":"200K $B"},
    {"bounty":"The Night Swimmer",   "emoji":"🌊","desc":'"Swam in the ocean at night for $BOUNTYWORK. Brave or unhinged? Yes."',   "reward":"165K $B"},
    {"bounty":"The Spicy Noodle",    "emoji":"🍜","desc":'"Ate a full bowl of ghost pepper noodles. Smile never left their face."', "reward":"145K $B"},
  ],
  "UNCOMMON": [
    {"bounty":"The Meme Lord",       "emoji":"😂","desc":'"Created the dankest $BOUNTYWORK meme the community had ever seen."',     "reward":"30K $B"},
    {"bounty":"The Thread Weaver",   "emoji":"🧵","desc":'"Wrote a 10-tweet thread about $BOUNTYWORK. Every post hit different."',  "reward":"100K $B"},
    {"bounty":"The TikToker",        "emoji":"📱","desc":'"Posted a $BOUNTYWORK TikTok. Captions on point. Bag secured."',          "reward":"150K $B"},
    {"bounty":"The Reddit Raider",   "emoji":"🤖","desc":'"Dropped $BOUNTYWORK on r/CryptoMoonShots. Hit 50 upvotes overnight."',  "reward":"75K $B"},
    {"bounty":"The Sticker Pack",    "emoji":"🎨","desc":'"Designed a full Telegram sticker pack. The community went wild."',       "reward":"200K $B"},
    {"bounty":"The YouTube Shorty",  "emoji":"▶️","desc":'"Made a YouTube Short about $BOUNTYWORK. Views popping off."',            "reward":"175K $B"},
  ],
  "COMMON": [
    {"bounty":"The Tweeter",         "emoji":"🐦","desc":'"Posted about $BOUNTYWORK with the CA and got the community going."',     "reward":"50K $B"},
    {"bounty":"The Newcomer",        "emoji":"🚀","desc":'"First buy. First step. Every legend starts somewhere."',                 "reward":"10K $B"},
    {"bounty":"The Hashtag Hero",    "emoji":"#️⃣","desc":'"Dropped the right tags at the right time. Stealth marketing champion."', "reward":"50K $B"},
    {"bounty":"The Diamond Hand",    "emoji":"💎","desc":'"Bought and held. Never panicked. True degen energy."',                   "reward":"10K $B"},
    {"bounty":"The Tag Master",      "emoji":"🏷️","desc":'"Tagged three crypto influencers. Got the eyeballs."',                   "reward":"60K $B"},
  ],
}

RARITY_META = {
  "LEGENDARY":{"rc":"#f5c542","rg":"rgba(245,197,66,.55)","cbg":"linear-gradient(160deg,#1a1000,#0a0800)","ab":"linear-gradient(135deg,#3a2000,#1a0f00)","ag":"radial-gradient(circle at 40% 40%,rgba(245,197,66,.3),transparent 70%)","stars":"★★★★★"},
  "EPIC":     {"rc":"#c084fc","rg":"rgba(192,132,252,.5)","cbg":"linear-gradient(160deg,#120020,#080010)","ab":"linear-gradient(135deg,#1a0030,#0a0018)","ag":"radial-gradient(circle at 40% 40%,rgba(192,132,252,.3),transparent 70%)","stars":"★★★★☆"},
  "RARE":     {"rc":"#60a5fa","rg":"rgba(96,165,250,.5)","cbg":"linear-gradient(160deg,#000e20,#000810)","ab":"linear-gradient(135deg,#001535,#000c1f)","ag":"radial-gradient(circle at 40% 40%,rgba(96,165,250,.3),transparent 70%)","stars":"★★★☆☆"},
  "UNCOMMON": {"rc":"#4ade80","rg":"rgba(74,222,128,.45)","cbg":"linear-gradient(160deg,#001a0a,#000c05)","ab":"linear-gradient(135deg,#001a10,#000e08)","ag":"radial-gradient(circle at 40% 40%,rgba(74,222,128,.25),transparent 70%)","stars":"★★☆☆☆"},
  "COMMON":   {"rc":"#9ca3af","rg":"rgba(156,163,175,.35)","cbg":"linear-gradient(160deg,#0a0c12,#060810)","ab":"linear-gradient(135deg,#0a0e18,#060810)","ag":"radial-gradient(circle at 40% 40%,rgba(156,163,175,.2),transparent 70%)","stars":"★☆☆☆☆"},
}

_edition_lock = threading.Lock()
_edition_count = [1000]

def next_edition():
    with _edition_lock:
        _edition_count[0] += 1
        return _edition_count[0]

def mint_card(rarity):
    templates = TEMPLATES.get(rarity, TEMPLATES["COMMON"])
    t = random.choice(templates)
    ed = next_edition()
    uid = hashlib.md5(f"{rarity}{t['bounty']}{ed}{time.time()}".encode()).hexdigest()[:10]
    meta = RARITY_META[rarity]
    return {
        "id": uid,
        "num": f"#{ed:04d}",
        "rarity": rarity,
        "hunter": "Community Hunter",
        "bounty": t["bounty"],
        "desc": t["desc"],
        "reward": t["reward"],
        "emoji": t["emoji"],
        "proof": t.get("proof",""),
        "mintedAt": datetime.now(timezone.utc).isoformat(),
        **meta,
    }

# ── Data helpers ──────────────────────────────────────────────────────────────
_lock = threading.Lock()

def load_users():
    if not os.path.exists(USERS_FILE):
        return {"users":{}}
    with open(USERS_FILE,"r",encoding="utf-8") as f:
        return json.load(f)

def save_users(d):
    with open(USERS_FILE,"w",encoding="utf-8") as f:
        json.dump(d,f,indent=2,ensure_ascii=False)

def load_pool():
    if not os.path.exists(POOL_FILE):
        return {"pool":[],"editionCount":1000,"lastRare":0,"lastEpic":0,"lastLeg":0}
    with open(POOL_FILE,"r",encoding="utf-8") as f:
        return json.load(f)

def save_pool(d):
    with open(POOL_FILE,"w",encoding="utf-8") as f:
        json.dump(d,f,indent=2,ensure_ascii=False)

def load_chat():
    if not os.path.exists(CHAT_FILE):
        return {"messages":[]}
    with open(CHAT_FILE,"r",encoding="utf-8") as f:
        return json.load(f)

def save_chat(d):
    with open(CHAT_FILE,"w",encoding="utf-8") as f:
        json.dump(d,f,indent=2,ensure_ascii=False)

def post_system_message(text, card=None, msg_type="system"):
    with _lock:
        chat = load_chat()
        msg = {
            "id": hashlib.md5(f"sys{time.time()}{random.random()}".encode()).hexdigest()[:8],
            "username": "SYSTEM",
            "text": text,
            "gif": "",
            "card": card,
            "upvotes": 0,
            "upvotedBy": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": msg_type,
        }
        chat["messages"].append(msg)
        chat["messages"] = chat["messages"][-300:]
        save_chat(chat)

# ── Scheduler ─────────────────────────────────────────────────────────────────
def scheduler_loop():
    while True:
        time.sleep(60)  # check every minute
        now = time.time()
        with _lock:
            p = load_pool()
            changed = False
            if now - p.get("lastRare",0) >= RARE_SEC:
                card = mint_card("RARE")
                p["pool"].append(card)
                p["lastRare"] = now
                changed = True
                print(f"[{_ts()}] New RARE minted: {card['bounty']}")
            if now - p.get("lastEpic",0) >= EPIC_SEC:
                card = mint_card("EPIC")
                p["pool"].append(card)
                p["lastEpic"] = now
                changed = True
                print(f"[{_ts()}] New EPIC minted: {card['bounty']}")
            if now - p.get("lastLeg",0) >= LEG_SEC:
                card = mint_card("LEGENDARY")
                p["pool"].append(card)
                p["lastLeg"] = now
                changed = True
                print(f"[{_ts()}] New LEGENDARY minted: {card['bounty']}")
            if changed:
                # Keep pool to last 100 cards
                p["pool"] = p["pool"][-100:]
                save_pool(p)

def _ts():
    return datetime.now().strftime("%H:%M:%S")

# ── RNG pull ──────────────────────────────────────────────────────────────────
def roll_rarity():
    r = random.random() * 100
    for (name, threshold) in PULL_TIERS:
        if r < threshold:
            return name
    return "COMMON"

def do_pull():
    rarity = roll_rarity()
    pool = load_pool()["pool"]
    candidates = [c for c in pool if c["rarity"] == rarity]
    if candidates:
        base = random.choice(candidates)
    else:
        base = mint_card(rarity)
    # Create unique instance
    card = dict(base)
    card["instanceId"] = hashlib.md5(f"{base['id']}{time.time()}{random.random()}".encode()).hexdigest()[:8]
    return card

# ── HTTP handler ──────────────────────────────────────────────────────────────
MIME = {".html":"text/html;charset=utf-8",".css":"text/css",".js":"application/javascript",
        ".json":"application/json",".png":"image/png",".ico":"image/x-icon",".svg":"image/svg+xml"}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def cors(self):
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Access-Control-Allow-Methods","GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers","Content-Type,X-Username")

    def json_resp(self, code, data):
        body = json.dumps(data,ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(body)))
        self.cors(); self.end_headers(); self.wfile.write(body)

    def file_resp(self, path):
        try:
            with open(path,"rb") as f: body = f.read()
            ext = os.path.splitext(path)[1].lower()
            self.send_response(200)
            self.send_header("Content-Type",MIME.get(ext,"application/octet-stream"))
            self.send_header("Content-Length",str(len(body)))
            self.cors(); self.end_headers(); self.wfile.write(body)
        except FileNotFoundError:
            self.send_response(404); self.end_headers()

    def body(self):
        n = int(self.headers.get("Content-Length",0))
        return json.loads(self.rfile.read(n)) if n else {}

    def do_OPTIONS(self):
        self.send_response(200); self.cors(); self.end_headers()

    def do_GET(self):
        p = self.path.split("?")[0]

        # ── GET /api/pool ──────────────────────────────────────
        if p == "/api/pool":
            self.json_resp(200, load_pool())

        # ── GET /api/users ─────────────────────────────────────
        elif p == "/api/users":
            d = load_users()
            flex = []
            for u in d["users"].values():
                coll = u.get("collection",[])
                order = {"LEGENDARY":0,"EPIC":1,"RARE":2,"UNCOMMON":3,"COMMON":4}
                top = sorted(coll, key=lambda c: order.get(c.get("rarity","COMMON"),4))
                flex.append({
                    "username": u["username"],
                    "totalCards": len(coll),
                    "topCard": top[0] if top else None,
                    "legendaries": sum(1 for c in coll if c.get("rarity")=="LEGENDARY"),
                    "epics":       sum(1 for c in coll if c.get("rarity")=="EPIC"),
                    "rares":       sum(1 for c in coll if c.get("rarity")=="RARE"),
                    "joinedAt": u.get("joinedAt",""),
                })
            flex.sort(key=lambda x: (-(x["legendaries"]*1000 + x["epics"]*100 + x["rares"]*10 + x["totalCards"])))
            self.json_resp(200, flex)

        # ── GET /api/users/:name ────────────────────────────────
        elif p.startswith("/api/users/"):
            uname = p.split("/api/users/")[1]
            d = load_users()
            user = d["users"].get(uname)
            if not user: self.json_resp(404,{"error":"User not found"}); return
            # Don't expose cooldown internals — compute client-side values
            now = time.time()
            batch_start = user.get("batchStart", 0)
            batch_pulls = user.get("batchPulls", 0)
            elapsed = now - batch_start
            if elapsed >= COOLDOWN_SEC:
                batch_pulls = 0
            pulls_left = max(0, MAX_PULLS - batch_pulls)
            cooldown_left = max(0, int(COOLDOWN_SEC - elapsed)) if batch_pulls >= MAX_PULLS else 0
            self.json_resp(200, {
                "username": user["username"],
                "collection": user.get("collection",[]),
                "totalCards": len(user.get("collection",[])),
                "pullsLeft": pulls_left,
                "cooldownLeft": cooldown_left,
                "joinedAt": user.get("joinedAt",""),
            })

        # ── GET /api/chat ───────────────────────────────────────
        elif p.startswith("/api/chat"):
            chat = load_chat()
            msgs = chat.get("messages",[])
            since = ""
            if "since=" in p:
                since = p.split("since=")[1].split("&")[0]
            if since:
                msgs = [m for m in msgs if m.get("timestamp","") > since]
            self.json_resp(200,{"messages": msgs[-80:]})

        # ── Static files ────────────────────────────────────────
        elif p in ("/",""):
            self.file_resp(os.path.join(BASE_DIR,"index.html"))
        else:
            self.file_resp(os.path.join(BASE_DIR, p.lstrip("/")))

    def do_POST(self):
        p = self.path.split("?")[0]

        # ── POST /api/register ──────────────────────────────────
        if p == "/api/register":
            body = self.body()
            uname = body.get("username","").strip()
            if not uname or len(uname) < 2 or len(uname) > 20:
                self.json_resp(400,{"error":"Username must be 2-20 characters"}); return
            if not uname.replace("_","").replace("-","").isalnum():
                self.json_resp(400,{"error":"Only letters, numbers, _ and - allowed"}); return
            with _lock:
                d = load_users()
                if uname.lower() in {k.lower() for k in d["users"]}:
                    self.json_resp(409,{"error":"Username already taken"}); return
                d["users"][uname] = {
                    "username": uname,
                    "collection": [],
                    "batchPulls": 0,
                    "batchStart": 0,
                    "joinedAt": datetime.now(timezone.utc).isoformat(),
                }
                save_users(d)
            print(f"[{_ts()}] New user: {uname}")
            self.json_resp(201,{"ok":True,"username":uname,"pullsLeft":MAX_PULLS,"cooldownLeft":0,"collection":[]})

        # ── POST /api/pull ──────────────────────────────────────
        elif p == "/api/pull":
            body    = self.body()
            uname   = self.headers.get("X-Username","").strip() or body.get("username","").strip()
            count   = min(int(body.get("count",1)), 10)
            if not uname:
                self.json_resp(401,{"error":"Not logged in"}); return
            with _lock:
                d = load_users()
                user = d["users"].get(uname)
                if not user:
                    self.json_resp(404,{"error":"User not found"}); return
                now = time.time()
                elapsed = now - user.get("batchStart",0)
                if elapsed >= COOLDOWN_SEC:
                    user["batchPulls"] = 0
                    user["batchStart"] = now
                batch_pulls = user.get("batchPulls",0)
                if batch_pulls >= MAX_PULLS:
                    remaining = int(COOLDOWN_SEC - elapsed)
                    self.json_resp(429,{"error":"Cooldown active","cooldownLeft":remaining}); return
                actual = min(count, MAX_PULLS - batch_pulls)
                pulled = [do_pull() for _ in range(actual)]
                user["collection"].extend(pulled)
                user["batchPulls"] = batch_pulls + actual
                if user["batchPulls"] == actual and user.get("batchStart",0) == 0:
                    user["batchStart"] = now
                elif user.get("batchStart",0) == 0 or elapsed >= COOLDOWN_SEC:
                    user["batchStart"] = now
                save_users(d)
            pulls_left = max(0, MAX_PULLS - user["batchPulls"])
            cooldown_left = max(0, int(COOLDOWN_SEC - (time.time() - user["batchStart"]))) if user["batchPulls"] >= MAX_PULLS else 0
            self.json_resp(200,{
                "ok": True,
                "cards": pulled,
                "pullsLeft": pulls_left,
                "cooldownLeft": cooldown_left,
            })
            # Legendary alert in chat
            legs = [c for c in pulled if c.get("rarity")=="LEGENDARY"]
            for card in legs:
                threading.Thread(target=post_system_message, args=(
                    f"🔔 {uname} just pulled a LEGENDARY: {card['bounty']}!",
                    card, "legendary_alert"
                ), daemon=True).start()
        # ── POST /api/discard ───────────────────────────────────
        elif p == "/api/discard":
            body  = self.body()
            uname = self.headers.get("X-Username","").strip() or body.get("username","").strip()
            iid   = body.get("instanceId","").strip()
            if not uname or not iid:
                self.json_resp(400,{"error":"Missing username or instanceId"}); return
            with _lock:
                d    = load_users()
                user = d["users"].get(uname)
                if not user:
                    self.json_resp(404,{"error":"User not found"}); return
                before = len(user["collection"])
                user["collection"] = [c for c in user["collection"] if c.get("instanceId") != iid]
                removed = before - len(user["collection"])
                save_users(d)
            print(f"[{_ts()}] {uname} discarded card {iid} ({removed} removed)")
            self.json_resp(200,{"ok":True,"removed":removed})

        # ── POST /api/chat ──────────────────────────────────────
        elif p == "/api/chat":
            body  = self.body()
            uname = self.headers.get("X-Username","").strip() or body.get("username","").strip()
            if not uname:
                self.json_resp(401,{"error":"Not logged in"}); return
            text  = str(body.get("text","")).strip()[:400]
            gif   = str(body.get("gif","")).strip()
            card  = body.get("card")
            if not text and not gif and not card:
                self.json_resp(400,{"error":"Empty message"}); return
            msg = {
                "id": hashlib.md5(f"{uname}{time.time()}{random.random()}".encode()).hexdigest()[:8],
                "username": uname,
                "text": text,
                "gif": gif,
                "card": card,
                "upvotes": 0,
                "upvotedBy": [],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": "message",
            }
            with _lock:
                chat = load_chat()
                chat["messages"].append(msg)
                chat["messages"] = chat["messages"][-300:]
                save_chat(chat)
            self.json_resp(201,{"ok":True,"message":msg})

        # ── POST /api/upvote ────────────────────────────────────
        elif p == "/api/upvote":
            body   = self.body()
            uname  = self.headers.get("X-Username","").strip() or body.get("username","").strip()
            msg_id = body.get("messageId","")
            with _lock:
                chat = load_chat()
                for m in chat["messages"]:
                    if m["id"] == msg_id:
                        voted = m.setdefault("upvotedBy",[])
                        if uname in voted:
                            voted.remove(uname)
                            m["upvotes"] = max(0, m.get("upvotes",0)-1)
                        else:
                            voted.append(uname)
                            m["upvotes"] = m.get("upvotes",0)+1
                        save_chat(chat)
                        self.json_resp(200,{"ok":True,"upvotes":m["upvotes"],"voted":uname in voted})
                        return
            self.json_resp(404,{"error":"Message not found"})

        else:
            self.json_resp(404,{"error":"Not found"})

# ── Init & run ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Seed the pool on first run
    if not os.path.exists(POOL_FILE):
        p = {"pool":[],"lastRare":0,"lastEpic":0,"lastLeg":0}
        for r in ["COMMON","COMMON","UNCOMMON","UNCOMMON","RARE","RARE","RARE","EPIC","LEGENDARY"]:
            p["pool"].append(mint_card(r))
        save_pool(p)
        print(f"[{_ts()}] Pool seeded with {len(p['pool'])} cards")

    if not os.path.exists(USERS_FILE):
        save_users({"users":{}})

    print("="*55)
    print("BOUNTYWORK CARDS SERVER")
    print("="*55)
    print(f"  Port          : {PORT}")
    print(f"  Max pulls     : {MAX_PULLS} then {COOLDOWN_SEC//60}-min cooldown")
    print(f"  Rare every    : {RARE_SEC//60} min")
    print(f"  Epic every    : {EPIC_SEC//60} min")
    print(f"  Legendary every: {LEG_SEC//60} min")
    print("="*55)

    threading.Thread(target=scheduler_loop, daemon=True).start()

    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"\nServer running -> http://localhost:{PORT}\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopped.")
