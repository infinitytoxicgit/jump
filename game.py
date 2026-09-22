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
from pyrogram.errors import MessageNotModified
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    Message,
    ChatMemberUpdated
)

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
SUPPORT_GC = "https://t.me/Roohi_Soul_Gc"
ADD_ME_URL = "https://t.me/Jumbles_Words_Bot?startgroup=true"
MUSIC_BOT_URL = "https://t.me/Roohi_Queen_Bot?start=_tgr_yN-6yUs4ZmRh"

app = Client(
    "advanced_jumble_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

DB = sqlite3.connect("jumble_game.db", check_same_thread=False)
DB.row_factory = sqlite3.Row
LOCK = asyncio.Lock()

# ============================================================
# WORD BANKS
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

CREATE TABLE IF NOT EXISTS group_adders (
    chat_id INTEGER PRIMARY KEY,
    user_id INTEGER,
    added_at REAL
);

CREATE TABLE IF NOT EXISTS group_bonus (
    chat_id INTEGER PRIMARY KEY,
    user_id INTEGER,
    claimed_at REAL
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
# GRAPHICS ENGINE (PIL / STATS / PUZZLE)
# ============================================================

def get_font(size):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"
    ]
    for path in paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()

def draw_pill(draw, coords, radius, fill):
    x1, y1, x2, y2 = coords
    draw.rounded_rectangle([x1, y1, x2, y2], radius=radius, fill=fill)

def generate_stats_card(user_data, rank_str="Unranked"):
    img = Image.new("RGB", (900, 520), "#0b0f19")
    draw = ImageDraw.Draw(img)

    f_title = get_font(36)
    f_sub = get_font(22)
    f_val = get_font(30)
    f_lbl = get_font(18)

    draw_pill(draw, (20, 20, 880, 500), 24, "#131b2e")

    # Header
    name_clean = user_data['name'][:22].upper()
    draw.text((50, 45), f"PILOT: {name_clean}", font=f_title, fill="#38bdf8")
    draw.text((50, 95), f"ID: {user_data['user_id']}  •  GLOBAL TIER: {rank_str}", font=f_sub, fill="#94a3b8")

    boxes = [
        ("⭐ TOTAL POINTS", f"{user_data['points']:,}", "#fbbf24", (50, 150, 420, 255)),
        ("🧩 WORDS SOLVED", f"{user_data['solved']:,}", "#34d399", (460, 150, 830, 255)),
        ("🔥 CURRENT STREAK", f"{user_data['streak']} (Best: {user_data['best_streak']})", "#f87171", (50, 280, 420, 385)),
        ("⚔️ PVP RECORD", f"{user_data['fight_wins']}W / {user_data['fight_losses']}L", "#c084fc", (460, 280, 830, 385))
    ]

    for title, val, color, box in boxes:
        draw_pill(draw, box, 16, "#1e293b")
        draw.text((box[0] + 20, box[1] + 20), title, font=f_lbl, fill=color)
        draw.text((box[0] + 20, box[1] + 55), val, font=f_val, fill="#ffffff")

    # Win-rate meter
    total_fights = user_data['fight_wins'] + user_data['fight_losses']
    rate = (user_data['fight_wins'] / total_fights) if total_fights > 0 else 0.0
    draw.text((50, 410), f"WIN PROBABILITY: {rate*100:.1f}%", font=f_lbl, fill="#94a3b8")

    draw_pill(draw, (50, 440, 830, 465), 12, "#334155")
    fill_end = 50 + int(780 * rate)
    if fill_end > 60:
        draw_pill(draw, (50, 440, fill_end, 465), 12, "#38bdf8")

    bio = io.BytesIO()
    bio.name = "dossier.png"
    img.save(bio, "PNG")
    bio.seek(0)
    return bio

def make_puzzle_image(jumbled, mode_tag, puzzle_id):
    img = Image.new("RGB", (1200, 650), "#0a0e17")
    draw = ImageDraw.Draw(img)

    f_title = get_font(48)
    f_sub = get_font(32)

    length = len(jumbled)
    if length <= 7:
        text_spaced = "   ".join(jumbled)
        f_word = get_font(85)
    elif length <= 11:
        text_spaced = "  ".join(jumbled)
        f_word = get_font(65)
    else:
        text_spaced = " ".join(jumbled)
        f_word = get_font(48)

    draw_pill(draw, (40, 40, 1160, 610), 30, "#151e32")
    draw.text((600, 100), "🧩 UNSCRAMBLE CIPHER", anchor="mm", font=f_title, fill="#38bdf8")
    draw.text((600, 310), text_spaced, anchor="mm", font=f_word, fill="#f8fafc")
    draw.text((600, 480), f"TIER: {mode_tag.upper()}  •  PUZZLE #{puzzle_id}", anchor="mm", font=f_sub, fill="#94a3b8")
    draw.text((600, 540), "Type solution directly into chat", anchor="mm", font=f_sub, fill="#38bdf8")

    bio = io.BytesIO()
    bio.name = f"puzzle_{puzzle_id}.png"
    img.save(bio, "PNG")
    bio.seek(0)
    return bio

# ============================================================
# HELPERS & DB WRAPPERS
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
    return bool(user_id and int(user_id) == int(OWNER_ID))

def is_authed(user_id):
    if not user_id:
        return False
    if is_owner(user_id):
        return True
    return bool(DB.execute("SELECT user_id FROM auth_users WHERE user_id=?", (int(user_id),)).fetchone())

def get_global_config(key, default_val):
    row = DB.execute("SELECT value FROM bot_config WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default_val

def set_global_config(key, val):
    DB.execute("""
        INSERT INTO bot_config (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
    """, (key, val))
    DB.commit()

async def is_admin_or_owner(chat, user_id):
    if is_owner(user_id) or chat.type == ChatType.PRIVATE:
        return True
    try:
        m = await chat.get_member(user_id)
        return m.status in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR)
    except Exception:
        return False

def get_settings(chat_id):
    row = DB.execute("SELECT * FROM settings WHERE chat_id=?", (chat_id,)).fetchone()
    if not row:
        DB.execute("INSERT INTO settings(chat_id) VALUES (?) ON CONFLICT DO NOTHING", (chat_id,))
        DB.commit()
        row = DB.execute("SELECT * FROM settings WHERE chat_id=?", (chat_id,)).fetchone()
    return row

def is_group(message):
    return message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)

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
        res = "".join(letters)
        if res != word and res[::-1] != word:
            return res.upper()
    return "".join(letters).upper()

