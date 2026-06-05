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
import urllib.request, urllib.error, urllib.parse
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
# Force unbuffered output so logs appear in Render immediately
os.environ["PYTHONUNBUFFERED"] = "1"

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.environ.get("DATA_DIR", BASE_DIR)
GIST_TOKEN = os.environ.get("GIST_TOKEN","")
GIST_ID    = os.environ.get("GIST_ID","")
USERS_FILE = os.path.join(DATA_DIR, "users.json")
POOL_FILE  = os.path.join(DATA_DIR, "pool.json")
CHAT_FILE  = os.path.join(DATA_DIR, "chat.json")
PORT       = int(os.environ.get("PORT", 3457))

STARTING_ROLLS   = 40
CREDIT_INTERVAL  = 15 * 60
CREDITS_PER_TICK = 15
MAX_ROLLS        = 20_000
MAX_LOCKER       = 100_000
GIST_BACKUP_INTERVAL = 5 * 60   # backup to Gist every 5 min (not every heartbeat)
_last_gist_backup    = [0]       # track last Gist backup time

# ── Card drop cycle (every 40 min) ───────────────────────────────────────────
CYCLE_SEC   = 40 * 60
DROP_COUNTS = {"LEGENDARY":1, "EPIC":3, "RARE":5, "UNCOMMON":7, "COMMON":10}

# ── Pull weights ──────────────────────────────────────────────────────────────
# Roll 0-100; cumulative thresholds:
#   LEGENDARY < 0.2  (0.2%)
#   EPIC      < 10   (9.8%)
#   RARE      < 50   (40%)
#   UNCOMMON  < 85   (35%)
#   COMMON    < 100  (15%)
PULL_TIERS = [
    ("LEGENDARY", 0.2),   # 0.2%
    ("EPIC",      3.9),   # 3.7%
    ("RARE",      18.9),  # 15%
    ("UNCOMMON",  48.9),  # 30%
    ("COMMON",    100.0), # 45%
]

