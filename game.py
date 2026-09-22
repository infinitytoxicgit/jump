import asyncio
import html
import io
import os
import random
import re
import sqlite3
import subprocess
import sys
import time
from collections import defaultdict

from PIL import Image, ImageDraw, ImageFont
from pyrogram import Client, filters
from pyrogram.enums import ChatType, ChatMemberStatus, ParseMode
from pyrogram.errors import RPCError
from pyrogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    Message,
    ChatMemberUpdated
)

# ============================================================
# CONFIG & CREDENTIALS
# ============================================================

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

API_ID = 35218869
API_HASH = "80baadcfd00a39a0ff1f5f529d23156f"
OWNER_ID = 8564072723
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")

START_IMG = "https://graph.org/file/7c0c03d68308f0c5dad42-ddb933df03f0ff0632.jpg"

app = Client(
    "capsule_rich_jumble_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

DB = sqlite3.connect("jumble_game.db", check_same_thread=False)
DB.row_factory = sqlite3.Row
LOCK = asyncio.Lock()

# ============================================================
# WORD BANK
# ============================================================

DEFAULT_EASY = """
apple banana orange mango table chair house water school friend family
happy garden flower animal window bottle mobile computer summer winter
river music movie player football cricket doctor teacher market village
country morning evening coffee bread pizza camera phone pencil paper
train bus road car earth world light night star cloud rain green blue
black white tiger lion horse rabbit monkey fish bird tree fruit
""".split()

DEFAULT_MEDIUM = """
adventure beautiful knowledge education important dangerous different
experience friendship happiness technology information internet
mountain waterfall sunshine keyboard hospital university restaurant
football cricket championship tournament engineer scientist medicine
history geography language computer network application database
security password community discussion entertainment television
photography creativity imagination discovery opportunity challenge
journey traveler vacation airport railway newspaper magazine
""".split()

DEFAULT_HARD = """
extraordinary responsibility communication determination independence
international transformation understanding environment intelligence
architecture investigation recommendation administration opportunity
entrepreneurship cryptocurrency cybersecurity authentication
programming mathematics biotechnology astrophysics psychology
philosophy civilization transportation infrastructure globalization
misunderstanding pronunciation encyclopedia experimentation
electromagnetism thermodynamics interoperability decentralization
""".split()

# ============================================================
# DATABASE SETUP
# ============================================================

DB.executescript("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    name TEXT,
    points INTEGER DEFAULT 0,
    solved INTEGER DEFAULT 0,
    best_streak INTEGER DEFAULT 0,
    streak INTEGER DEFAULT 0,
    fight_wins INTEGER DEFAULT 0,
    fight_losses INTEGER DEFAULT 0,
    bet_wins INTEGER DEFAULT 0,
    bet_losses INTEGER DEFAULT 0,
    is_private INTEGER DEFAULT 0,
    last_daily REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS auth_users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    name TEXT,
    added_at REAL
);

CREATE TABLE IF NOT EXISTS custom_words (
    difficulty TEXT,
    word TEXT,
    PRIMARY KEY(difficulty, word)
);

CREATE TABLE IF NOT EXISTS settings (
    chat_id INTEGER PRIMARY KEY,
    easy INTEGER DEFAULT 120,
    medium INTEGER DEFAULT 300,
    hard INTEGER DEFAULT 600,
    default_diff TEXT DEFAULT 'medium',
    is_active INTEGER DEFAULT 1,
    auto_delete INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS bot_config (
    key TEXT PRIMARY KEY,
    value INTEGER
);

CREATE TABLE IF NOT EXISTS games (
    chat_id INTEGER PRIMARY KEY,
    difficulty TEXT,
    word TEXT,
    puzzle_id INTEGER,
    started REAL,
    expires REAL,
    message_id INTEGER,
    solved INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS used_words (
    chat_id INTEGER,
    difficulty TEXT,
    word TEXT,
    PRIMARY KEY(chat_id, difficulty, word)
);

CREATE TABLE IF NOT EXISTS puzzle_hints (
    chat_id INTEGER,
    puzzle_id INTEGER,
    user_id INTEGER,
    hints_used INTEGER DEFAULT 0,
    revealed_indices TEXT DEFAULT '',
    PRIMARY KEY(chat_id, puzzle_id, user_id)
);

CREATE TABLE IF NOT EXISTS score_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    chat_id INTEGER,
    points INTEGER,
    timestamp REAL
);
""")
DB.commit()

def run_migrations():
    defaults = {
        "points_easy": 10,
        "points_medium": 20,
        "points_hard": 30,
        "hints_easy": 3,
        "hints_medium": 3,
        "hints_hard": 3,
        "daily_points": 50,
        "bonus_points": 100
    }
    for k, v in defaults.items():
        DB.execute("INSERT OR IGNORE INTO bot_config (key, value) VALUES (?, ?)", (k, v))
    DB.commit()

run_migrations()

WORDS = {
    "easy": list(set(w.lower() for w in DEFAULT_EASY if len(w) >= 3)),
    "medium": list(set(w.lower() for w in DEFAULT_MEDIUM if len(w) >= 3)),
    "hard": list(set(w.lower() for w in DEFAULT_HARD if len(w) >= 3))
}

custom_rows = DB.execute("SELECT difficulty, word FROM custom_words").fetchall()
for row in custom_rows:
    diff = row["difficulty"].lower()
    w = row["word"].lower().strip()
    if diff in WORDS and w not in WORDS[diff]:
        WORDS[diff].append(w)

# ============================================================
# VISUAL CAPSULE ENGINE (RENDER CAPSULE PILLS VIA PIL)
# ============================================================

def get_font(size):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"
    ]
    for path in paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()

def draw_capsule(draw, xy, fill, outline=None, width=1):
    x0, y0, x1, y1 = xy
    r = (y1 - y0) // 2
    draw.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=fill, outline=outline, width=width)

def generate_capsule_ui_card(title: str, main_text: str, tag1: str, tag2: str, tag3: str = None) -> io.BytesIO:
    """
    Creates modern Telegram streaming UI cards with pure colored capsule pills (Cyan, Green, Coral, Glass).
    """
    w, h = 1000, 520
    img = Image.new("RGBA", (w, h), (18, 22, 28, 255))
    draw = ImageDraw.Draw(img)

    # Accent Top Header Bar
    draw_capsule(draw, (40, 30, w - 40, 85), fill=(26, 115, 80, 255))
    font_top = get_font(26)
    draw.text((w // 2, 57), f"✦  {title.upper()}  ✦", anchor="mm", font=font_top, fill=(255, 255, 255))

    # Inner Glass Deck
    draw.rounded_rectangle([40, 105, w - 40, h - 110], radius=22, fill=(28, 33, 43, 255), outline=(45, 55, 72, 255), width=2)

    # Main Center Word / Metric
    font_main = get_font(56)
    draw.text((w // 2, 210), main_text, anchor="mm", font=font_main, fill=(0, 245, 255))

    # Decorative Dots / Progress Track Line
    draw_capsule(draw, (120, 300, w - 120, 308), fill=(40, 48, 64, 255))
    draw_capsule(draw, (120, 300, 480, 308), fill=(0, 230, 153, 255))

    # Bottom Colored Capsule Buttons (Pills)
    # Capsule 1: Red/Coral Pill (Replay / Reset)
    draw_capsule(draw, (60, 430, 280, 485), fill=(45, 25, 30, 255), outline=(235, 87, 87, 255), width=2)
    draw.text((170, 457), f"↺ {tag1}", anchor="mm", font=get_font(22), fill=(235, 87, 87))

    # Capsule 2: Green Pill (Play / Pause / Mode)
    draw_capsule(draw, (310, 430, 680, 485), fill=(20, 45, 35, 255), outline=(39, 174, 96, 255), width=2)
    draw.text((495, 457), f"▶ {tag2}", anchor="mm", font=get_font(22), fill=(46, 204, 113))

    # Capsule 3: Cyan/Blue Pill (Skip / Next)
    c3_text = tag3 or "NEXT"
    draw_capsule(draw, (710, 430, 940, 485), fill=(20, 40, 60, 255), outline=(41, 128, 185, 255), width=2)
    draw.text((825, 457), f"» {c3_text}", anchor="mm", font=get_font(22), fill=(52, 152, 219))

    bio = io.BytesIO()
    bio.name = "ui_capsule.png"
    img.save(bio, "PNG")
    bio.seek(0)
    return bio

def make_graph_bar(percentage: float, length: int = 8) -> str:
    clamped = max(0.0, min(100.0, float(percentage)))
    filled = int(round((clamped / 100.0) * length))
    empty = length - filled
    return "▰" * filled + "▱" * empty

# ============================================================
# CORE HELPERS
# ============================================================

def ensure_user(user):
    if not user:
        return
    DB.execute("""
        INSERT INTO users(user_id, username, name)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username=excluded.username,
            name=excluded.name
    """, (user.id, user.username or "", user.first_name or "Player"))
    DB.commit()

def get_user(user_id):
    return DB.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()

def is_owner(user_id):
    return int(user_id) == int(OWNER_ID) if user_id else False

def is_authed(user_id):
    if not user_id:
        return False
    if is_owner(user_id):
        return True
    row = DB.execute("SELECT user_id FROM auth_users WHERE user_id=?", (int(user_id),)).fetchone()
    return bool(row)

async def is_admin_or_owner(chat, user_id):
    if is_owner(user_id):
        return True
    if chat.type in (ChatType.PRIVATE,):
        return True
    try:
        member = await chat.get_member(user_id)
        return member.status in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR)
    except Exception:
        return False

def get_settings(chat_id):
    row = DB.execute("SELECT * FROM settings WHERE chat_id=?", (chat_id,)).fetchone()
    if not row:
        DB.execute("""
            INSERT INTO settings(chat_id, easy, medium, hard, default_diff, is_active, auto_delete)
            VALUES (?, 120, 300, 600, 'medium', 1, 0)
            ON CONFLICT(chat_id) DO NOTHING
        """, (chat_id,))
        DB.commit()
        row = DB.execute("SELECT * FROM settings WHERE chat_id=?", (chat_id,)).fetchone()
    return row

def get_mention(user_obj=None, user_id=None, first_name=None, username=None):
    if user_obj:
        u_id = user_obj.id
        f_name = user_obj.first_name or "Player"
        u_name = user_obj.username
    else:
        u_id = user_id
        f_name = first_name or "Player"
        u_name = username

    clean_name = html.escape(str(f_name))
    if u_name:
        return f"<a href='https://t.me/{u_name}'>{clean_name}</a>"
    return f"<a href='tg://openmessage?user_id={u_id}'>{clean_name}</a>"

def clean_answer(text):
    return "".join(c.lower() for c in str(text) if c.isalnum())

def jumble_word(word):
    letters = list(word)
    for _ in range(50):
        random.shuffle(letters)
        result = "".join(letters)
        if result != word and result[::-1] != word:
            return result.upper()
    return "".join(letters).upper()

def choose_word(chat_id, difficulty):
    pool = WORDS.get(difficulty, [])[:]
    used = {
        row["word"]
        for row in DB.execute(
            "SELECT word FROM used_words WHERE chat_id=? AND difficulty=?",
            (chat_id, difficulty)
        ).fetchall()
    }
    available = [w for w in pool if w not in used]
    if not available:
        DB.execute("DELETE FROM used_words WHERE chat_id=? AND difficulty=?", (chat_id, difficulty))
        DB.commit()
        available = pool
    if not available:
        return "JUMBLE"
    word = random.choice(available)
    DB.execute("INSERT OR IGNORE INTO used_words(chat_id, difficulty, word) VALUES (?, ?, ?)", (chat_id, difficulty, word))
    DB.commit()
    return word

def get_global_config(key, default_val):
    row = DB.execute("SELECT value FROM bot_config WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default_val

def set_global_config(key, val):
    DB.execute("""
        INSERT INTO bot_config (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
    """, (key, val))
    DB.commit()

# ============================================================
# PERSISTENT BOTTOM KEYBOARD (NO INLINE BUTTONS)
# ============================================================

def get_main_menu_keyboard():
    """Native bottom reply keyboard (Replaces inline button clutter)"""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🧩 New Puzzle"), KeyboardButton("💡 Clue / Hint")],
            [KeyboardButton("📊 Leaderboard"), KeyboardButton("👤 My Stats")],
            [KeyboardButton("⚙️ Settings"), KeyboardButton("⏭️ Skip")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )

# ============================================================
# RICH GAME LAUNCHER & EXPIRY
# ============================================================

async def start_game(chat_id, difficulty, message_or_chat):
    settings = get_settings(chat_id)
    if not settings["is_active"]:
        return

    DB.execute("DELETE FROM games WHERE chat_id=?", (chat_id,))

    word = choose_word(chat_id, difficulty)
    jumbled = jumble_word(word)
    puzzle_id = random.randint(10000, 99999)
    now = time.time()
    timer_val = settings[difficulty]
    reward_pts = get_global_config(f"points_{difficulty}", 10)
    hint_limit = get_global_config(f"hints_{difficulty}", 3)
    expires = now + timer_val

    DB.execute("""
        INSERT INTO games(chat_id, difficulty, word, puzzle_id, started, expires, message_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (chat_id, difficulty, word, puzzle_id, now, expires, 0))
    DB.commit()

    card_image = generate_capsule_ui_card(
        title=f"Jumble #{puzzle_id} • {difficulty.upper()}",
        main_text="   ".join(jumbled) if len(jumbled) <= 8 else " ".join(jumbled),
        tag1="SKIP (/skip)",
        tag2=f"+{reward_pts} XP",
        tag3=f"HINT ({hint_limit})"
    )

    caption_text = (
        f"<blockquote>🧩 <b>𝐉𝐔𝐌𝐁𝐋𝐄 𝐏𝐔𝐙𝐙𝐋𝐄 #{puzzle_id}</b>\n\n"
        f"┌ <b>Difficulty:</b> <code>{difficulty.title()}</code>\n"
        f"├ <b>Time Limit:</b> <code>{timer_val // 60}m {timer_val % 60}s</code>\n"
        f"├ <b>Solve Reward:</b> <code>+{reward_pts} pts</code>\n"
        f"└ <b>Allowed Hints:</b> <code>{hint_limit}/player</code>\n\n"
        f"<b>Controls (No buttons):</b>\n"
        f"• Hint chahiye? Type <code>/hint</code>\n"
        f"• Skip karna hai? Type <code>/skip</code>\n"
        f"• New word? Type <code>/new</code></blockquote>\n\n"
        f"<blockquote>🔀 <i>Unscramble the letters & send answer in chat!</i></blockquote>"
    )

    try:
        if isinstance(message_or_chat, Message):
            sent = await message_or_chat.reply_photo(photo=card_image, caption=caption_text, reply_markup=get_main_menu_keyboard(), parse_mode=ParseMode.HTML)
        else:
            sent = await app.send_photo(chat_id, photo=card_image, caption=caption_text, reply_markup=get_main_menu_keyboard(), parse_mode=ParseMode.HTML)
        DB.execute("UPDATE games SET message_id=? WHERE chat_id=?", (sent.id, chat_id))
        DB.commit()
    except Exception as e:
        print(f"Game start error: {e}")

    asyncio.create_task(expire_game(chat_id, puzzle_id, expires))

async def expire_game(chat_id, puzzle_id, expires):
    await asyncio.sleep(max(0, expires - time.time()))
    row = DB.execute("SELECT * FROM games WHERE chat_id=? AND puzzle_id=?", (chat_id, puzzle_id)).fetchone()
    if not row or row["solved"]:
        return

    DB.execute("UPDATE games SET solved=1 WHERE chat_id=?", (chat_id,))
    DB.commit()

    try:
        await app.send_message(
            chat_id,
            f"<blockquote>⏰ <b>𝐓𝐈𝐌𝐄'𝐒 𝐔𝐏!</b>\n\n"
            f"❌ <b>Nobody unscrambled the word.</b>\n"
            f"✅ <b>Answer was:</b> <code>{row['word'].upper()}</code>\n\n"
            f"🔄 <i>Next puzzle loading in 3 seconds...</i></blockquote>",
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass

    await asyncio.sleep(3)
    s = get_settings(chat_id)
    if s["is_active"]:
        next_diff = s["default_diff"] if "default_diff" in s.keys() else "medium"
        asyncio.create_task(start_game(chat_id, next_diff, chat_id))

# ============================================================
# RICH STATS CARD (UNIVERSAL LOOKUP & GRAPH)
# ============================================================

async def resolve_target_user(client: Client, message: Message):
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user
    args = message.command[1:] if len(message.command) > 1 else []
    if args:
        val = args[0]
        try:
            if val.isdigit():
                return await client.get_users(int(val))
            return await client.get_users(val)
        except Exception:
            return None
    if message.entities:
        for entity in message.entities:
            if entity.type.name == "TEXT_MENTION" and entity.user:
                return entity.user
    return message.from_user

def render_rich_stats_text(u: sqlite3.Row, user_obj=None):
    total_fights = (u["fight_wins"] or 0) + (u["fight_losses"] or 0)
    fight_winrate = ((u["fight_wins"] / total_fights) * 100) if total_fights else 0.0
    f_bar = make_graph_bar(fight_winrate, 8)

    total_bets = (u["bet_wins"] or 0) + (u["bet_losses"] or 0)
    bet_winrate = (((u["bet_wins"] or 0) / total_bets) * 100) if total_bets else 0.0
    b_bar = make_graph_bar(bet_winrate, 8)

    mention = get_mention(user_obj=user_obj, user_id=u["user_id"], first_name=u["name"], username=u["username"])
    tier = "👑 Grandmaster" if u["points"] >= 5000 else ("💎 Diamond" if u["points"] >= 2000 else "🛡️ Fighter")

    return (
        f"<blockquote>👤 <b>𝐏𝐋𝐀𝐘𝐄𝐑 𝐒𝐓𝐀𝐓𝐈𝐒𝐓𝐈𝐂𝐒 𝐂𝐀𝐑𝐃</b>\n"
        f"├ <b>Player:</b> {mention}\n"
        f"├ <b>Rank Tier:</b> <code>{tier}</code>\n"
        f"├ <b>Total Points:</b> <code>{u['points']:,} pts</code>\n"
        f"├ <b>Words Solved:</b> <code>{u['solved']:,}</code>\n"
        f"└ <b>Active Streak:</b> <code>{u['streak']}</code> (Best: {u['best_streak']})\n\n"
        f"⚔️ <b>1v1 Duel Arena</b>\n"
        f"<code>[{f_bar}]</code> <b>{fight_winrate:.1f}%</b> ({u['fight_wins']}W - {u['fight_losses']}L)\n\n"
        f"💰 <b>High Stakes Bet Match</b>\n"
        f"<code>[{b_bar}]</code> <b>{bet_winrate:.1f}%</b> ({u['bet_wins']}W - {u['bet_losses']}L)</blockquote>\n\n"
        f"<blockquote>📌 <i>Kisi aur ka stats check karne ke liye:</i> <code>/stats @username</code></blockquote>"
    )

@app.on_message(filters.command(["stats", "stat", "score", "profile"]))
async def stats_cmd(client: Client, message: Message):
    target = await resolve_target_user(client, message)
    if not target:
        return await message.reply_text("<blockquote>❌ <b>User nahi mila.</b> Sahi @username ya ID dein.</blockquote>", parse_mode=ParseMode.HTML)

    ensure_user(target)
    u = get_user(target.id)
    if not u:
        return await message.reply_text("<blockquote>❌ Is player ka record nahi mila.</blockquote>", parse_mode=ParseMode.HTML)

    stats_msg = render_rich_stats_text(u, target)
    card_img = generate_capsule_ui_card(
        title=f"PROFILE • {target.first_name[:12]}",
        main_text=f"{u['points']:,} PTS",
        tag1=f"SOLVED: {u['solved']}",
        tag2=f"STREAK: {u['streak']}",
        tag3=f"FIGHTS: {u['fight_wins']}W"
    )
    await message.reply_photo(photo=card_img, caption=stats_msg, parse_mode=ParseMode.HTML)

# ============================================================
# RICH TABLE LEADERBOARD (NO BUTTONS, PURE FORMATTING)
# ============================================================

@app.on_message(filters.command(["leaderboard", "top", "rank", "lb"]))
async def leaderboard_cmd(_, message: Message):
    now = time.time()
    since = now - 86400

    # Group Daily
    rows = DB.execute("""
        SELECT h.user_id, u.name, u.username, u.is_private, SUM(h.points) as total_pts
        FROM score_history h
        LEFT JOIN users u ON h.user_id = u.user_id
        WHERE h.chat_id = ? AND h.timestamp >= ?
        GROUP BY h.user_id
        HAVING total_pts > 0
        ORDER BY total_pts DESC
        LIMIT 10
    """, (message.chat.id, since)).fetchall()

    if not rows:
        # Fallback to Global all-time
        rows = DB.execute("""
            SELECT user_id, name, username, is_private, points as total_pts
            FROM users
            WHERE points > 0
            ORDER BY points DESC
            LIMIT 10
        """).fetchall()
        heading = "🌍 <b>GLOBAL ALL-TIME LEADERBOARD</b>"
    else:
        heading = "📅 <b>DAILY GROUP LEADERBOARD (24h)</b>"

    medals = ["🥇", "🥈", "🥉"]
    max_pts = rows[0]["total_pts"] if rows else 1

    text = f"<blockquote>{heading}\n\n"
    for idx, r in enumerate(rows, 1):
        pts = r["total_pts"]
        bar = make_graph_bar((pts / max_pts) * 100, 6)
        m_tag = medals[idx - 1] if idx <= 3 else f"<code>#{idx:02d}</code>"
        p_name = html.escape(str(r["name"] or "Player"))
        text += f"{m_tag} <b>{p_name}</b>\n    <code>[{bar}]</code> ⭐ <b>{pts:,}</b> XP\n"

    text += "\n<i>Commands:</i> <code>/lb global</code> • <code>/lb daily</code></blockquote>"
    await message.reply_text(text, parse_mode=ParseMode.HTML)

# ============================================================
# GAME CONTROLS (TEXT BASED, ZERO INLINE BUTTONS)
# ============================================================

@app.on_message(filters.command("hint"))
async def hint_cmd(_, message: Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    game = DB.execute("SELECT * FROM games WHERE chat_id=? AND solved=0", (chat_id,)).fetchone()
    if not game:
        return await message.reply_text("<blockquote>❌ Koi active puzzle nahi chal raha. Naya shuru karne ke liye <code>/jumble</code> likhein.</blockquote>", parse_mode=ParseMode.HTML)

    ensure_user(message.from_user)
    puzzle_id = game["puzzle_id"]
    word = game["word"]
    difficulty = game["difficulty"]

    hint_limit = get_global_config(f"hints_{difficulty}", 3)
    hint_row = DB.execute("SELECT * FROM puzzle_hints WHERE chat_id=? AND puzzle_id=? AND user_id=?", (chat_id, puzzle_id, user_id)).fetchone()
    hints_used = hint_row["hints_used"] if hint_row else 0
    revealed_indices = [int(i) for i in hint_row["revealed_indices"].split(",") if i] if hint_row else []

    if hints_used >= hint_limit:
        return await message.reply_text(f"<blockquote>❌ Aapke is word ke {hint_limit} hints pure ho chuke hain!</blockquote>", parse_mode=ParseMode.HTML)

    avail = [i for i in range(len(word)) if i not in revealed_indices]
    if not avail:
        return await message.reply_text("<blockquote>❌ Sabhi letters reveal ho chuke hain!</blockquote>", parse_mode=ParseMode.HTML)

    chosen = random.choice(avail)
    revealed_indices.append(chosen)
    hints_used += 1

    DB.execute("""
        INSERT INTO puzzle_hints(chat_id, puzzle_id, user_id, hints_used, revealed_indices)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(chat_id, puzzle_id, user_id) DO UPDATE SET
            hints_used=excluded.hints_used,
            revealed_indices=excluded.revealed_indices
    """, (chat_id, puzzle_id, user_id, hints_used, ",".join(map(str, revealed_indices))))
    DB.commit()

    letter = word[chosen].upper()
    await message.reply_text(
        f"<blockquote>💡 <b>𝐂𝐋𝐔𝐄 𝐑𝐄𝐕𝐄𝐀𝐋𝐄𝐃</b>\n\n"
        f"Letter #{chosen + 1} is: <code>{letter}</code>\n"
        f"Hints remaining: <b>{hint_limit - hints_used}/{hint_limit}</b></blockquote>",
        parse_mode=ParseMode.HTML
    )

@app.on_message(filters.command("skip"))
async def skip_cmd(_, message: Message):
    if not message.from_user or not await is_admin_or_owner(message.chat, message.from_user.id):
        return await message.reply_text("<blockquote>❌ Sirf group admins skip kar sakte hain.</blockquote>", parse_mode=ParseMode.HTML)

    chat_id = message.chat.id
    game = DB.execute("SELECT * FROM games WHERE chat_id=? AND solved=0", (chat_id,)).fetchone()
    if not game:
        return await message.reply_text("<blockquote>Active game nahi mila.</blockquote>", parse_mode=ParseMode.HTML)

    DB.execute("UPDATE games SET solved=1 WHERE chat_id=?", (chat_id,))
    DB.commit()

    await message.reply_text(
        f"<blockquote>⏭️ <b>𝐒𝐊𝐈𝐏𝐏𝐄𝐃!</b>\n\n"
        f"Word was: <code>{game['word'].upper()}</code>\n"
        f"🔄 <i>Next puzzle starting in 3 seconds...</i></blockquote>",
        parse_mode=ParseMode.HTML
    )
    await asyncio.sleep(3)
    s = get_settings(chat_id)
    if s["is_active"]:
        next_diff = s["default_diff"] if "default_diff" in s.keys() else "medium"
        asyncio.create_task(start_game(chat_id, next_diff, chat_id))

@app.on_message(filters.command(["jumble", "new"]))
async def jumble_cmd(_, message: Message):
    ensure_user(message.from_user)
    DB.execute("UPDATE settings SET is_active=1 WHERE chat_id=?", (message.chat.id,))
    DB.commit()

    s = get_settings(message.chat.id)
    default_d = s["default_diff"] if "default_diff" in s.keys() else "medium"

    if len(message.command) > 1:
        req_diff = message.command[1].lower().strip()
        difficulty = req_diff if req_diff in WORDS else default_d
    else:
        difficulty = default_d

    await start_game(message.chat.id, difficulty, message)

# ============================================================
# PERSISTENT REPLY KEYBOARD DISPATCHER
# ============================================================

@app.on_message(filters.text & filters.regex(r"^(🧩 New Puzzle|💡 Clue / Hint|📊 Leaderboard|👤 My Stats|⚙️ Settings|⏭️ Skip)$"))
async def reply_menu_dispatcher(client: Client, message: Message):
    txt = message.text
    if txt == "🧩 New Puzzle":
        await jumble_cmd(client, message)
    elif txt == "💡 Clue / Hint":
        await hint_cmd(client, message)
    elif txt == "📊 Leaderboard":
        await leaderboard_cmd(client, message)
    elif txt == "👤 My Stats":
        await stats_cmd(client, message)
    elif txt == "⚙️ Settings":
        await settings_cmd(client, message)
    elif txt == "⏭️ Skip":
        await skip_cmd(client, message)

# ============================================================
# SETTINGS VIA TEXT COMMANDS (CLEAN UI)
# ============================================================

@app.on_message(filters.command(["settings", "setting"]))
async def settings_cmd(_, message: Message):
    if not message.from_user or not await is_admin_or_owner(message.chat, message.from_user.id):
        return await message.reply_text("<blockquote>❌ Sirf group admins settings badal sakte hain.</blockquote>", parse_mode=ParseMode.HTML)

    s = get_settings(message.chat.id)
    cur_diff = s["default_diff"] if "default_diff" in s.keys() else "medium"

    text = (
        f"<blockquote>⚙️ <b>𝐆𝐑𝐎𝐔𝐏 𝐉𝐔𝐌𝐁𝐋𝐄 𝐒𝐄𝐓𝐓𝐈𝐍𝐆𝐒</b>\n\n"
        f"┌ <b>Status:</b> <code>{'Running' if s['is_active'] else 'Stopped'}</code>\n"
        f"├ <b>Default Difficulty:</b> <code>{str(cur_diff).title()}</code>\n"
        f"├ <b>Timers:</b> Easy: <code>{s['easy']}s</code> | Med: <code>{s['medium']}s</code> | Hard: <code>{s['hard']}s</code>\n"
        f"└ <b>Auto Delete:</b> <code>{'Enabled' if s['auto_delete'] else 'Disabled'}</code>\n\n"
        f"<b>Commands to Change Settings:</b>\n"
        f"• <code>/setmode easy</code> (or medium/hard)\n"
        f"• <code>/settimer easy 60</code> (or 120)\n"
        f"• <code>/stopgame</code> ya <code>/startgame</code></blockquote>"
    )
    await message.reply_text(text, parse_mode=ParseMode.HTML)

@app.on_message(filters.command("setmode"))
async def setmode_cmd(_, message: Message):
    if not message.from_user or not await is_admin_or_owner(message.chat, message.from_user.id):
        return await message.reply_text("<blockquote>❌ Admins only.</blockquote>", parse_mode=ParseMode.HTML)
    if len(message.command) < 2 or message.command[1].lower() not in WORDS:
        return await message.reply_text("<blockquote>Usage: <code>/setmode easy</code> | <code>medium</code> | <code>hard</code></blockquote>", parse_mode=ParseMode.HTML)

    mode = message.command[1].lower()
    DB.execute("UPDATE settings SET default_diff=? WHERE chat_id=?", (mode, message.chat.id))
    DB.commit()
    await message.reply_text(f"<blockquote>✅ Default mode updated to <b>{mode.upper()}</b>!</blockquote>", parse_mode=ParseMode.HTML)

# ============================================================
# ANSWER PROCESSOR
# ============================================================

ALL_BOT_COMMANDS = {
    "start", "help", "jumble", "new", "hint", "skip", "settings", "setting", "setmode",
    "settimer", "stats", "stat", "score", "profile", "leaderboard", "lb", "top", "rank",
    "daily", "bonus", "auth", "unauth", "authlist", "addword", "delword"
}

@app.on_message(filters.text & filters.group)
async def group_answer_handler(_, message: Message):
    if not message.from_user or not message.text:
        return

    txt = message.text.strip()
    if txt.startswith(("/", "!", ".")):
        candidate = txt[1:].split()[0].split("@")[0].lower()
        if candidate in ALL_BOT_COMMANDS:
            return

    chat_id = message.chat.id
    user_id = message.from_user.id
    cleaned_input = clean_answer(txt)

    if not cleaned_input:
        return

    game = DB.execute("SELECT * FROM games WHERE chat_id=? AND solved=0", (chat_id,)).fetchone()
    if not game or time.time() > game["expires"]:
        return

    if cleaned_input == clean_answer(game["word"]):
        updated = DB.execute("UPDATE games SET solved=1 WHERE chat_id=? AND solved=0", (chat_id,))
        if updated.rowcount != 1:
            return
        DB.commit()

        ensure_user(message.from_user)
        u = get_user(user_id)
        pts_reward = get_global_config(f"points_{game['difficulty']}", 10)
        new_streak = u["streak"] + 1
        best = max(new_streak, u["best_streak"])

        DB.execute("""
            UPDATE users SET points=points+?, solved=solved+1, streak=?, best_streak=?
            WHERE user_id=?
        """, (pts_reward, new_streak, best, user_id))

        DB.execute("""
            INSERT INTO score_history (user_id, chat_id, points, timestamp)
            VALUES (?, ?, ?, ?)
        """, (user_id, chat_id, pts_reward, time.time()))
        DB.commit()

        u_mention = get_mention(message.from_user)
        await message.reply_text(
            f"<blockquote>🎉 <b>𝐂𝐎𝐑𝐑𝐄𝐂𝐓 𝐀𝐍𝐒𝐖𝐄𝐑!</b>\n\n"
            f"👤 <b>Winner:</b> {u_mention}\n"
            f"✅ <b>Word:</b> <code>{game['word'].upper()}</code>\n"
            f"⭐ <b>Points Won:</b> <code>+{pts_reward} pts</code>\n"
            f"🔥 <b>Active Streak:</b> <code>{new_streak}</code>\n\n"
            f"🔄 <i>Next puzzle coming in 3 seconds...</i></blockquote>",
            parse_mode=ParseMode.HTML
        )

        await asyncio.sleep(3)
        s = get_settings(chat_id)
        if s["is_active"]:
            next_diff = s["default_diff"] if "default_diff" in s.keys() else "medium"
            asyncio.create_task(start_game(chat_id, next_diff, chat_id))

# ============================================================
# START BOT
# ============================================================

if __name__ == "__main__":
    print("🚀 Capsule UI Rich Jumble Bot Running (No Inline Buttons)...")
    app.run()