def choose_word(chat_id, difficulty):
    pool = WORDS.get(difficulty, [])[:]
    used = {r["word"] for r in DB.execute("SELECT word FROM used_words WHERE chat_id=? AND difficulty=?", (chat_id, difficulty)).fetchall()}
    avail = [w for w in pool if w not in used]

    if not avail:
        DB.execute("DELETE FROM used_words WHERE chat_id=? AND difficulty=?", (chat_id, difficulty))
        DB.commit()
        avail = pool

    if not avail:
        return "JUMBLE"

    w = random.choice(avail)
    DB.execute("INSERT OR IGNORE INTO used_words(chat_id, difficulty, word) VALUES (?, ?, ?)", (chat_id, difficulty, w))
    DB.commit()
    return w

async def safe_delete_and_unpin(chat_id: int, message_id: int):
    if not message_id:
        return
    try:
        await app.unpin_chat_message(chat_id, message_id)
    except Exception:
        pass
    try:
        await app.delete_messages(chat_id, message_id)
    except Exception:
        pass

async def delete_after(msg: Message, delay: int = 5):
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except Exception:
        pass

# ============================================================
# UI BUTTONS & CONTROLS
# ============================================================

def normal_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💡 Reveal Hint", callback_data="hint"),
            InlineKeyboardButton("⏭️ Skip Turn", callback_data="skip")
        ],
        [
            InlineKeyboardButton("🔀 Next Puzzle", callback_data="newword"),
            InlineKeyboardButton("⚙️ Settings", callback_data="open_settings")
        ]
    ])

def fight_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💡 Reveal Duel Hint", callback_data="fight_hint")
        ]
    ])

# ============================================================
# GAME CYCLER
# ============================================================

JUMBLE_FIGHT = {}
FIGHT_LOBBY = {}

async def start_game(chat_id, difficulty, message_or_chat):
    if chat_id in JUMBLE_FIGHT:
        return

    settings = get_settings(chat_id)
    if not settings["is_active"]:
        return

    old = DB.execute("SELECT message_id FROM games WHERE chat_id=?", (chat_id,)).fetchone()
    if old and settings["auto_delete"] and old["message_id"]:
        await safe_delete_and_unpin(chat_id, old["message_id"])

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

    image = make_puzzle_image(jumbled, difficulty, puzzle_id)
    caption = (
        f"<b>┌── 🧩 JUMBLE #{puzzle_id} ──┐</b>\n"
        f"│ 🎯 <b>Tier:</b> <code>{difficulty.upper()}</code>\n"
        f"│ ⏱️ <b>Timer:</b> <code>{timer_val // 60}m {timer_val % 60}s</code>\n"
        f"│ ⭐ <b>Bounty:</b> <code>+{reward_pts} pts</code>\n"
        f"│ 💡 <b>Hints Limit:</b> <code>{hint_limit}/user</code>\n"
        f"<b>└──────────────────┘</b>\n\n"
        f"<blockquote expandable>"
        f"🔤 <i>Type the unscrambled word directly into the chat to claim points.</i>"
        f"</blockquote>"
    )

    try:
        if isinstance(message_or_chat, Message):
            sent = await message_or_chat.reply_photo(photo=image, caption=caption, reply_markup=normal_keyboard(), parse_mode=ParseMode.HTML)
        else:
            sent = await app.send_photo(chat_id, photo=image, caption=caption, reply_markup=normal_keyboard(), parse_mode=ParseMode.HTML)

        DB.execute("UPDATE games SET message_id=? WHERE chat_id=?", (sent.id, chat_id))
        DB.commit()
        try:
            await sent.pin(disable_notification=True)
        except Exception:
            pass
    except Exception as e:
        print(f"Error initiating puzzle: {e}")

    asyncio.create_task(expire_game(chat_id, puzzle_id, expires))

async def expire_game(chat_id, puzzle_id, expires):
    await asyncio.sleep(max(0, expires - time.time()))
    if chat_id in JUMBLE_FIGHT:
        return

    row = DB.execute("SELECT * FROM games WHERE chat_id=? AND puzzle_id=?", (chat_id, puzzle_id)).fetchone()
    if not row or row["solved"]:
        return

    DB.execute("UPDATE games SET solved=1 WHERE chat_id=?", (chat_id,))
    DB.commit()

    s = get_settings(chat_id)
    if s["auto_delete"] and row["message_id"]:
        await safe_delete_and_unpin(chat_id, row["message_id"])

    try:
        exp_msg = await app.send_message(
            chat_id,
            f"<b>┌── ⌛ TIME RUN OUT ──┐</b>\n"
            f"│ ❌ Puzzle left unresolved.\n"
            f"│ ✅ <b>Word was:</b> <code>{row['word'].upper()}</code>\n"
            f"<b>└───────────────────┘</b>\n\n"
            f"<i>Next puzzle spinning up in 3s...</i>",
            parse_mode=ParseMode.HTML
        )
        if s["auto_delete"]:
            asyncio.create_task(delete_after(exp_msg, 4))
    except Exception:
        pass

    await asyncio.sleep(3)
    s = get_settings(chat_id)
    if chat_id not in JUMBLE_FIGHT and s["is_active"]:
        asyncio.create_task(start_game(chat_id, s["default_diff"], chat_id))