# ── Card templates (large pool for unique drops every 40 min) ─────────────────
TEMPLATES = {
  "LEGENDARY": [
    {"bounty":"The Tattoo Saint",       "emoji":"💉","desc":'"Got $BOUNTYWORK permanently tattooed. No regrets. Forever in the hunt."',"reward":"2M $B"},
    {"bounty":"The Sky Diver",          "emoji":"🪂","desc":'"Skydived with $BOUNTYWORK written across their suit. Pure insanity."',   "reward":"1.5M $B"},
    {"bounty":"The Fire Walker",        "emoji":"🔥","desc":'"Walked barefoot across burning coals for $BOUNTYWORK. Zero hesitation."',"reward":"1.2M $B"},
    {"bounty":"The Rainbow Mane",       "emoji":"🌈","desc":'"Dyed every strand of hair 7 different colours. All for the bags."',      "reward":"900K $B"},
    {"bounty":"The Bald Sacrifice",     "emoji":"🪒","desc":'"Shaved it all off on camera. No wig. No mercy. No going back."',         "reward":"500K $B","proof":"https://x.com/ayushquantt/status/2062585750206525537"},
    {"bounty":"The Brow Eraser",        "emoji":"😶","desc":'"Both eyebrows gone. On camera. Didn\'t even blink."',                   "reward":"400K $B","proof":"https://x.com/ayushquantt/status/2062662989589746140"},
    {"bounty":"The Eternal Ink",        "emoji":"🎭","desc":'"Got the $BOUNTYWORK logo tattooed on their neck. Committed for life."',  "reward":"2.5M $B"},
    {"bounty":"The Summit Conqueror",   "emoji":"🏔️","desc":'"Climbed a mountain and planted a $BOUNTYWORK flag at the peak."',      "reward":"1.8M $B"},
    {"bounty":"The Overnight Warrior",  "emoji":"🌙","desc":'"Stayed awake 72 hours straight grinding $BOUNTYWORK content live."',    "reward":"1.1M $B"},
    {"bounty":"The Cliff Diver",        "emoji":"🌊","desc":'"Cliff dived 30 metres with $BOUNTYWORK painted on their back."',        "reward":"1.4M $B"},
    {"bounty":"The Billboard Legend",   "emoji":"📢","desc":'"Rented a billboard and put $BOUNTYWORK on it for a full week."',        "reward":"3M $B"},
    {"bounty":"The World Record",       "emoji":"🏆","desc":'"Attempted a Guinness World Record wearing $BOUNTYWORK gear."',          "reward":"2M $B"},
    {"bounty":"The Stage Crasher",      "emoji":"🎪","desc":'"Got on stage at a live event and shouted $BOUNTYWORK into the mic."',   "reward":"1.6M $B"},
    {"bounty":"The Marathon Legend",    "emoji":"🏅","desc":'"Ran a full 26.2 mile marathon in $BOUNTYWORK gear. Top 100 finish."',   "reward":"1.3M $B"},
    {"bounty":"The Ice Sculptor",       "emoji":"🧊","desc":'"Carved $BOUNTYWORK into a 6-foot ice block in a public square."',      "reward":"1.7M $B"},
    {"bounty":"The Skydive Banner",     "emoji":"🎌","desc":'"Unfurled a $BOUNTYWORK banner mid-freefall at 15,000 feet."',          "reward":"2.2M $B"},
    {"bounty":"The Body Painter",       "emoji":"🎨","desc":'"Had $BOUNTYWORK painted across their entire torso at a public beach."', "reward":"800K $B"},
    {"bounty":"The Flash Mob Leader",   "emoji":"💃","desc":'"Organised a 50-person $BOUNTYWORK flash mob in a shopping centre."',   "reward":"1.9M $B"},
    {"bounty":"The Zero Gravity",       "emoji":"🚀","desc":'"Went on a zero-G flight with $BOUNTYWORK on their shirt."',            "reward":"4M $B"},
    {"bounty":"The Firework Launch",    "emoji":"🎆","desc":'"Set off fireworks that spelled out $BOUNTYWORK in the night sky."',    "reward":"2.8M $B"},
  ],
  "EPIC": [
    {"bounty":"The Toilet Dive",        "emoji":"🚽","desc":'"Full head submerge, one take, no cuts. Toilet and all."',              "reward":"350K $B","proof":"https://x.com/ayushquantt/status/2062687785811587393"},
    {"bounty":"The Spicy Legend",       "emoji":"🌶️","desc":'"Ate the nuclear ramen challenge on camera. Cried. Finished it."',     "reward":"450K $B"},
    {"bounty":"The Mud Warrior",        "emoji":"🏃","desc":'"Ran a full mile through knee-deep mud in $BOUNTYWORK gear."',          "reward":"400K $B"},
    {"bounty":"The Fast King",          "emoji":"⏱️","desc":'"Fasted 24 straight hours for $BOUNTYWORK. Pure mental strength."',    "reward":"380K $B"},
    {"bounty":"The Karaoke Degen",      "emoji":"🎤","desc":'"Sang a crypto rap in public. Strangers joined in."',                  "reward":"360K $B"},
    {"bounty":"The Rooftop Screamer",   "emoji":"📣","desc":'"Climbed a rooftop and screamed $BOUNTYWORK 50 times at the city."',   "reward":"340K $B"},
    {"bounty":"The Cold Plunge",        "emoji":"❄️","desc":'"Jumped into a frozen lake and stayed in for 3 minutes."',             "reward":"400K $B"},
    {"bounty":"The Ice Bath King",      "emoji":"🧊","desc":'"Two minutes in an ice bath. Stone cold face the whole time."',        "reward":"300K $B"},
    {"bounty":"The Wing King",          "emoji":"🍗","desc":'"Ate 50 ghost pepper wings in one sitting. Didn\'t touch milk once."', "reward":"320K $B"},
    {"bounty":"The Sleep Deprived",     "emoji":"😴","desc":'"Stayed awake 48 hours and posted $BOUNTYWORK content every hour."',   "reward":"280K $B"},
    {"bounty":"The Public Splash",      "emoji":"💦","desc":'"Jumped fully clothed into a public fountain screaming $BOUNTYWORK."', "reward":"310K $B"},
    {"bounty":"The Charity Runner",     "emoji":"🎽","desc":'"Ran 10 miles for charity in $BOUNTYWORK gear. Raised actual money."', "reward":"420K $B"},
    {"bounty":"The Stunt Driver",       "emoji":"🏎️","desc":'"Learned to drift a car and did it with $BOUNTYWORK on the hood."',   "reward":"480K $B"},
    {"bounty":"The Snake Handler",      "emoji":"🐍","desc":'"Held a live snake for 5 minutes on camera for $BOUNTYWORK."',        "reward":"350K $B"},
    {"bounty":"The Bungee Jumper",      "emoji":"🪢","desc":'"Bungee jumped while wearing a $BOUNTYWORK t-shirt. First time."',    "reward":"500K $B"},
    {"bounty":"The Polar Swim",         "emoji":"🏊","desc":'"Swam a full kilometre in 5-degree ocean water for $BOUNTYWORK."',    "reward":"440K $B"},
    {"bounty":"The Storm Chaser",       "emoji":"⛈️","desc":'"Stood in a hailstorm for 10 minutes holding a $BOUNTYWORK sign."',  "reward":"370K $B"},
    {"bounty":"The Skate Legend",       "emoji":"🛹","desc":'"Learned to skateboard in 24 hours and landed a trick for $BW."',    "reward":"290K $B"},
    {"bounty":"The Hot Spring Dip",     "emoji":"♨️","desc":'"Jumped from a snow bank directly into a hot spring shouting $BW."', "reward":"330K $B"},
    {"bounty":"The Cage Diver",         "emoji":"🦈","desc":'"Went cage diving with sharks wearing $BOUNTYWORK on their suit."',  "reward":"600K $B"},
  ],
  "RARE": [
    {"bounty":"The Powder Bomb",        "emoji":"💨","desc":'"Entire bag over their head. Became a ghost for $BOUNTYWORK."',        "reward":"200K $B","proof":"https://x.com/ayushquantt/status/2062663328246149169"},
    {"bounty":"The Raw Deal",           "emoji":"🥚","desc":'"Cracked it open. Downed it raw. No filter, pure bounty energy."',    "reward":"150K $B"},
    {"bounty":"The Onion Eater",        "emoji":"🧅","desc":'"A whole raw onion. No reaction. Zero tears."',                       "reward":"200K $B"},
    {"bounty":"The 100 Pushup",         "emoji":"💪","desc":'"100 consecutive pushups on cam. Screamed $BOUNTYWORK on rep 100."',  "reward":"100K $B"},
    {"bounty":"The Donut Destroyer",    "emoji":"🍩","desc":'"A full dozen donuts in one sitting. Every last crumb. For the bags."',"reward":"175K $B"},
    {"bounty":"The Vlog God",           "emoji":"📹","desc":'"7 straight days of $BOUNTYWORK content. Never missed a day."',       "reward":"160K $B"},
    {"bounty":"The Speed Cube",         "emoji":"🧩","desc":'"Solved a Rubik\'s cube while explaining $BOUNTYWORK to camera."',   "reward":"140K $B"},
    {"bounty":"The Gym Streak",         "emoji":"🏋️","desc":'"Gym every day for a week, $BOUNTYWORK post every single session."', "reward":"130K $B"},
    {"bounty":"The Street Poster",      "emoji":"📌","desc":'"Printed 200 $BOUNTYWORK flyers and posted them across the city."',   "reward":"120K $B"},
    {"bounty":"The Podcast Guest",      "emoji":"🎙️","desc":'"Got on a crypto podcast and talked $BOUNTYWORK for 20 minutes."',  "reward":"200K $B"},
    {"bounty":"The Night Swimmer",      "emoji":"🌊","desc":'"Ocean swim at midnight for $BOUNTYWORK. Brave or unhinged? Yes."',  "reward":"165K $B"},
    {"bounty":"The Spicy Noodle",       "emoji":"🍜","desc":'"Ghost pepper noodles. Full bowl. Never stopped smiling."',           "reward":"145K $B"},
    {"bounty":"The 50 Burpee",          "emoji":"🏃","desc":'"50 burpees without stopping. Shouted $BOUNTYWORK at the end."',     "reward":"110K $B"},
    {"bounty":"The Live Streamer",      "emoji":"📺","desc":'"Streamed for 8 hours straight promoting $BOUNTYWORK non-stop."',    "reward":"180K $B"},
    {"bounty":"The Trash Bag Outfit",   "emoji":"🗑️","desc":'"Wore a full outfit made of bin bags in public for $BOUNTYWORK."',  "reward":"135K $B"},
    {"bounty":"The Balcony Singer",     "emoji":"🎶","desc":'"Sang a $BOUNTYWORK song from their balcony. Neighbours filmed it."',"reward":"125K $B"},
    {"bounty":"The Spicy Smoothie",     "emoji":"🥤","desc":'"Blended and drank a full ghost pepper smoothie on camera."',        "reward":"155K $B"},
    {"bounty":"The Worm Dancer",        "emoji":"🪱","desc":'"Held a live worm in each hand for 5 minutes for $BOUNTYWORK."',    "reward":"115K $B"},
    {"bounty":"The Backwards Runner",   "emoji":"🔄","desc":'"Ran a mile backwards in public with $BOUNTYWORK on their shirt."',  "reward":"145K $B"},
    {"bounty":"The Chilli Stare",       "emoji":"😤","desc":'"Stared into a chilli for 60 seconds without blinking. Won."',       "reward":"105K $B"},
    {"bounty":"The Stranger Hug",       "emoji":"🤗","desc":'"Gave 20 strangers a hug and told them about $BOUNTYWORK."',        "reward":"95K $B"},
    {"bounty":"The Cold Shower Week",   "emoji":"🚿","desc":'"7 days straight of cold showers. Posted every single one."',       "reward":"170K $B"},
    {"bounty":"The Public Push-Up",     "emoji":"🏋️","desc":'"Did push-ups in the middle of a busy shopping centre."',          "reward":"105K $B"},
    {"bounty":"The Staring Contest",    "emoji":"👁️","desc":'"Beat a stranger in a staring contest. Winner shouts $BOUNTYWORK."',"reward":"90K $B"},
    {"bounty":"The Lemon Finisher",     "emoji":"🍋","desc":'"Ate a whole lemon — peel included — without flinching once."',     "reward":"120K $B"},
  ],
  "UNCOMMON": [
    {"bounty":"The Meme Lord",          "emoji":"😂","desc":'"Created the dankest $BOUNTYWORK meme the community had ever seen."', "reward":"30K $B"},
    {"bounty":"The Thread Weaver",      "emoji":"🧵","desc":'"Wrote a 10-tweet thread about $BOUNTYWORK. Every post hit."',       "reward":"100K $B"},
    {"bounty":"The TikToker",           "emoji":"📱","desc":'"Posted a $BOUNTYWORK TikTok that actually slapped."',               "reward":"150K $B"},
    {"bounty":"The Reddit Raider",      "emoji":"🤖","desc":'"Dropped $BOUNTYWORK on r/CryptoMoonShots. Hit 50 upvotes."',       "reward":"75K $B"},
    {"bounty":"The Sticker Maker",      "emoji":"🎨","desc":'"Designed a full Telegram sticker pack. Community went wild."',      "reward":"200K $B"},
    {"bounty":"The YouTube Shorty",     "emoji":"▶️","desc":'"Made a YouTube Short about $BOUNTYWORK. Views popping off."',      "reward":"175K $B"},
    {"bounty":"The Discord Builder",    "emoji":"🗨️","desc":'"Grew a $BOUNTYWORK Discord server to 100 members."',              "reward":"220K $B"},
    {"bounty":"The Quote Retweeter",    "emoji":"🔁","desc":'"Got 25 quote retweets on a single $BOUNTYWORK post."',             "reward":"85K $B"},
    {"bounty":"The Language Translator","emoji":"🌍","desc":'"Translated the $BOUNTYWORK how-to-buy guide into 3 languages."',  "reward":"65K $B"},
    {"bounty":"The Influencer Tag",     "emoji":"📲","desc":'"Tagged 5 crypto influencers (10K+ each) in one $BOUNTYWORK post."',"reward":"90K $B"},
    {"bounty":"The Fan Artist",         "emoji":"🖼️","desc":'"Drew original fan art featuring $BOUNTYWORK. Submitted to community."',"reward":"55K $B"},
    {"bounty":"The Poem Writer",        "emoji":"✍️","desc":'"Wrote an original 12-line poem about $BOUNTYWORK and posted it."', "reward":"45K $B"},
    {"bounty":"The Wallpaper Pack",     "emoji":"🖥️","desc":'"Designed 5 $BOUNTYWORK phone wallpapers. Community loved them."', "reward":"70K $B"},
    {"bounty":"The Forum Hustler",      "emoji":"💬","desc":'"Started a $BOUNTYWORK thread on 3 different crypto forums."',      "reward":"60K $B"},
    {"bounty":"The Voice Note",         "emoji":"🎵","desc":'"Recorded a voice memo explaining $BOUNTYWORK and went viral."',    "reward":"55K $B"},
    {"bounty":"The Poll Maker",         "emoji":"📊","desc":'"Made a Twitter poll about $BOUNTYWORK. 500+ people voted."',       "reward":"50K $B"},
    {"bounty":"The Review Writer",      "emoji":"📝","desc":'"Wrote a 300-word review of $BOUNTYWORK on pump.fun."',            "reward":"45K $B"},
    {"bounty":"The GIF Creator",        "emoji":"🎞️","desc":'"Created an original animated GIF of the $BOUNTYWORK coin."',     "reward":"80K $B"},
    {"bounty":"The Group Poster",       "emoji":"👥","desc":'"Shared $BOUNTYWORK in 10 different crypto Telegram groups."',      "reward":"65K $B"},
    {"bounty":"The Crosspost Champion", "emoji":"🔀","desc":'"Crossposted $BOUNTYWORK content across 5 platforms in one day."',  "reward":"95K $B"},
    {"bounty":"The Contest Host",       "emoji":"🎯","desc":'"Hosted a $BOUNTYWORK trivia contest in a public Discord."',        "reward":"110K $B"},
    {"bounty":"The Profile Switcher",   "emoji":"🔄","desc":'"Changed their profile pic to $BOUNTYWORK logo for a full month."', "reward":"40K $B"},
    {"bounty":"The X Space Host",       "emoji":"🎙️","desc":'"Hosted a 30-minute X Space about $BOUNTYWORK. 30+ listeners."', "reward":"130K $B"},
    {"bounty":"The News Poster",        "emoji":"📰","desc":'"Got $BOUNTYWORK mentioned in a crypto newsletter."',              "reward":"160K $B"},
    {"bounty":"The Bio Adder",          "emoji":"📌","desc":'"Added $BOUNTYWORK CA to their bio across all social platforms."',  "reward":"35K $B"},
    {"bounty":"The Community Guide",    "emoji":"📚","desc":'"Wrote a beginner guide explaining $BOUNTYWORK to normies."',      "reward":"85K $B"},
    {"bounty":"The Rap Spitter",        "emoji":"🎤","desc":'"Wrote and posted a 16-bar rap about $BOUNTYWORK. Fire bars."',    "reward":"120K $B"},
    {"bounty":"The Video Tutorial",     "emoji":"📷","desc":'"Made a step-by-step video on how to buy $BOUNTYWORK."',          "reward":"145K $B"},
  ],
  "COMMON": [
    {"bounty":"The Tweeter",            "emoji":"🐦","desc":'"Posted about $BOUNTYWORK with the CA. Solid."',                    "reward":"50K $B"},
    {"bounty":"The Newcomer",           "emoji":"🚀","desc":'"First buy. First step. Every legend starts somewhere."',           "reward":"10K $B"},
    {"bounty":"The Hashtag Hero",       "emoji":"#️⃣","desc":'"Used the right tags at the right time."',                          "reward":"50K $B"},
    {"bounty":"The Diamond Hand",       "emoji":"💎","desc":'"Bought and held. Didn\'t panic sell."',                            "reward":"10K $B"},
    {"bounty":"The Tag Master",         "emoji":"🏷️","desc":'"Tagged three crypto influencers. Got eyes on $BOUNTYWORK."',      "reward":"60K $B"},
    {"bounty":"The Early Bird",         "emoji":"🐤","desc":'"Bought $BOUNTYWORK before it hit the trending page."',             "reward":"15K $B"},
    {"bounty":"The Wallet Connector",   "emoji":"🔗","desc":'"Connected their Phantom wallet and made their first swap."',       "reward":"5K $B"},
    {"bounty":"The First Share",        "emoji":"📤","desc":'"Shared the $BOUNTYWORK CA with at least one friend."',            "reward":"20K $B"},
    {"bounty":"The Believer",           "emoji":"🙏","desc":'"Bought in during the dip. Conviction unlocked."',                  "reward":"15K $B"},
    {"bounty":"The Lurker",             "emoji":"👀","desc":'"Watched quietly, then bought when the time was right."',           "reward":"8K $B"},
    {"bounty":"The Community Joiner",   "emoji":"🤝","desc":'"Joined the $BOUNTYWORK community and introduced themselves."',    "reward":"12K $B"},
    {"bounty":"The Retweeter",          "emoji":"🔁","desc":'"Retweeted the $BOUNTYWORK launch post without hesitation."',      "reward":"18K $B"},
    {"bounty":"The Reply Guy",          "emoji":"💬","desc":'"Left a solid reply under a $BOUNTYWORK post. Based."',            "reward":"10K $B"},
    {"bounty":"The Liker",              "emoji":"❤️","desc":'"Liked every $BOUNTYWORK post. Showing love."',                    "reward":"5K $B"},
    {"bounty":"The First Comment",      "emoji":"✍️","desc":'"First person to comment on the $BOUNTYWORK launch post."',        "reward":"25K $B"},
    {"bounty":"The Screenshot Saver",   "emoji":"📸","desc":'"Screenshotted their $BOUNTYWORK buy for the memories."',          "reward":"8K $B"},
    {"bounty":"The Bag Checker",        "emoji":"💰","desc":'"Checked the $BOUNTYWORK price exactly 100 times in a day."',      "reward":"10K $B"},
    {"bounty":"The Profile Updater",    "emoji":"🔄","desc":'"Updated their Telegram bio to include $BOUNTYWORK."',             "reward":"12K $B"},
    {"bounty":"The Question Asker",     "emoji":"❓","desc":'"Asked a smart question about $BOUNTYWORK in the community."',     "reward":"15K $B"},
    {"bounty":"The Weekend Buyer",      "emoji":"📅","desc":'"Bought $BOUNTYWORK on a Saturday at 3am. Based timing."',        "reward":"10K $B"},
    {"bounty":"The Meme Sharer",        "emoji":"😆","desc":'"Shared a $BOUNTYWORK meme in at least 3 group chats."',          "reward":"20K $B"},
    {"bounty":"The Pump Watcher",       "emoji":"📈","desc":'"Watched the $BOUNTYWORK chart for 6+ hours straight."',           "reward":"8K $B"},
    {"bounty":"The Farm Hand",          "emoji":"🌾","desc":'"Held $BOUNTYWORK through two separate pumps and dumps."',         "reward":"15K $B"},
    {"bounty":"The Small Bag",          "emoji":"👜","desc":'"Bought a small bag just to say they were there at the start."',   "reward":"5K $B"},
    {"bounty":"The Alert Setter",       "emoji":"🔔","desc":'"Set a price alert for $BOUNTYWORK and actually followed through."',"reward":"10K $B"},
    {"bounty":"The Solana Sender",      "emoji":"⚡","desc":'"Sent SOL to their wallet in under 2 minutes to buy $BOUNTYWORK."',"reward":"12K $B"},
    {"bounty":"The Pump Fan",           "emoji":"🎯","desc":'"Left a 5-star review for $BOUNTYWORK on pump.fun."',             "reward":"18K $B"},
    {"bounty":"The Second Buy",         "emoji":"2️⃣","desc":'"Came back and bought a second bag after seeing gains."',          "reward":"20K $B"},
    {"bounty":"The Price Prophet",      "emoji":"🔮","desc":'"Predicted $BOUNTYWORK\'s next price move and was correct."',      "reward":"25K $B"},
    {"bounty":"The Midnight Buyer",     "emoji":"🌙","desc":'"Bought $BOUNTYWORK between midnight and 4am. Committed."',       "reward":"10K $B"},
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

def mint_card(rarity, t=None):
    if t is None:
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

def save_users(d, force_gist=True):
    """Save users locally. Backs up to Gist immediately for critical ops, throttled otherwise."""
    with open(USERS_FILE,"w",encoding="utf-8") as f:
        json.dump(d,f,indent=2,ensure_ascii=False)
    if GIST_TOKEN and GIST_ID:
        now = time.time()
        if force_gist or (now - _last_gist_backup[0]) >= GIST_BACKUP_INTERVAL:
            if _backup_to_gist(d):
                _last_gist_backup[0] = now

def _backup_to_gist(data):
    """Synchronously write users data to GitHub Gist."""
    try:
        body = json.dumps({
            "files": {"users.json": {"content": json.dumps(data, ensure_ascii=False)}}
        }).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.github.com/gists/{GIST_ID}",
            data=body, method="PATCH",
            headers={
                "Authorization": f"token {GIST_TOKEN}",
                "Content-Type": "application/json",
                "User-Agent": "BountyworkCardsServer/1.0",
                "Accept": "application/vnd.github.v3+json",
            }
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            if r.status == 200:
                print(f"[{_ts()}] Gist saved: {len(data.get('users',{}))} users", flush=True)
                return True
    except Exception as e:
        print(f"[{_ts()}] Gist backup ERROR: {e}", flush=True)
    return False

def _restore_from_gist():
    """Fetch users data from GitHub Gist on startup."""
    if not GIST_TOKEN or not GIST_ID:
        return None
    try:
        req = urllib.request.Request(
            f"https://api.github.com/gists/{GIST_ID}",
            headers={
                "Authorization": f"token {GIST_TOKEN}",
                "User-Agent": "BountyworkCardsServer/1.0",
            }
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            gist = json.loads(r.read().decode("utf-8"))
            content = gist["files"]["users.json"]["content"]
            data = json.loads(content)
            if data and isinstance(data.get("users"), dict):
                return data
    except Exception as e:
        print(f"[{_ts()}] Gist restore failed: {e}", flush=True)
    return None

def load_pool():
    if not os.path.exists(POOL_FILE):
        return {"pool":[],"editionCount":1000,"lastRare":0,"lastEpic":0,"lastLeg":0}
    with open(POOL_FILE,"r",encoding="utf-8") as f:
        return json.load(f)

def save_pool(d):
    with open(POOL_FILE,"w",encoding="utf-8") as f:
        json.dump(d,f,indent=2,ensure_ascii=False)

def hash_pw(pw):
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()

# In-memory chat cooldown: {username: last_send_timestamp}
_chat_cd = {}
CHAT_CD_SEC = 20

def load_chat():
    if not os.path.exists(CHAT_FILE):
        return {"messages":[]}
    with open(CHAT_FILE,"r",encoding="utf-8") as f:
        return json.load(f)

def save_chat(d):
    with open(CHAT_FILE,"w",encoding="utf-8") as f:
        json.dump(d,f,indent=2,ensure_ascii=False)

def get_top_user():
    """Return username of #1 on the time leaderboard, or None."""
    try:
        d = load_users()
        users = list(d["users"].values())
        if not users: return None
        top = max(users, key=lambda u: u.get("totalMinutes", 0))
        return top["username"] if top.get("totalMinutes", 0) > 0 else None
    except:
        return None

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

# ── Card drop cycle (every 40 min: 1 Leg + 3 Epic + 5 Rare + 7 Uncommon + 10 Common)
def run_drop_cycle():
    ts = _ts()
    print(f"\n[{ts}] Running 40-min card drop...", flush=True)
    with _lock:
        p = load_pool()
        used = set(p.get("usedTemplates", []))
        new_cards = []

        for rarity, count in DROP_COUNTS.items():
            pool_t = TEMPLATES.get(rarity, [])
            avail  = [t for t in pool_t if t["bounty"] not in used]
            if len(avail) < count:
                # Reset used templates for this rarity when pool runs low
                used -= {t["bounty"] for t in pool_t}
                avail = pool_t
            chosen = random.sample(avail, min(count, len(avail)))
            for t in chosen:
                card = mint_card(rarity, t)
                new_cards.append(card)
                used.add(t["bounty"])
                print(f"  + [{rarity}] {t['bounty']}", flush=True)

        p["pool"].extend(new_cards)
        p["pool"] = p["pool"][-500:]
        p["usedTemplates"] = list(used)[-300:]
        p["lastCycle"] = time.time()
        save_pool(p)
    print(f"[{ts}] Dropped {len(new_cards)} new cards.\n", flush=True)

def scheduler_loop():
    while True:
        time.sleep(CYCLE_SEC)
        run_drop_cycle()

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

        # ── GET /api/test-backup ────────────────────────────────
        if p == "/api/test-backup":
            result = {"gist_token_set": bool(GIST_TOKEN), "gist_id": GIST_ID}
            if GIST_TOKEN and GIST_ID:
                try:
                    body = json.dumps({"files":{"users.json":{"content":"TEST"}}}).encode()
                    req = urllib.request.Request(
                        f"https://api.github.com/gists/{GIST_ID}",
                        data=body, method="PATCH",
                        headers={
                            "Authorization": f"token {GIST_TOKEN}",
                            "Content-Type": "application/json",
                            "User-Agent": "BountyworkTest/1.0",
                            "Accept": "application/vnd.github.v3+json",
                        }
                    )
                    with urllib.request.urlopen(req, timeout=15) as r:
                        result["status"] = r.status
                        result["success"] = r.status == 200
                except urllib.error.HTTPError as e:
                    result["error"] = f"HTTP {e.code}: {e.reason}"
                    result["success"] = False
                except Exception as e:
                    result["error"] = str(e)
                    result["success"] = False
            else:
                result["error"] = "Missing GIST_TOKEN or GIST_ID"
                result["success"] = False
            self.json_resp(200, result)

        # ── GET /api/health ────────────────────────────────────
        elif p == "/api/health":
            d = load_users()
            self.json_resp(200,{
                "status": "ok",
                "users": len(d.get("users",{})),
                "gist_configured": bool(GIST_TOKEN and GIST_ID),
                "gist_id": (GIST_ID[:8]+"...") if GIST_ID else "NOT SET",
                "token_set": bool(GIST_TOKEN),
                "data_dir": DATA_DIR,
            })

        # ── GET /api/pool ──────────────────────────────────────
        elif p == "/api/pool":
            self.json_resp(200, load_pool())

        # ── GET /api/leaderboard ───────────────────────────────
        elif p == "/api/leaderboard":
            d = load_users()
            board = []
            for u in d["users"].values():
                mins = u.get("totalMinutes", 0)
                board.append({
                    "username": u["username"],
                    "totalMinutes": mins,
                    "hours": mins // 60,
                    "minutes": mins % 60,
                    "cards": len(u.get("collection", [])),
                    "legendaries": sum(1 for c in u.get("collection",[]) if c.get("rarity")=="LEGENDARY"),
                })
            board.sort(key=lambda x: (-x["totalMinutes"], -x["cards"]))
            self.json_resp(200, board[:20])

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
            # Only users with at least 1 legendary, sorted by legendary count, top 3
            flex = [f for f in flex if f.get("legendaries",0) > 0]
            flex.sort(key=lambda x: (-x.get("legendaries",0), -x.get("totalCards",0)))
            self.json_resp(200, flex[:3])

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
            self.json_resp(200, {
                "username": user["username"],
                "collection": user.get("collection",[]),
                "totalCards": len(user.get("collection",[])),
                "rollCredits": user.get("rollCredits", STARTING_ROLLS),
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
            # On initial load (no since=), strip legendary alerts from history
            if not since:
                msgs = [m for m in msgs if m.get("type") != "legendary_alert"]
            self.json_resp(200,{"messages": msgs[-50:]})

        # ── Static files ────────────────────────────────────────
        elif p in ("/",""):
            self.file_resp(os.path.join(BASE_DIR,"index.html"))
        else:
            self.file_resp(os.path.join(BASE_DIR, p.lstrip("/")))

    def do_POST(self):
        p = self.path.split("?")[0]

        # ── POST /api/register ──────────────────────────────────
        if p == "/api/register":
            body  = self.body()
            uname = body.get("username","").strip()
            pwd   = body.get("password","").strip()
            if not uname or len(uname) < 2 or len(uname) > 20:
                self.json_resp(400,{"error":"Username must be 2-20 characters"}); return
            if not uname.replace("_","").replace("-","").isalnum():
                self.json_resp(400,{"error":"Only letters, numbers, _ and - allowed"}); return
            if not pwd or len(pwd) < 4:
                self.json_resp(400,{"error":"Password must be at least 4 characters"}); return
            with _lock:
                d = load_users()
                if uname.lower() in {k.lower() for k in d["users"]}:
                    self.json_resp(409,{"error":"Username already taken"}); return
                d["users"][uname] = {
                    "username": uname,
                    "password": hash_pw(pwd),
                    "collection": [],
                    "rollCredits": STARTING_ROLLS,
                    "lastCreditClaim": 0,
                    "totalMinutes": 0,
                    "joinedAt": datetime.now(timezone.utc).isoformat(),
                }
                save_users(d)
            print(f"[{_ts()}] New user: {uname}", flush=True)
            self.json_resp(201,{"ok":True,"username":uname,"rollCredits":STARTING_ROLLS,"collection":[]})

        # ── POST /api/login ─────────────────────────────────────
        elif p == "/api/login":
            body  = self.body()
            uname = body.get("username","").strip()
            pwd   = body.get("password","").strip()
            d     = load_users()
            user  = d["users"].get(uname)
            if not user:
                self.json_resp(404,{"error":"Username not found"}); return
            stored = user.get("password","")
            if stored and stored != hash_pw(pwd):
                self.json_resp(401,{"error":"Wrong password"}); return
            self.json_resp(200,{
                "username": uname,
                "collection": user.get("collection",[]),
                "rollCredits": user.get("rollCredits", STARTING_ROLLS),
            })

        # ── POST /api/heartbeat (track active time, 1 min = 1 ping) ──
        elif p == "/api/heartbeat":
            uname = self.headers.get("X-Username","").strip() or self.body().get("username","").strip()
            if not uname:
                self.json_resp(401,{"error":"Not logged in"}); return
            with _lock:
                d    = load_users()
                user = d["users"].get(uname)
                if not user:
                    self.json_resp(404,{"error":"User not found"}); return
                user["totalMinutes"] = user.get("totalMinutes", 0) + 1
                save_users(d, force_gist=False)  # throttled backup — not every minute
            top = get_top_user()
            self.json_resp(200,{
                "ok": True,
                "totalMinutes": user["totalMinutes"],
                "isTopUser": top == uname,
                "topUser": top,
            })

        # ── POST /api/credits (earn +15 rolls every 15 min) ────
        elif p == "/api/credits":
            uname = self.headers.get("X-Username","").strip() or self.body().get("username","").strip()
            if not uname:
                self.json_resp(401,{"error":"Not logged in"}); return
            with _lock:
                d    = load_users()
                user = d["users"].get(uname)
                if not user:
                    self.json_resp(404,{"error":"User not found"}); return
                now  = time.time()
                last = user.get("lastCreditClaim",0)
                if now - last < CREDIT_INTERVAL:
                    wait = int(CREDIT_INTERVAL-(now-last))
                    self.json_resp(429,{"error":"Too soon","waitSec":wait,
                                        "rollCredits":user.get("rollCredits",0)}); return
                cur  = user.get("rollCredits", 0)
                # 2x boost for #1 on time leaderboard
                top_user   = get_top_user()
                multiplier = 2 if (top_user == uname) else 1
                added = min(MAX_ROLLS - cur, CREDITS_PER_TICK * multiplier)
                new   = cur + added
                user["rollCredits"]     = new
                user["lastCreditClaim"] = now
                save_users(d)
            self.json_resp(200,{"ok":True,"rollCredits":new,"added":added,"boost":multiplier})

        # ── POST /api/pull ──────────────────────────────────────
        elif p == "/api/pull":
            body  = self.body()
            uname = self.headers.get("X-Username","").strip() or body.get("username","").strip()
            count = min(int(body.get("count",1)), 10)
            if not uname:
                self.json_resp(401,{"error":"Not logged in"}); return
            with _lock:
                d    = load_users()
                user = d["users"].get(uname)
                if not user:
                    self.json_resp(404,{"error":"User not found"}); return
                credits = user.get("rollCredits", 0)
                if credits <= 0:
                    self.json_resp(429,{"error":"No rolls left! Wait 15 min for +15 rolls.","rollCredits":0}); return
                # Check locker cap
                locker_size = len(user.get("collection",[]))
                if locker_size >= MAX_LOCKER:
                    self.json_resp(400,{"error":"Locker full! (100,000 card limit) Discard some cards first."}); return
                actual = min(count, credits, MAX_LOCKER - locker_size)
                pulled = [do_pull() for _ in range(actual)]
                user["collection"].extend(pulled)
                user["rollCredits"] = credits - actual
                save_users(d)
            self.json_resp(200,{
                "ok": True,
                "cards": pulled,
                "rollCredits": user["rollCredits"],
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
            print(f"[{_ts()}] {uname} discarded card {iid} ({removed} removed)", flush=True)
            self.json_resp(200,{"ok":True,"removed":removed})

        # ── POST /api/chat ──────────────────────────────────────
        elif p == "/api/chat":
            body  = self.body()
            uname = self.headers.get("X-Username","").strip() or body.get("username","").strip()
            if not uname:
                self.json_resp(401,{"error":"Not logged in"}); return
            # Rate limit: 20s cooldown per user
            now_cd = time.time()
            last_cd = _chat_cd.get(uname, 0)
            if now_cd - last_cd < CHAT_CD_SEC:
                remaining = int(CHAT_CD_SEC - (now_cd - last_cd))
                self.json_resp(429,{"error":f"Wait {remaining}s before sending again","cooldown":remaining}); return
            text  = str(body.get("text","")).strip()[:400]
            card  = body.get("card")
            if not text and not card:
                self.json_resp(400,{"error":"Empty message"}); return
            _chat_cd[uname] = now_cd
            msg = {
                "id": hashlib.md5(f"{uname}{time.time()}{random.random()}".encode()).hexdigest()[:8],
                "username": uname,
                "text": text,
                "gif": "",
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
    # Ensure data directory exists (important when using a Render disk at /data)
    os.makedirs(DATA_DIR, exist_ok=True)

    print("="*55)
    print("BOUNTYWORK CARDS SERVER")
    print("="*55)
    print(f"  Port           : {PORT}", flush=True)
    print(f"  Data dir       : {DATA_DIR}", flush=True)
    print(f"  Starting rolls : {STARTING_ROLLS}", flush=True)
    print(f"  Max rolls      : {MAX_ROLLS}", flush=True)
    print(f"  Max locker     : {MAX_LOCKER}", flush=True)
    print(f"  Credits/15min  : {CREDITS_PER_TICK}", flush=True)
    print(f"  Drop cycle     : every {CYCLE_SEC//60} min", flush=True)
    print(f"  Per cycle      : 1 Leg + 3 Epic + 5 Rare + 7 Uncommon + 10 Common", flush=True)
    print(f"  Template pool  : {sum(len(v) for v in TEMPLATES.values())} unique cards", flush=True)
    print("="*55)

    # ── USERS: always prefer Gist (most up-to-date) then local, then fresh ─────
    print(f"  Checking Gist for latest user data...", flush=True)
    gist_data = _restore_from_gist()

    if gist_data and gist_data.get("users"):
        # Write Gist data to local file (authoritative source)
        with open(USERS_FILE,"w",encoding="utf-8") as f:
            json.dump(gist_data,f,indent=2,ensure_ascii=False)
        print(f"  Restored {len(gist_data['users'])} user(s) from Gist backup!", flush=True)
    elif os.path.exists(USERS_FILE):
        d = load_users()
        total = len(d.get("users",{}))
        print(f"  Loaded {total} user(s) from local file (no Gist data)", flush=True)
        # Back up local to Gist now
        _backup_to_gist(d)
    else:
        print(f"  No user data found anywhere — starting fresh", flush=True)
        with open(USERS_FILE,"w",encoding="utf-8") as f:
            json.dump({"users":{}},f)
        _backup_to_gist({"users":{}})

    # ── POOL: load existing or seed fresh ──────────────────────────────────────
    if os.path.exists(POOL_FILE):
        p = load_pool()
        print(f"  Loaded existing pool ({len(p.get('pool',[]))} cards)", flush=True)
    else:
        save_pool({"pool":[], "usedTemplates":[], "lastCycle":0})
        print(f"  Created fresh pool — running initial drop...", flush=True)
        run_drop_cycle()

    # ── CHAT: load existing or create fresh ────────────────────────────────────
    if not os.path.exists(CHAT_FILE):
        save_chat({"messages":[]})

    threading.Thread(target=scheduler_loop, daemon=True).start()

    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"\nServer running -> http://localhost:{PORT}\n", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopped.")