# ============================================================
# PVP COMBAT ENGINE
# ============================================================

async def fight_next(chat_id):
    game = JUMBLE_FIGHT.get(chat_id)
    if not game:
        return

    curr = asyncio.current_task()
    if game.get("task") and game["task"] is not curr and not game["task"].done():
        try:
            game["task"].cancel()
        except Exception:
            pass

    game["round"] += 1
    if game["round"] > 10:
        await finish_fight(chat_id)
        return

    diff = game["difficulty"]
    word = random.choice(WORDS[diff])
    jumbled = jumble_word(word)

    game["word"] = word
    game["expires"] = time.time() + game["timer"]

    per_round_hints = int(get_global_config(f"hints_{diff}", 3))
    game["max_hints"] = per_round_hints
    game["hints_left"] = {p: per_round_hints for p in game["players"]}
    game["round_revealed"] = {p: [] for p in game["players"]}

    fight_tag = "BET MATCH" if game.get("is_bet") else "DUEL"
    image = make_puzzle_image(jumbled, f"{fight_tag} {diff.upper()}", game["round"])

    p1, p2 = game["players"]
    extra_pot = f"\n│ 💰 <b>Total Pot:</b> <code>{game.get('bet_amount') * 2} pts</code>" if game.get("is_bet") else ""

    caption = (
        f"<b>┌── ⚔️ {fight_tag}: ROUND {game['round']}/10 ──┐</b>\n"
        f"│ 🎯 <b>Tier:</b> <code>{diff.upper()}</code>\n"
        f"│ ⏱️ <b>Clock:</b> <code>{game['timer']}s</code>{extra_pot}\n"
        f"│ 💡 <b>Round Hints:</b> <code>{per_round_hints} each</code>\n"
        f"│ 👥 <b>Rivals:</b> {game['mentions'][p1]} ⚔️ {game['mentions'][p2]}\n"
        f"<b>└──────────────────────────────┘</b>\n\n"
        f"<blockquote expandable>"
        f"⚡ <i>Type solution in chat to score first and conquer the round!</i>"
        f"</blockquote>"
    )

    try:
        sent = await app.send_photo(chat_id, photo=image, caption=caption, reply_markup=fight_keyboard(), parse_mode=ParseMode.HTML)
        game["msg_id"] = sent.id
        try:
            await sent.pin(disable_notification=True)
        except Exception:
            pass
    except Exception as e:
        print(f"Fight dispatch error: {e}")

    game["task"] = asyncio.create_task(fight_timeout_task(chat_id, game["round"], game["timer"]))

async def fight_timeout_task(chat_id, round_num, timer_duration):
    await asyncio.sleep(timer_duration)
    advance = False
    async with LOCK:
        game = JUMBLE_FIGHT.get(chat_id)
        if game and game["round"] == round_num:
            w = game["word"]
            s = get_settings(chat_id)
            if s["auto_delete"] and game.get("msg_id"):
                await safe_delete_and_unpin(chat_id, game["msg_id"])

            try:
                t_msg = await app.send_message(
                    chat_id,
                    f"<b>┌── ⌛ ROUND {round_num} OVER ──┐</b>\n"
                    f"│ ❌ No solver hit the target.\n"
                    f"│ ✅ <b>Word was:</b> <code>{w.upper()}</code>\n"
                    f"<b>└────────────────────────┘</b>",
                    parse_mode=ParseMode.HTML
                )
                if s["auto_delete"]:
                    asyncio.create_task(delete_after(t_msg, 4))
            except Exception:
                pass
            advance = True

    if advance:
        await asyncio.sleep(2)
        asyncio.create_task(fight_next(chat_id))

async def finish_fight(chat_id):
    game = JUMBLE_FIGHT.pop(chat_id, None)
    if not game:
        return

    p1, p2 = game["players"]
    s1, s2 = game["scores"][p1], game["scores"][p2]
    now = time.time()

    if s1 > s2:
        winner, loser = p1, p2
    elif s2 > s1:
        winner, loser = p2, p1
    else:
        winner = loser = None

    if not game.get("is_bet"):
        if winner:
            DB.execute("UPDATE users SET fight_wins=fight_wins+1 WHERE user_id=?", (winner,))
            DB.execute("UPDATE users SET fight_losses=fight_losses+1 WHERE user_id=?", (loser,))
            DB.commit()
            res = (
                f"<b>┌── 🏆 DUEL CONCLUDED ──┐</b>\n"
                f"│ 🥇 <b>Champion:</b> {game['mentions'][winner]} (<code>{game['scores'][winner]} pts</code>)\n"
                f"│ 🥈 <b>Contender:</b> {game['mentions'][loser]} (<code>{game['scores'][loser]} pts</code>)\n"
                f"<b>└──────────────────────┘</b>"
            )
        else:
            res = (
                f"<b>┌── 🤝 DUEL TIED ──┐</b>\n"
                f"│ Score leveled at <code>{s1} - {s2}</code>.\n"
                f"<b>└─────────────────┘</b>"
            )
    else:
        amt = game["bet_amount"]
        if winner:
            pot = amt * 2
            win_cut = int(pot * 0.75)
            lose_cashback = pot - win_cut

            DB.execute("UPDATE users SET points=points+?, bet_wins=bet_wins+1 WHERE user_id=?", (win_cut, winner))
            DB.execute("UPDATE users SET points=points+?, bet_losses=bet_losses+1 WHERE user_id=?", (lose_cashback, loser))
            DB.execute("INSERT INTO score_history (user_id, chat_id, points, timestamp) VALUES (?, ?, ?, ?)", (winner, chat_id, win_cut, now))
            DB.execute("INSERT INTO score_history (user_id, chat_id, points, timestamp) VALUES (?, ?, ?, ?)", (loser, chat_id, lose_cashback, now))
            DB.commit()

            res = (
                f"<b>┌── 💰 HIGH STAKES SETTLED ──┐</b>\n"
                f"│ 🥇 <b>Victor:</b> {game['mentions'][winner]} (<code>+{win_cut:,} pts</code>)\n"
                f"│ 🛡️ <b>Cashback:</b> {game['mentions'][loser]} (<code>+{lose_cashback:,} pts</code>)\n"
                f"<b>└───────────────────────────┘</b>"
            )
        else:
            DB.execute("UPDATE users SET points=points+? WHERE user_id=?", (amt, p1))
            DB.execute("UPDATE users SET points=points+? WHERE user_id=?", (amt, p2))
            DB.commit()
            res = f"<b>┌── 🤝 STAKES RESTORED ──┐</b>\n│ Tied battle: <code>{amt:,} pts</code> refunded."

    await app.send_message(chat_id, res, parse_mode=ParseMode.HTML)
    await asyncio.sleep(3)

    s = get_settings(chat_id)
    if s["is_active"]:
        asyncio.create_task(start_game(chat_id, s["default_diff"], chat_id))

# ============================================================
# COMMAND & EVENT HANDLERS
# ============================================================

async def resolve_target_user(message: Message):
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user

    args = message.command[1:] if len(message.command) > 1 else []
    if args:
        arg = args[0]
        try:
            return await app.get_users(int(arg) if arg.isdigit() else arg)
        except Exception:
            pass

    if message.entities:
        for ent in message.entities:
            if ent.type.name == "TEXT_MENTION" and ent.user:
                return ent.user

    return message.from_user

@app.on_message(filters.command(["stats", "stat", "score", "profile"]))
async def user_stats_cmd(_, message: Message):
    target = await resolve_target_user(message)
    if not target:
        return await message.reply_text("❌ User could not be identified.")

    ensure_user(target)
    u = get_user(target.id)

    rank_row = DB.execute("SELECT COUNT(*) + 1 AS rank FROM users WHERE points > ?", (u["points"],)).fetchone()
    rank_str = f"#{rank_row['rank']}" if rank_row else "Unranked"

    img_card = generate_stats_card(u, rank_str)

    # Rich Text Monospace Table
    table_card = (
        f"<blockquote>"
        f"┌─ <b>TELEMETRY DOSSIER</b>\n"
        f"│ 👤 <b>Agent:</b> {get_mention(target)}\n"
        f"│ 🆔 <b>ID:</b> <code>{target.id}</code>\n"
        f"│ 🏆 <b>Global Stand:</b> <code>{rank_str}</code>\n"
        f"├───────────────────────────\n"
        f"│ ⭐ <b>Score:</b>  <code>{u['points']:,} pts</code>\n"
        f"│ 🧩 <b>Solved:</b> <code>{u['solved']:,} words</code>\n"
        f"│ 🔥 <b>Streak:</b> <code>{u['streak']}</code> (Peak: <code>{u['best_streak']}</code>)\n"
        f"│ ⚔️ <b>Duels:</b>  <code>{u['fight_wins']}W - {u['fight_losses']}L</code>\n"
        f"│ 💰 <b>Stakes:</b> <code>{u['bet_wins']}W - {u['bet_losses']}L</code>\n"
        f"└───────────────────────────</blockquote>"
    )

    await message.reply_photo(photo=img_card, caption=table_card, parse_mode=ParseMode.HTML)

@app.on_message(filters.command(["leaderboard", "top", "rank", "lb"]))
async def leaderboard_cmd(_, message: Message):
    chat_id = message.chat.id
    scope = "daily" if is_group(message) else "global"
    text, kb = build_rich_leaderboard(scope, chat_id)
    await message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

def build_rich_leaderboard(scope_type, chat_id):
    now = time.time()
    if scope_type == "daily":
        since = now - 86400
        title = "DAILY SPRINT (24H GC)"
        rows = DB.execute("""
            SELECT h.user_id, u.name, u.username, u.is_private, SUM(h.points) as total_pts
            FROM score_history h
            LEFT JOIN users u ON h.user_id = u.user_id
            WHERE h.chat_id = ? AND h.timestamp >= ?
            GROUP BY h.user_id
            HAVING total_pts > 0
            ORDER BY total_pts DESC
            LIMIT 10
        """, (chat_id, since)).fetchall()
    elif scope_type == "weekly":
        since = now - (86400 * 7)
        title = "WEEKLY ARENA (7D GC)"
        rows = DB.execute("""
            SELECT h.user_id, u.name, u.username, u.is_private, SUM(h.points) as total_pts
            FROM score_history h
            LEFT JOIN users u ON h.user_id = u.user_id
            WHERE h.chat_id = ? AND h.timestamp >= ?
            GROUP BY h.user_id
            HAVING total_pts > 0
            ORDER BY total_pts DESC
            LIMIT 10
        """, (chat_id, since)).fetchall()
    elif scope_type == "monthly":
        since = now - (86400 * 30)
        title = "MONTHLY GLOBAL (30D)"
        rows = DB.execute("""
            SELECT h.user_id, u.name, u.username, u.is_private, SUM(h.points) as total_pts
            FROM score_history h
            LEFT JOIN users u ON h.user_id = u.user_id
            WHERE h.timestamp >= ?
            GROUP BY h.user_id
            HAVING total_pts > 0
            ORDER BY total_pts DESC
            LIMIT 10
        """, (since,)).fetchall()
    else:
        title = "GLOBAL SUPREMACY"
        rows = DB.execute("""
            SELECT user_id, name, username, is_private, points as total_pts
            FROM users
            WHERE points > 0
            ORDER BY points DESC
            LIMIT 10
        """).fetchall()

    table_lines = [
        f"<b>┌── 🏆 {title} ──┐</b>",
        f"│ <code>{'RNK':<3} | {'OPERATIVE':<12} | {'PTS':>7}</code>",
        "├───────────────────────────┤"
    ]

    if not rows:
        table_lines.append("│ <i>No activity recorded yet.</i>")
    else:
        for i, u in enumerate(rows, 1):
            raw_name = (u["name"] or "Player")[:11]
            u_clean = html.escape(raw_name)
            pts_str = f"{u['total_pts']:,}"
            table_lines.append(f"│ <code>{i:<3} | {u_clean:<12} | {pts_str:>7}</code>")

    table_lines.append("<b>└───────────────────────────┘</b>")
    formatted_card = "\n".join(table_lines)

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"{'🟢 ' if scope_type=='daily' else ''}Daily", callback_data=f"lb_daily_{chat_id}"),
            InlineKeyboardButton(f"{'🟡 ' if scope_type=='weekly' else ''}Weekly", callback_data=f"lb_weekly_{chat_id}")
        ],
        [
            InlineKeyboardButton(f"{'🟣 ' if scope_type=='monthly' else ''}Monthly", callback_data=f"lb_monthly_{chat_id}"),
            InlineKeyboardButton(f"{'🌐 ' if scope_type=='global' else ''}Global", callback_data=f"lb_global_{chat_id}")
        ],
        [InlineKeyboardButton("❌ Dismiss", callback_data="close_panel")]
    ])

    return formatted_card, kb

@app.on_message(filters.command("start"))
async def start_cmd(_, message: Message):
    ensure_user(message.from_user)
    text = (
        "<b>┌── ⚡ ADVANCED JUMBLE ENGINE ──┐</b>\n"
        "│ High-speed word unscrambling with\n"
        "│ integrated 1v1 PvP combat arena.\n"
        "<b>└────────────────────────────────┘</b>\n\n"
        "<blockquote expandable>"
        "🎮 <b>Battle Operations:</b>\n"
        "• <code>/jumble</code> — Trigger game loop\n"
        "• <code>/jumblefight @user</code> — Issue 1v1 Duel\n"
        "• <code>/betfight [mode] [amt] @user</code> — High Stakes\n"
        "• <code>/settings</code> — Admin configurations\n\n"
        "📊 <b>Telemetry & Rewards:</b>\n"
        "• <code>/stats [@user]</code> — Visual player dossier\n"
        "• <code>/leaderboard</code> — Hall of fame\n"
        "• <code>/daily</code> — 24h bonus in direct message\n"
        "• <code>/bonus</code> — Group admin rewards"
        "</blockquote>"
    )

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💬 Support HQ", url=SUPPORT_GC),
            InlineKeyboardButton("➕ Add Bot", url=ADD_ME_URL)
        ],
        [InlineKeyboardButton("˹ 𓆩ℛᴏ֟፝ᴏʜɪ ꭙ 𝐌ᴜ֟፝sɪᴄ𓆪˼ ♪", url=MUSIC_BOT_URL)]
    ])

    if message.chat.type == ChatType.PRIVATE:
        try:
            await message.reply_photo(photo=START_IMG, caption=text, reply_markup=kb, parse_mode=ParseMode.HTML)
        except Exception:
            await message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    else:
        await message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

@app.on_message(filters.command("jumble"))
async def jumble_cmd(_, message: Message):
    ensure_user(message.from_user)
    if message.chat.id in JUMBLE_FIGHT:
        return await message.reply_text("<blockquote>⚔️ <b>PvP duel currently engaging. Wait for victory.</b></blockquote>", parse_mode=ParseMode.HTML)

    DB.execute("UPDATE settings SET is_active=1 WHERE chat_id=?", (message.chat.id,))
    DB.commit()

    s = get_settings(message.chat.id)
    default_d = s["default_diff"]
    diff = message.command[1].lower() if len(message.command) > 1 and message.command[1].lower() in WORDS else default_d
    await start_game(message.chat.id, diff, message)

@app.on_message(filters.command(["jumblefight", "fight"]))
async def fight_cmd(_, message: Message):
    if not is_group(message):
        return await message.reply_text("<blockquote>❌ Group engagement only.</blockquote>", parse_mode=ParseMode.HTML)

    target = await resolve_target_user(message)
    if not target or target.id == message.from_user.id or target.is_bot:
        return await message.reply_text("<blockquote>❌ Mention or reply to a valid rival to challenge.</blockquote>", parse_mode=ParseMode.HTML)

    ensure_user(message.from_user)
    ensure_user(target)
    cid = message.chat.id

    if cid in JUMBLE_FIGHT:
        return await message.reply_text("<blockquote>⚔️ Active duel in progress.</blockquote>", parse_mode=ParseMode.HTML)

    FIGHT_LOBBY[cid] = {
        "p1": message.from_user.id,
        "p2": target.id,
        "p1_name": message.from_user.first_name,
        "p2_name": target.first_name,
        "m1": get_mention(message.from_user),
        "m2": get_mention(target),
        "difficulty": "medium",
        "timer": 60,
        "is_bet": False,
        "bet_amount": 0
    }

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🟢 Easy", callback_data="f_diff_easy"),
            InlineKeyboardButton("🟡 Medium", callback_data="f_diff_medium"),
            InlineKeyboardButton("🔴 Hard", callback_data="f_diff_hard")
        ],
        [
            InlineKeyboardButton("⏱️ 30s", callback_data="f_time_30"),
            InlineKeyboardButton("⏱️ 60s", callback_data="f_time_60")
        ],
        [
            InlineKeyboardButton("⚔️ Accept Duel", callback_data="f_accept"),
            InlineKeyboardButton("🚫 Decline", callback_data="f_decline")
        ]
    ])

    await message.reply_text(
        f"<b>┌── ⚔️ DUEL CHALLENGE STAGED ──┐</b>\n"
        f"│ 👤 <b>Initiator:</b> {get_mention(message.from_user)}\n"
        f"│ 🎯 <b>Target:</b> {get_mention(target)}\n"
        f"│ ⚙️ <b>Config:</b> Medium Tier • 60s Round Timer\n"
        f"<b>└───────────────────────────────┘</b>\n\n"
        f"<i>Rival must tap Accept below to commence!</i>",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )

@app.on_message(filters.command(["jumblebetfight", "betfight"]))
async def bet_cmd(_, message: Message):
    if not is_group(message):
        return await message.reply_text("<blockquote>❌ Group engagement only.</blockquote>", parse_mode=ParseMode.HTML)

    target = await resolve_target_user(message)
    if not target or target.id == message.from_user.id or target.is_bot:
        return await message.reply_text("<blockquote>❌ Mention or reply to a valid rival to bet against.</blockquote>", parse_mode=ParseMode.HTML)

    amount = 100
    diff = "medium"
    for p in message.command[1:]:
        if p.isdigit() and int(p) >= 100:
            amount = int(p)
        elif p.lower() in ("easy", "medium", "hard"):
            diff = p.lower()

    u1 = get_user(message.from_user.id)
    u2 = get_user(target.id)

    if not u1 or u1["points"] < amount:
        return await message.reply_text(f"<blockquote>❌ Insufficient points ({amount} pts required).</blockquote>", parse_mode=ParseMode.HTML)
    if not u2 or u2["points"] < amount:
        return await message.reply_text(f"<blockquote>❌ Rival lacks balance ({amount} pts required).</blockquote>", parse_mode=ParseMode.HTML)

    cid = message.chat.id
    FIGHT_LOBBY[cid] = {
        "p1": message.from_user.id,
        "p2": target.id,
        "p1_name": message.from_user.first_name,
        "p2_name": target.first_name,
        "m1": get_mention(message.from_user),
        "m2": get_mention(target),
        "difficulty": diff,
        "timer": 60,
        "is_bet": True,
        "bet_amount": amount
    }

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🟢 Easy", callback_data="f_diff_easy"),
            InlineKeyboardButton("🟡 Medium", callback_data="f_diff_medium"),
            InlineKeyboardButton("🔴 Hard", callback_data="f_diff_hard")
        ],
        [
            InlineKeyboardButton("⏱️ 30s", callback_data="f_time_30"),
            InlineKeyboardButton("⏱️ 60s", callback_data="f_time_60")
        ],
        [
            InlineKeyboardButton("💰 Accept Stakes", callback_data="f_accept"),
            InlineKeyboardButton("🚫 Decline", callback_data="f_decline")
        ]
    ])

    await message.reply_text(
        f"<b>┌── 💰 HIGH STAKES DUEL STAGED ──┐</b>\n"
        f"│ 👤 <b>Host:</b> {get_mention(message.from_user)}\n"
        f"│ 🎯 <b>Rival:</b> {get_mention(target)}\n"
        f"│ 💵 <b>Stake:</b> <code>{amount:,} pts</code> (Pot: <code>{amount*2:,} pts</code>)\n"
        f"│ 🛡️ <b>Split:</b> 75% Victor • 25% Cashback\n"
        f"<b>└─────────────────────────────────┘</b>",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )

# ============================================================
# CHAT ANSWER INGESTION (NON-BLOCKING)
# ============================================================

ALL_CMDS = {
    "start", "help", "jumble", "jumblefight", "fight", "rapido", "jumblebetfight", "betfight",
    "settings", "setting", "setpoints", "sethint", "setdaily", "setbonus", "daily", "bonus",
    "private", "public", "addword", "addwords", "delword", "delallword", "delallwords",
    "clearword", "clearwords", "word", "words", "auth", "unauth", "authlist", "update", "gitpull",
    "stats", "stat", "mystats", "score", "profile", "leaderboard", "top", "rank", "lb"
}

@app.on_message(filters.text & filters.group, group=1)
async def chat_message_verifier(_, message: Message):
    if not message.from_user or not message.text:
        return

    txt = message.text.strip()
    if txt.startswith(("/", "!", ".")):
        candidate = txt[1:].split()[0].split("@")[0].lower()
        if candidate in ALL_CMDS:
            return

    chat_id = message.chat.id
    user_id = message.from_user.id
    cleaned = clean_answer(txt)
    if not cleaned:
        return

    # 1. Duel check
    if chat_id in JUMBLE_FIGHT:
        async with LOCK:
            g = JUMBLE_FIGHT.get(chat_id)
            if not g or user_id not in g["players"]:
                return

            if time.time() <= g["expires"] and cleaned == clean_answer(g["word"]):
                curr = asyncio.current_task()
                if g.get("task") and g["task"] is not curr and not g["task"].done():
                    try:
                        g["task"].cancel()
                    except Exception:
                        pass

                g["scores"][user_id] += 1
                s = get_settings(chat_id)
                if s["auto_delete"] and g.get("msg_id"):
                    await safe_delete_and_unpin(chat_id, g["msg_id"])

                u_mention = get_mention(message.from_user)
                r_msg = await message.reply_text(
                    f"<blockquote>⚡ <b>ROUND WON BY {u_mention}!</b> Score: <code>{g['scores'][user_id]} pts</code></blockquote>",
                    parse_mode=ParseMode.HTML
                )
                if s["auto_delete"]:
                    asyncio.create_task(delete_after(r_msg, 4))

                await asyncio.sleep(2)
                asyncio.create_task(fight_next(chat_id))
                return
        return

    # 2. Main Game Loop Check
    g_row = DB.execute("SELECT * FROM games WHERE chat_id=? AND solved=0", (chat_id,)).fetchone()
    if not g_row or time.time() > g_row["expires"]:
        return

    if cleaned == clean_answer(g_row["word"]):
        upd = DB.execute("UPDATE games SET solved=1 WHERE chat_id=? AND solved=0", (chat_id,))
        if upd.rowcount != 1:
            return
        DB.commit()

        ensure_user(message.from_user)
        u = get_user(user_id)
        s = get_settings(chat_id)
        reward = get_global_config(f"points_{g_row['difficulty']}", 10)

        new_streak = u["streak"] + 1
        best = max(new_streak, u["best_streak"])

        DB.execute("UPDATE users SET points=points+?, solved=solved+1, streak=?, best_streak=? WHERE user_id=?", (reward, new_streak, best, user_id))
        DB.execute("INSERT INTO score_history (user_id, chat_id, points, timestamp) VALUES (?, ?, ?, ?)", (user_id, chat_id, reward, time.time()))
        DB.commit()

        if s["auto_delete"] and g_row["message_id"]:
            await safe_delete_and_unpin(chat_id, g_row["message_id"])

        u_mention = get_mention(message.from_user)
        c_msg = await message.reply_text(
            f"<b>┌── 🎉 UNSCRAMBLED! ──┐</b>\n"
            f"│ 👤 <b>Solver:</b> {u_mention}\n"
            f"│ ✅ <b>Word:</b> <code>{g_row['word'].upper()}</code>\n"
            f"│ ⭐ <b>Bounty:</b> <code>+{reward} pts</code>\n"
            f"│ 🔥 <b>Streak:</b> <code>{new_streak}</code>\n"
            f"<b>└─────────────────────┘</b>",
            parse_mode=ParseMode.HTML
        )
        if s["auto_delete"]:
            asyncio.create_task(delete_after(c_msg, 4))

        await asyncio.sleep(3)
        s = get_settings(chat_id)
        if chat_id not in JUMBLE_FIGHT and s["is_active"]:
            asyncio.create_task(start_game(chat_id, s["default_diff"], chat_id))

# ============================================================
# CALLBACK ROUTER
# ============================================================

@app.on_callback_query()
async def callback_router(_, query: CallbackQuery):
    data = query.data
    cid = query.message.chat.id
    uid = query.from_user.id

    if data == "hint":
        g = DB.execute("SELECT * FROM games WHERE chat_id=? AND solved=0", (cid,)).fetchone()
        if not g:
            return await query.answer("No active puzzle found.", show_alert=True)

        limit = get_global_config(f"hints_{g['difficulty']}", 3)
        h_row = DB.execute("SELECT * FROM puzzle_hints WHERE chat_id=? AND puzzle_id=? AND user_id=?", (cid, g["puzzle_id"], uid)).fetchone()
        hints_used = h_row["hints_used"] if h_row else 0
        rev = [int(i) for i in h_row["revealed_indices"].split(",") if i] if h_row else []

        if hints_used >= limit:
            return await query.answer(f"❌ Max {limit} hints exhausted for this puzzle.", show_alert=True)

        avail = [i for i in range(len(g["word"])) if i not in rev]
        if not avail:
            return await query.answer("❌ No more characters to reveal.", show_alert=True)

        idx = random.choice(avail)
        rev.append(idx)
        hints_used += 1

        DB.execute("""
            INSERT INTO puzzle_hints(chat_id, puzzle_id, user_id, hints_used, revealed_indices)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, puzzle_id, user_id) DO UPDATE SET
                hints_used=excluded.hints_used, revealed_indices=excluded.revealed_indices
        """, (cid, g["puzzle_id"], uid, hints_used, ",".join(map(str, rev))))
        DB.commit()

        letter = g["word"][idx].upper()
        return await query.answer(f"💡 Letter #{idx+1} is '{letter}' ({limit - hints_used} hints left)", show_alert=True)

    elif data == "fight_hint":
        g = JUMBLE_FIGHT.get(cid)
        if not g or uid not in g["players"]:
            return await query.answer("Duel combatants only.", show_alert=True)

        left = g["hints_left"].get(uid, 0)
        if left <= 0:
            return await query.answer("Hints exhausted for this round.", show_alert=True)

        w = g["word"]
        rev = g["round_revealed"][uid]
        avail = [i for i in range(len(w)) if i not in rev]
        if not avail:
            return await query.answer("All characters currently exposed.", show_alert=True)

        idx = random.choice(avail)
        rev.append(idx)
        g["hints_left"][uid] -= 1
        return await query.answer(f"💡 Letter #{idx+1} is '{w[idx].upper()}'", show_alert=True)

    elif data.startswith("lb_"):
        await query.answer()
        parts = data.split("_")
        scope = parts[1]
        target_cid = int(parts[2])

        text, kb = build_rich_leaderboard(scope, target_cid)
        try:
            await query.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        except MessageNotModified:
            pass

    elif data == "skip":
        if not await is_admin_or_owner(query.message.chat, uid):
            return await query.answer("Admin permission required to skip.", show_alert=True)

        g = DB.execute("SELECT * FROM games WHERE chat_id=? AND solved=0", (cid,)).fetchone()
        if not g:
            return await query.answer("No active puzzle.", show_alert=True)

        DB.execute("UPDATE games SET solved=1 WHERE chat_id=?", (cid,))
        DB.commit()

        await query.answer("Puzzle bypassed.")
        s = get_settings(cid)
        if s["is_active"]:
            asyncio.create_task(start_game(cid, s["default_diff"], query.message))

    elif data == "newword":
        g = DB.execute("SELECT * FROM games WHERE chat_id=? AND solved=0", (cid,)).fetchone()
        if g and time.time() <= g["expires"]:
            return await query.answer("Active puzzle is currently in progress.", show_alert=True)

        s = get_settings(cid)
        await query.answer("Cycling new puzzle...")
        asyncio.create_task(start_game(cid, s["default_diff"], query.message))

    elif data.startswith("f_"):
        lobby = FIGHT_LOBBY.get(cid)
        if not lobby:
            return await query.answer("Lobby expired.", show_alert=True)

        if data == "f_decline":
            if uid not in (lobby["p1"], lobby["p2"]):
                return await query.answer("Combatants only.", show_alert=True)
            del FIGHT_LOBBY[cid]
            await query.message.delete()
            return await query.answer("Duel dismissed.")

        if data == "f_accept":
            if uid != lobby["p2"]:
                return await query.answer("Only the rival player can accept.", show_alert=True)

            if lobby["is_bet"]:
                amt = lobby["bet_amount"]
                u1 = get_user(lobby["p1"])
                u2 = get_user(lobby["p2"])
                if u1["points"] < amt or u2["points"] < amt:
                    del FIGHT_LOBBY[cid]
                    return await query.message.edit_text("<blockquote>❌ Balance check failure. Duel canceled.</blockquote>", parse_mode=ParseMode.HTML)

                DB.execute("UPDATE users SET points=points-? WHERE user_id=?", (amt, lobby["p1"]))
                DB.execute("UPDATE users SET points=points-? WHERE user_id=?", (amt, lobby["p2"]))
                DB.commit()

            diff = lobby["difficulty"]
            per_round_hints = int(get_global_config(f"hints_{diff}", 3))

            JUMBLE_FIGHT[cid] = {
                "players": [lobby["p1"], lobby["p2"]],
                "names": {lobby["p1"]: lobby["p1_name"], lobby["p2"]: lobby["p2_name"]},
                "mentions": {lobby["p1"]: lobby["m1"], lobby["p2"]: lobby["m2"]},
                "round": 0,
                "scores": defaultdict(int),
                "word": None,
                "expires": None,
                "task": None,
                "difficulty": diff,
                "timer": lobby["timer"],
                "msg_id": None,
                "is_bet": lobby["is_bet"],
                "bet_amount": lobby["bet_amount"],
                "max_hints": per_round_hints,
                "hints_left": {lobby["p1"]: per_round_hints, lobby["p2"]: per_round_hints},
                "round_revealed": {lobby["p1"]: [], lobby["p2"]: []}
            }
            del FIGHT_LOBBY[cid]
            await query.message.delete()
            await query.answer("⚔️ Duel Activated!")
            asyncio.create_task(fight_next(cid))

        elif data.startswith("f_diff_"):
            lobby["difficulty"] = data.split("_")[2]
            await query.answer(f"Tier updated to {lobby['difficulty'].upper()}")
        elif data.startswith("f_time_"):
            lobby["timer"] = int(data.split("_")[2])
            await query.answer(f"Timer set to {lobby['timer']}s")

    elif data == "close_panel":
        await query.message.delete()

# ============================================================
# BOOT SEQUENCE
# ============================================================

async def resume_all_games():
    await asyncio.sleep(2)
    rows = DB.execute("SELECT chat_id, default_diff FROM settings WHERE is_active = 1 AND chat_id != 0").fetchall()
    for row in rows:
        try:
            DB.execute("DELETE FROM games WHERE chat_id=?", (row["chat_id"],))
            DB.commit()
            await start_game(row["chat_id"], row["default_diff"] or "medium", row["chat_id"])
            await asyncio.sleep(0.5)
        except Exception:
            pass

if __name__ == "__main__":
    print("🚀 Advanced Rich Jumble Bot is starting...")
    asyncio.get_event_loop().create_task(resume_all_games())
    app.run()
