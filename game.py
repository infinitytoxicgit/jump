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
from pyrogram.errors import MessageNotModified, RPCError
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    Message,
    ChatMemberUpdated
)

# ============================================================
# CONFIG & HARDCODED CREDENTIALS
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
# DATABASE SETUP & MIGRATIONS
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

    cols = [c[1] for c in DB.execute("PRAGMA table_info(settings)").fetchall()]
    if "default_diff" not in cols:
        DB.execute("ALTER TABLE settings ADD COLUMN default_diff TEXT DEFAULT 'medium'")
    if "is_active" not in cols:
        DB.execute("ALTER TABLE settings ADD COLUMN is_active INTEGER DEFAULT 1")
    if "auto_delete" not in cols:
        DB.execute("ALTER TABLE settings ADD COLUMN auto_delete INTEGER DEFAULT 0")

    user_cols = [c[1] for c in DB.execute("PRAGMA table_info(users)").fetchall()]
    if "fight_wins" not in user_cols:
        DB.execute("ALTER TABLE users ADD COLUMN fight_wins INTEGER DEFAULT 0")
    if "fight_losses" not in user_cols:
        DB.execute("ALTER TABLE users ADD COLUMN fight_losses INTEGER DEFAULT 0")
    if "bet_wins" not in user_cols:
        DB.execute("ALTER TABLE users ADD COLUMN bet_wins INTEGER DEFAULT 0")
    if "bet_losses" not in user_cols:
        DB.execute("ALTER TABLE users ADD COLUMN bet_losses INTEGER DEFAULT 0")
    if "is_private" not in user_cols:
        DB.execute("ALTER TABLE users ADD COLUMN is_private INTEGER DEFAULT 0")
    if "last_daily" not in user_cols:
        DB.execute("ALTER TABLE users ADD COLUMN last_daily REAL DEFAULT 0")

    try:
        users = DB.execute("SELECT user_id, points FROM users").fetchall()
        now = time.time()
        for u in users:
            uid = u["user_id"]
            real_pts = u["points"]
            history_sum_row = DB.execute("SELECT SUM(points) as total FROM score_history WHERE user_id = ?", (uid,)).fetchone()
            history_total = history_sum_row["total"] if history_sum_row and history_sum_row["total"] else 0

            diff = real_pts - history_total
            if diff != 0:
                DB.execute("INSERT INTO score_history (user_id, chat_id, points, timestamp) VALUES (?, 0, ?, ?)", (uid, diff, now))
        DB.commit()
    except Exception as e:
        print(f"Sync migration error: {e}")

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
# VISUAL GRAPHICS & HELPER UTILITIES
# ============================================================

def make_graph_bar(percentage: float, length: int = 10) -> str:
    clamped = max(0.0, min(100.0, float(percentage)))
    filled = int(round((clamped / 100.0) * length))
    empty = length - filled
    return "▰" * filled + "▱" * empty

def get_tier_badge(points: int) -> tuple:
    if points >= 10000:
        return "👑 𝐌𝐲𝐭𝐡𝐢𝐜", "⚡⚡⚡⚡⚡"
    elif points >= 5000:
        return "💎 𝐆𝐫𝐚𝐧𝐝𝐦𝐚𝐬𝐭𝐞𝐫", "⚡⚡⚡⚡"
    elif points >= 2500:
        return "🔥 𝐃𝐢𝐚𝐦𝐨𝐧𝐝", "⚡⚡⚡"
    elif points >= 1000:
        return "⚔️ 𝐏𝐥𝐚𝐭𝐢𝐧𝐮𝐦", "⚡⚡"
    elif points >= 300:
        return "🛡️ 𝐆𝐨𝐥𝐝", "⚡"
    elif points >= 100:
        return "🥈 𝐒𝐢𝐥𝐯𝐞𝐫", "•"
    return "🥉 𝐁𝐫𝐨𝐧𝐳𝐞", "•"

def ensure_user(user):
    if not user:
        return
    DB.execute("""
        INSERT INTO users(user_id, username, name)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username=excluded.username,
            name=excluded.name
    """, (
        user.id,
        user.username or "",
        user.first_name or "Player"
    ))
    DB.commit()

def get_user(user_id):
    return DB.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()

def is_owner(user_id):
    if not user_id:
        return False
    return int(user_id) == int(OWNER_ID)

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

def make_puzzle_image(jumbled, mode_tag, puzzle_id):
    img = Image.new("RGB", (1200, 650), "#0a0e17")
    draw = ImageDraw.Draw(img)

    title_font = get_font(55)
    small_font = get_font(35)

    text_len = len(jumbled)
    if text_len <= 7:
        display_text = "   ".join(jumbled)
        word_font = get_font(85)
    elif text_len <= 11:
        display_text = "  ".join(jumbled)
        word_font = get_font(65)
    elif text_len <= 15:
        display_text = " ".join(jumbled)
        word_font = get_font(50)
    else:
        display_text = " ".join(jumbled)
        word_font = get_font(38)

    draw.text((600, 70), "🧩 JUMBLE WORD", anchor="mm", font=title_font, fill="#00ffff")
    draw.text((600, 300), display_text, anchor="mm", font=word_font, fill="#39ff14")
    draw.text((600, 480), f"{mode_tag.upper()}  •  PUZZLE #{puzzle_id}", anchor="mm", font=small_font, fill="#ffffff")
    draw.text((600, 545), "Unscramble the letters & win points!", anchor="mm", font=small_font, fill="#8892b0")

    bio = io.BytesIO()
    bio.name = f"puzzle_{puzzle_id}_{random.randint(100, 999)}.png"
    img.save(bio, "PNG")
    bio.seek(0)
    return bio

async def delete_after(msg: Message, delay: int = 5):
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except Exception:
        pass

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
# BOT JOIN DETECTOR
# ============================================================

@app.on_chat_member_updated()
async def bot_added_handler(_, update: ChatMemberUpdated):
    if update.new_chat_member and update.new_chat_member.user and update.new_chat_member.user.is_self:
        if update.from_user and not update.from_user.is_bot:
            chat_id = update.chat.id
            user_id = update.from_user.id
            ensure_user(update.from_user)
            DB.execute("""
                INSERT INTO group_adders (chat_id, user_id, added_at)
                VALUES (?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET user_id=excluded.user_id, added_at=excluded.added_at
            """, (chat_id, user_id, time.time()))
            DB.commit()

# ============================================================
# NORMAL GAME CORE
# ============================================================

def normal_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💡 𝐇ɪɴᴛ 𝐂𝐥𝐮𝐞", callback_data="hint"),
            InlineKeyboardButton("⏭️ 𝐒ᴋɪᴘ 𝐖ᴏʀᴅ", callback_data="skip")
        ],
        [
            InlineKeyboardButton("🔄 𝐑ᴇ-𝐑ᴏʟʟ 𝐏ᴜᴢᴢʟᴇ", callback_data="newword"),
            InlineKeyboardButton("📊 𝐋ᴇᴀᴅᴇʀʙᴏᴀʀᴅ", callback_data="lb_open_inline")
        ]
    ])

async def start_game(chat_id, difficulty, message_or_chat):
    if chat_id in JUMBLE_FIGHT:
        return

    settings = get_settings(chat_id)
    if not settings["is_active"]:
        return

    old_game = DB.execute("SELECT message_id FROM games WHERE chat_id=?", (chat_id,)).fetchone()
    if old_game and settings["auto_delete"] and old_game["message_id"]:
        await safe_delete_and_unpin(chat_id, old_game["message_id"])

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
    caption_text = (
        f"<blockquote>✨ <b>𝐉𝐔𝐌𝐁𝐋𝐄 𝐏𝐔𝐙𝐙𝐋𝐄 #{puzzle_id}</b>\n\n"
        f"🎯 <b>𝐃ɪғғɪᴄᴜʟᴛʏ:</b> <code>{difficulty.title()}</code>\n"
        f"⏱️ <b>𝐓ɪᴍᴇʀ:</b> <code>{timer_val // 60}m {timer_val % 60}s</code>\n"
        f"⭐ <b>𝐏ᴏɪɴᴛs:</b> <code>+{reward_pts} XP</code>\n"
        f"💡 <b>𝐇ɪɴᴛ 𝐋ɪᴍɪᴛ:</b> <code>{hint_limit} hints/player</code></blockquote>\n\n"
        f"<blockquote>🔀 <i>Unscramble letters and send the word below!</i></blockquote>"
    )

    try:
        if isinstance(message_or_chat, Message):
            sent = await message_or_chat.reply_photo(photo=image, caption=caption_text, reply_markup=normal_keyboard(), parse_mode=ParseMode.HTML)
        else:
            sent = await app.send_photo(chat_id, photo=image, caption=caption_text, reply_markup=normal_keyboard(), parse_mode=ParseMode.HTML)

        DB.execute("UPDATE games SET message_id=? WHERE chat_id=?", (sent.id, chat_id))
        DB.commit()

        try:
            await sent.pin(disable_notification=True)
        except Exception:
            pass
    except Exception as e:
        print(f"Error launching puzzle: {e}")

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
            f"<blockquote>⏰ <b>𝐓𝐈𝐌𝐄'𝐒 𝐔𝐏!</b>\n\n"
            f"❌ <i>Nobody solved this puzzle!</i>\n"
            f"✅ <b>Correct Word:</b> <code>{row['word'].upper()}</code>\n\n"
            f"🔄 <i>Next puzzle coming right up in 3s...</i></blockquote>",
            parse_mode=ParseMode.HTML
        )
        if s["auto_delete"]:
            asyncio.create_task(delete_after(exp_msg, 4))
    except Exception:
        pass

    await asyncio.sleep(3)
    s = get_settings(chat_id)
    if chat_id not in JUMBLE_FIGHT and s["is_active"]:
        next_diff = s["default_diff"] if "default_diff" in s.keys() else "medium"
        asyncio.create_task(start_game(chat_id, next_diff, chat_id))

# ============================================================
# 1v1 FIGHT & BET SYSTEM
# ============================================================

JUMBLE_FIGHT = {}
FIGHT_LOBBY = {}
REBET_LOBBY = {}

def fight_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💡 𝐔𝐬𝐞 𝐇𝐢𝐧𝐭", callback_data="fight_hint")
        ]
    ])

async def fight_timeout_task(chat_id, round_num, timer_duration):
    await asyncio.sleep(timer_duration)

    should_advance = False
    async with LOCK:
        game = JUMBLE_FIGHT.get(chat_id)
        if game and game["round"] == round_num:
            word = game["word"]

            s = get_settings(chat_id)
            if s["auto_delete"] and game.get("msg_id"):
                await safe_delete_and_unpin(chat_id, game["msg_id"])

            try:
                t_msg = await app.send_message(
                    chat_id,
                    f"<blockquote>⏰ <b>𝐑𝐎𝐔𝐍𝐃 {round_num} 𝐓𝐈𝐌𝐄𝐎𝐔𝐓!</b>\n"
                    f"❌ <b>Kisi ne time me solve nahi kiya!</b>\n"
                    f"✅ <b>Answer:</b> <code>{word.upper()}</code>\n\n"
                    f"🔄 <i>Starting next round...</i></blockquote>",
                    parse_mode=ParseMode.HTML
                )
                if s["auto_delete"]:
                    asyncio.create_task(delete_after(t_msg, 4))
            except Exception:
                pass
            should_advance = True

    if should_advance:
        await asyncio.sleep(2.5)
        asyncio.create_task(fight_next(chat_id))

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

    fight_tag = "BET BATTLE" if game.get("is_bet") else "DUEL BATTLE"
    image = make_puzzle_image(jumbled, f"{fight_tag} {diff.upper()}", game["round"])

    title_header = "💎 <b>𝐉𝐔𝐌𝐁𝐋𝐄 𝐁𝐄𝐓 𝐅𝐈𝐆𝐇𝐓" if game.get("is_bet") else "⚔️ <b>𝐉𝐔𝐌𝐁𝐋𝐄 1v1 𝐅𝐈𝐆𝐇𝐓"
    extra_info = f"\n💰 <b>𝐁ᴇᴛ 𝐒ᴛᴀᴋᴇ:</b> <code>{game.get('bet_amount')} pts</code>" if game.get("is_bet") else ""

    p1, p2 = game["players"]

    try:
        sent = await app.send_photo(
            chat_id,
            photo=image,
            caption=(
                f"<blockquote>{title_header} — 𝐑𝐎𝐔𝐍𝐃 {game['round']}/10</b>\n\n"
                f"🎯 <b>𝐃ɪғғɪᴄᴜʟᴛʏ:</b> <code>{diff.title()}</code>\n"
                f"⏱️ <b>𝐓ɪᴍᴇʀ:</b> <code>{game['timer']}s</code>{extra_info}\n"
                f"💡 <b>𝐇ɪɴᴛs:</b> <code>{per_round_hints} available/round</code>\n\n"
                f"👥 <b>𝐃ᴜᴇʟ:</b> {game['mentions'][p1]} 🆚 {game['mentions'][p2]}</blockquote>"
            ),
            reply_markup=fight_keyboard(),
            parse_mode=ParseMode.HTML
        )
        game["msg_id"] = sent.id
        try:
            await sent.pin(disable_notification=True)
        except Exception:
            pass
    except Exception as e:
        print(f"Fight send error: {e}")

    game["task"] = asyncio.create_task(fight_timeout_task(chat_id, game["round"], game["timer"]))

async def finish_fight(chat_id):
    game = JUMBLE_FIGHT.pop(chat_id, None)
    if not game:
        return

    curr = asyncio.current_task()
    if game.get("task") and game["task"] is not curr and not game["task"].done():
        try:
            game["task"].cancel()
        except Exception:
            pass

    s = get_settings(chat_id)
    if s["auto_delete"] and game.get("msg_id"):
        await safe_delete_and_unpin(chat_id, game["msg_id"])

    p1, p2 = game["players"]
    s1, s2 = game["scores"][p1], game["scores"][p2]
    is_bet = game.get("is_bet", False)
    bet_amt = game.get("bet_amount", 0)
    is_rebet = game.get("is_rebet", False)
    now = time.time()

    if s1 > s2:
        winner, loser = p1, p2
        w_score, l_score = s1, s2
    elif s2 > s1:
        winner, loser = p2, p1
        w_score, l_score = s2, s1
    else:
        winner = loser = None

    m1 = game["mentions"][p1]
    m2 = game["mentions"][p2]
    end_kb = None

    bar_p1 = make_graph_bar(s1 * 10, 8)
    bar_p2 = make_graph_bar(s2 * 10, 8)

    if not is_bet:
        if winner:
            DB.execute("UPDATE users SET fight_wins=fight_wins+1 WHERE user_id=?", (winner,))
            DB.execute("UPDATE users SET fight_losses=fight_losses+1 WHERE user_id=?", (loser,))
            DB.commit()

        result = (
            f"<blockquote>🏁 <b>𝐉𝐔𝐌𝐁𝐋𝐄 𝐅𝐈𝐆𝐇𝐓 𝐂𝐎𝐌𝐏𝐋𝐄𝐓𝐄!</b>\n\n"
            f"👤 {m1}\n"
            f"<code>[{bar_p1}]</code> — <b>{s1}/10</b> pts\n\n"
            f"👤 {m2}\n"
            f"<code>[{bar_p2}]</code> — <b>{s2}/10</b> pts\n\n"
        )
        if winner:
            result += f"🏆 <b>𝐌𝐚𝐭𝐜𝐡 𝐖𝐢𝐧𝐧𝐞𝐫:</b> {game['mentions'][winner]} 🎉</blockquote>"
        else:
            result += "🤝 <b>Match Tied! (Draw)</b></blockquote>"

    else:
        if winner:
            if is_rebet:
                total_rematch_pot = bet_amt * 2
                comeback_bonus = 100
                total_payout = total_rematch_pot + comeback_bonus

                DB.execute("UPDATE users SET points=points+?, bet_wins=bet_wins+1 WHERE user_id=?", (total_payout, winner))
                DB.execute("UPDATE users SET bet_losses=bet_losses+1 WHERE user_id=?", (loser,))
                DB.execute("INSERT INTO score_history (user_id, chat_id, points, timestamp) VALUES (?, ?, ?, ?)", (winner, chat_id, total_payout, now))
                DB.commit()

                result = (
                    f"<blockquote>💰 <b>25% 𝐂𝐎𝐌𝐄𝐁𝐀𝐂𝐊 𝐑𝐄-𝐁𝐄𝐓 𝐅𝐈𝐆𝐇𝐓 𝐎𝐕𝐄𝐑!</b>\n\n"
                    f"👤 {game['mentions'][winner]} <code>[{make_graph_bar(w_score * 10, 8)}]</code> <b>{w_score} pts</b> (WINNER)\n"
                    f"👤 {game['mentions'][loser]} <code>[{make_graph_bar(l_score * 10, 8)}]</code> <b>{l_score} pts</b>\n\n"
                    f"🔥 <b>Comeback Payout Breakdown:</b>\n"
                    f"├ 25% + 25% Stake Pot: <code>+{total_rematch_pot} pts</code>\n"
                    f"└ Comeback Victory Stars: <code>+100 pts</code>\n\n"
                    f"🏆 <b>Total Won:</b> <code>+{total_payout} points</code> transferred to {game['mentions'][winner]}!</blockquote>"
                )
            else:
                total_pot = bet_amt * 2
                win_reward = int(total_pot * 0.75)
                loser_cashback = total_pot - win_reward
                rebet_stake = int(bet_amt * 0.25)

                DB.execute("UPDATE users SET points=points+?, bet_wins=bet_wins+1 WHERE user_id=?", (win_reward, winner))
                DB.execute("UPDATE users SET points=points+?, bet_losses=bet_losses+1 WHERE user_id=?", (loser_cashback, loser))
                DB.execute("INSERT INTO score_history (user_id, chat_id, points, timestamp) VALUES (?, ?, ?, ?)", (winner, chat_id, win_reward, now))
                DB.execute("INSERT INTO score_history (user_id, chat_id, points, timestamp) VALUES (?, ?, ?, ?)", (loser, chat_id, loser_cashback, now))
                DB.commit()

                REBET_LOBBY[chat_id] = {
                    "original_winner": winner,
                    "original_loser": loser,
                    "rebet_amount": rebet_stake,
                    "difficulty": game["difficulty"],
                    "timer": game["timer"],
                    "winner_mention": game['mentions'][winner],
                    "loser_mention": game['mentions'][loser],
                    "orig_stake": bet_amt
                }

                end_kb = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(f"🔁 25% 𝐑ᴇ-𝐁ᴇᴛ ({rebet_stake} pts) + 100⭐", callback_data="rebet_challenge")
                    ]
                ])

                result = (
                    f"<blockquote>💰 <b>𝐉𝐔𝐌𝐁𝐋𝐄 𝐁𝐄𝐓 𝐅𝐈𝐆𝐇𝐓 𝐎𝐕𝐄𝐑!</b>\n\n"
                    f"👤 {game['mentions'][winner]} <code>[{make_graph_bar(w_score * 10, 8)}]</code> <b>{w_score} pts</b> (WINNER)\n"
                    f"👤 {game['mentions'][loser]} <code>[{make_graph_bar(l_score * 10, 8)}]</code> <b>{l_score} pts</b>\n\n"
                    f"🏆 <b>75% Winner Reward:</b> <code>+{win_reward} pts</code>\n"
                    f"🛡️ <b>25% Loser Cashback:</b> <code>+{loser_cashback} pts</code>\n\n"
                    f"👉 {game['mentions'][loser]} chahe toh neeche <b>25% Re-bet</b> button dabakar pot + <b>100 Comeback Stars</b> jeet sakta hai!</blockquote>"
                )
        else:
            DB.execute("UPDATE users SET points=points+? WHERE user_id=?", (bet_amt, p1))
            DB.execute("UPDATE users SET points=points+? WHERE user_id=?", (bet_amt, p2))
            DB.execute("INSERT INTO score_history (user_id, chat_id, points, timestamp) VALUES (?, ?, ?, ?)", (p1, chat_id, bet_amt, now))
            DB.execute("INSERT INTO score_history (user_id, chat_id, points, timestamp) VALUES (?, ?, ?, ?)", (p2, chat_id, bet_amt, now))
            DB.commit()
            result = (
                f"<blockquote>🤝 <b>𝐉𝐔𝐌𝐁𝐋𝐄 𝐁𝐄𝐓 𝐅𝐈𝐆𝐇𝐓 𝐃𝐑𝐀𝐖!</b>\n\n"
                f"👤 {m1} — <b>{s1} pts</b>\n"
                f"👤 {m2} — <b>{s2} pts</b>\n\n"
                f"Dono players ko unka staked <code>{bet_amt} points</code> refund kar diya gaya hai.</blockquote>"
            )

    await app.send_message(chat_id, result, reply_markup=end_kb, parse_mode=ParseMode.HTML)

    await asyncio.sleep(3)
    s = get_settings(chat_id)
    if s["is_active"]:
        await app.send_message(chat_id, "<blockquote>🔄 <i>Resuming auto-loop Jumble Game...</i></blockquote>", parse_mode=ParseMode.HTML)
        next_diff = s["default_diff"] if "default_diff" in s.keys() else "medium"
        asyncio.create_task(start_game(chat_id, next_diff, chat_id))

# ============================================================
# DATABASE BACKUP SYSTEM
# ============================================================

@app.on_message(filters.command(["backup", "dbbackup", "getdb"]))
async def backup_db_cmd(_, message: Message):
    if not message.from_user or not is_owner(message.from_user.id):
        return await message.reply_text("❌ Sirf Bot Owner database backup export kar sakta hai.")

    if not os.path.exists("jumble_game.db"):
        return await message.reply_text("❌ Database file nahi mili!")

    status_msg = await message.reply_text("📦 <i>Exporting latest SQLite database backup...</i>", parse_mode=ParseMode.HTML)
    try:
        await message.reply_document(
            document="jumble_game.db",
            caption=(
                "<blockquote>💾 <b>𝐉𝐔𝐌𝐁𝐋𝐄 𝐁𝐎𝐓 𝐃𝐀𝐓𝐀𝐁𝐀𝐒𝐄 𝐁𝐀𝐂𝐊𝐔𝐏</b>\n\n"
                f"📅 <b>Timestamp:</b> <code>{time.strftime('%Y-%m-%d %H:%M:%S')}</code>\n"
                "📌 <i>VPS transfer ya database restoration ke liye yeh file bot ke folder me drop karein.</i></blockquote>"
            ),
            parse_mode=ParseMode.HTML
        )
        await status_msg.delete()
    except Exception as e:
        await status_msg.edit_text(f"❌ Backup failed: <code>{str(e)}</code>")

async def auto_backup_task():
    while True:
        await asyncio.sleep(21600)
        try:
            if os.path.exists("jumble_game.db"):
                await app.send_document(
                    chat_id=OWNER_ID,
                    document="jumble_game.db",
                    caption=(
                        "<blockquote>🤖 <b>𝐉𝐔𝐌𝐁𝐋𝐄 𝐀𝐔𝐓𝐎 𝐃𝐀𝐓𝐀𝐁𝐀𝐒𝐄 𝐁𝐀𝐂𝐊𝐔𝐏 (6h Interval)</b>\n\n"
                        f"⏰ <b>Timestamp:</b> <code>{time.strftime('%Y-%m-%d %H:%M:%S')}</code></blockquote>"
                    ),
                    parse_mode=ParseMode.HTML
                )
        except Exception as e:
            print(f"Auto-backup issue: {e}")

# ============================================================
# MODERN UPGRADED /STATS (DETAIL GRAPH & UNIVERSAL LOOKUP)
# ============================================================

async def resolve_target_user(client: Client, message: Message):
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user
    args = message.command[1:]
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

def generate_stats_card(u: sqlite3.Row, user_obj=None):
    total_fights = (u["fight_wins"] or 0) + (u["fight_losses"] or 0)
    fight_winrate = ((u["fight_wins"] / total_fights) * 100) if total_fights else 0
    fight_bar = make_graph_bar(fight_winrate, 10)

    total_bets = (u["bet_wins"] or 0) + (u["bet_losses"] or 0)
    bet_winrate = (((u["bet_wins"] or 0) / total_bets) * 100) if total_bets else 0
    bet_bar = make_graph_bar(bet_winrate, 10)

    tier_name, tier_stars = get_tier_badge(u["points"])
    mention = get_mention(user_obj=user_obj, user_id=u["user_id"], first_name=u["name"], username=u["username"])
    priv_status = "🔒 Private" if u["is_private"] else "🌐 Public"

    text = (
        f"<blockquote>👤 <b>𝐏𝐋𝐀𝐘𝐄𝐑 𝐏𝐑𝐎𝐅𝐈𝐋𝐄 𝐂𝐀𝐑𝐃</b>\n"
        f"├ <b>User:</b> {mention}\n"
        f"├ <b>ID:</b> <code>{u['user_id']}</code>\n"
        f"├ <b>Tier:</b> {tier_name} ({tier_stars})\n"
        f"└ <b>Privacy:</b> <code>{priv_status}</code>\n\n"
        f"⭐ <b>Total Points:</b> <code>{u['points']:,} pts</code>\n"
        f"🧩 <b>Words Solved:</b> <code>{u['solved']:,}</code>\n"
        f"🔥 <b>Active Streak:</b> <code>{u['streak']}</code> (Best: <code>{u['best_streak']}</code>)\n\n"
        f"⚔️ <b>𝐉𝐮𝐦𝐛𝐥𝐞 𝐅𝐢𝐠𝐡𝐭 (1v1 Dueling)</b>\n"
        f"<code>[{fight_bar}]</code> <b>{fight_winrate:.1f}%</b>\n"
        f"🏆 <b>W/L Record:</b> <code>{u['fight_wins']}W</code> / <code>{u['fight_losses']}L</code> (Total: {total_fights})\n\n"
        f"💰 <b>𝐉𝐮𝐦𝐛𝐥𝐞 𝐁𝐞𝐭 𝐅𝐢𝐠𝐡𝐭 (High Stakes)</b>\n"
        f"<code>[{bet_bar}]</code> <b>{bet_winrate:.1f}%</b>\n"
        f"💵 <b>Bet Record:</b> <code>{u['bet_wins'] or 0}W</code> / <code>{u['bet_losses'] or 0}L</code> (Total: {total_bets})</blockquote>"
    )

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 𝐆𝐥𝐨𝐛𝐚𝐥 𝐑𝐚𝐧𝐤𝐬", callback_data="lb_global_0"),
            InlineKeyboardButton("🔄 𝐑𝐞𝐟𝐫𝐞𝐬𝐡", callback_data=f"refresh_stats_{u['user_id']}")
        ],
        [
            InlineKeyboardButton("❌ 𝐂𝐥𝐨𝐬𝐞", callback_data="close_panel")
        ]
    ])
    return text, kb

@app.on_message(filters.command(["stats", "stat", "mystats", "score", "profile"]))
async def stats_cmd(client: Client, message: Message):
    target = await resolve_target_user(client, message)
    if not target:
        return await message.reply_text("<blockquote>❌ <b>User nahi mila!</b> Username ya User ID check karein.</blockquote>", parse_mode=ParseMode.HTML)

    ensure_user(target)
    u = get_user(target.id)
    if not u:
        return await message.reply_text("<blockquote>❌ <b>No records found for this player.</b></blockquote>", parse_mode=ParseMode.HTML)

    card_text, kb = generate_stats_card(u, target)
    await message.reply_text(card_text, reply_markup=kb, parse_mode=ParseMode.HTML)

# ============================================================
# MODERN UPGRADED /LEADERBOARD (GRAPH & VISUAL STYLING)
# ============================================================

def format_lb_entry(user_id, name, username, is_private):
    clean_name = html.escape(str(name or "Player"))
    if is_private:
        return f"<b>{clean_name}</b>"
    if username:
        return f"<a href='https://t.me/{username}'>{clean_name}</a>"
    return f"<a href='tg://openmessage?user_id={user_id}'>{clean_name}</a>"

def build_leaderboard_text_and_kb(scope_type, chat_id):
    now = time.time()
    medals = ["🥇", "🥈", "🥉"]

    if scope_type == "daily":
        since = now - 86400
        title = "📅 <b>𝐃𝐀𝐈𝐋𝐘 𝐆𝐑𝐎𝐔𝐏 𝐋𝐄𝐀𝐃𝐄𝐑𝐁𝐎𝐀𝐑𝐃 (24h)</b>"
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
        title = "🗓️ <b>𝐖𝐄𝐄𝐊𝐋𝐘 𝐆𝐑𝐎𝐔𝐏 𝐋𝐄𝐀𝐃𝐄𝐑𝐁𝐎𝐀𝐑𝐃 (7 Days)</b>"
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
        title = "📆 <b>𝐌𝐎𝐍𝐓𝐇𝐋𝐘 𝐆𝐋𝐎𝐁𝐀𝐋 𝐋𝐄𝐀𝐃𝐄𝐑𝐁𝐎𝐀𝐑𝐃 (30 Days)</b>"
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
        title = "🌍 <b>𝐆𝐋𝐎𝐁𝐀𝐋 𝐀𝐋𝐋-𝐓𝐈𝐌𝐄 𝐋𝐄𝐀𝐃𝐄𝐑𝐁𝐎𝐀𝐑𝐃</b>"
        rows = DB.execute("""
            SELECT user_id, name, username, is_private, points as total_pts
            FROM users
            WHERE points > 0
            ORDER BY points DESC
            LIMIT 10
        """).fetchall()

    max_pts = rows[0]["total_pts"] if rows else 1

    text = f"<blockquote>{title}\n\n"
    if not rows:
        text += "<i>Abhi tak koi scores record nahi hue hain.</i>"
    else:
        for i, u in enumerate(rows, 1):
            pts = u['total_pts']
            pct = (pts / max_pts) * 100 if max_pts > 0 else 0
            bar = make_graph_bar(pct, 6)
            medal = medals[i - 1] if i <= 3 else f"<code>#{i:02d}</code>"
            user_entry = format_lb_entry(u['user_id'], u['name'], u['username'], u['is_private'])
            text += (
                f"{medal} {user_entry}\n"
                f"   <code>[{bar}]</code> ⭐ <b>{pts:,}</b> pts\n"
            )
    text += "</blockquote>"

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"{'🔘 ' if scope_type=='daily' else '⚪ '}📅 𝐃ᴀɪʟʏ", callback_data=f"lb_daily_{chat_id}"),
            InlineKeyboardButton(f"{'🔘 ' if scope_type=='weekly' else '⚪ '}🗓️ 𝐖ᴇᴇᴋʟʏ", callback_data=f"lb_weekly_{chat_id}")
        ],
        [
            InlineKeyboardButton(f"{'🔘 ' if scope_type=='monthly' else '⚪ '}📆 𝐌ᴏɴᴛʜʟʏ", callback_data=f"lb_monthly_{chat_id}"),
            InlineKeyboardButton(f"{'🔘 ' if scope_type=='global' else '⚪ '}🌍 𝐆ʟᴏʙᴀʟ", callback_data=f"lb_global_{chat_id}")
        ],
        [
            InlineKeyboardButton("❌ 𝐂𝐥𝐨𝐬𝐞", callback_data="close_panel")
        ]
    ])

    return text, kb

@app.on_message(filters.command(["leaderboard", "top", "rank", "lb"]))
async def leaderboard_cmd(_, message: Message):
    chat_id = message.chat.id
    scope = "daily" if is_group(message) else "global"
    text, kb = build_leaderboard_text_and_kb(scope, chat_id)
    await message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

# ============================================================
# GENERAL BOT COMMANDS
# ============================================================

@app.on_message(filters.command("start"))
async def start_cmd(_, message: Message):
    ensure_user(message.from_user)
    text = (
        "<blockquote>🧩 <b>𝐖𝐄𝐋𝐂𝐎𝐌𝐄 𝐓𝐎 𝐀𝐃𝐕𝐀𝐍𝐂𝐄𝐃 𝐉𝐔𝐌𝐁𝐋𝐄 𝐁𝐎𝐓!</b></blockquote>\n\n"
        "<blockquote>🎮 <b>𝐆ᴀᴍᴇ 𝐌ᴏᴅᴇs & 𝐂ᴏᴍᴍᴀɴᴅs:</b>\n"
        "• <code>/jumble</code> — Start Auto-loop Jumble Game\n"
        "• <code>/jumblefight @user</code> — 1v1 Battle Mode Challenge\n"
        "• <code>/jumblebetfight [mode] [amount] @user</code> — 1v1 High Stakes Bet\n"
        "• <code>/settings</code> — Admin Interactive Management Dashboard</blockquote>\n\n"
        "<blockquote>🎁 <b>𝐑ᴇᴡᴀʀᴅs & 𝐄ᴄᴏɴᴏᴍʏ:</b>\n"
        "• <code>/daily</code> — Claim Daily Points in DM (Every 24h)\n"
        "• <code>/bonus</code> — Claim Free Group Admin Addition Bonus</blockquote>\n\n"
        "<blockquote>📊 <b>𝐒ᴛᴀᴛs & 𝐑ᴀɴᴋɪɴɢs:</b>\n"
        "• <code>/stats</code> — Detailed Visual Graphical Card (or /stats @user)\n"
        "• <code>/leaderboard</code> — Top Players & Daily Rankings Graph\n"
        "• <code>/private</code> / <code>/public</code> — Toggle Profile Privacy</blockquote>"
    )

    dm_markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💬 𝐒ᴜᴘᴘᴏʀᴛ 𝐆ʀᴏᴜᴘ", url=SUPPORT_GC),
            InlineKeyboardButton("➕ 𝐀ᴅᴅ 𝐌ᴇ 𝐓ᴏ 𝐆ʀᴏᴜᴘ", url=ADD_ME_URL)
        ],
        [
            InlineKeyboardButton("🎵 ˹ 𓆩ℛᴏ֟፝ᴏʜɪ ꭙ 𝐌ᴜ֟፝sɪᴄ𓆪˼ ♪", url=MUSIC_BOT_URL)
        ]
    ])

    if message.chat.type in (ChatType.PRIVATE,):
        try:
            await message.reply_photo(photo=START_IMG, caption=text, reply_markup=dm_markup, parse_mode=ParseMode.HTML)
        except Exception:
            await message.reply_text(text, reply_markup=dm_markup, parse_mode=ParseMode.HTML)
    else:
        await message.reply_text(text, reply_markup=dm_markup, parse_mode=ParseMode.HTML)

@app.on_message(filters.command("help"))
async def help_cmd(_, message: Message):
    is_user_auth = is_authed(message.from_user.id) if message.from_user else False
    text = (
        "<blockquote>🧩 <b>𝐉𝐔𝐌𝐁𝐋𝐄 𝐂𝐎𝐌𝐌𝐀𝐍𝐃𝐒 𝐆𝐔𝐈𝐃𝐄</b>\n\n"
        "• <code>/jumble</code> — Start auto-looping jumble game\n"
        "• <code>/jumblefight @user</code> — 1v1 battle match\n"
        "• <code>/jumblebetfight [mode] [amount] @user</code> — 1v1 bet battle\n"
        "• <code>/settings</code> — Admin game settings panel\n"
        "• <code>/daily</code> — Claim 50+ daily points (DM only)\n"
        "• <code>/bonus</code> — Claim group addition points\n"
        "• <code>/leaderboard</code> — Graphical Rankings leaderboard\n"
        "• <code>/stats [@user]</code> — Visual Graphical Profile Card\n"
        "• <code>/private</code> / <code>/public</code> — Leaderboard ID privacy</blockquote>"
    )
    if is_user_auth:
        text += (
            "\n\n<blockquote>🔐 <b>𝐀𝐔𝐓𝐇 & 𝐖𝐎𝐑𝐃 𝐁𝐀𝐍𝐊 𝐂𝐎𝐌𝐌𝐀𝐍𝐃𝐒:</b>\n"
            "• <code>/word</code> — View Interactive Word Bank\n"
            "• <code>/addword easy cat dog bird</code> — Bulk add words\n"
            "• <code>/delword easy word</code> — Remove word from bank\n"
            "• <code>/delallword easy</code> — Clear all words in a category\n"
            "• <code>/setpoints [easy|med|hard] [pts]</code> — Change global rewards\n"
            "• <code>/sethint [easy|med|hard] [hints]</code> — Change global hint limits\n"
            "• <code>/setdaily [pts]</code> — Change daily reward\n"
            "• <code>/setbonus [pts]</code> — Change group bonus reward\n"
            "• <code>/addstar [user] [pts]</code> — Credit points to player\n"
            "• <code>/deductstar [user] [pts]</code> — Deduct points from player\n"
            "• <code>/update</code> — Git pull & Auto-restart bot</blockquote>"
        )
    if message.from_user and is_owner(message.from_user.id):
        text += (
            "\n\n<blockquote>👑 <b>𝐎𝐖𝐍𝐄𝐑 𝐂𝐎𝐌𝐌𝐀𝐍𝐃𝐒:</b>\n"
            "• <code>/auth @user</code> — Grant Auth permissions\n"
            "• <code>/unauth @user</code> — Revoke Auth permissions\n"
            "• <code>/authlist</code> — View authorized members\n"
            "• <code>/backup</code> — Download instant SQLite database backup</blockquote>"
        )
    await message.reply_text(text, parse_mode=ParseMode.HTML)

# ============================================================
# SETTINGS PANEL
# ============================================================

def build_timers_keyboard(s):
    easy_val = s["easy"]
    med_val = s["medium"]
    hard_val = s["hard"]
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"{'🟢 ' if easy_val==60 else '⚪ '}Easy: 60s", callback_data="set_t_easy_60"),
            InlineKeyboardButton(f"{'🟢 ' if easy_val==120 else '⚪ '}Easy: 120s", callback_data="set_t_easy_120")
        ],
        [
            InlineKeyboardButton(f"{'🟡 ' if med_val==180 else '⚪ '}Med: 180s", callback_data="set_t_medium_180"),
            InlineKeyboardButton(f"{'🟡 ' if med_val==300 else '⚪ '}Med: 300s", callback_data="set_t_medium_300")
        ],
        [
            InlineKeyboardButton(f"{'🔴 ' if hard_val==300 else '⚪ '}Hard: 300s", callback_data="set_t_hard_300"),
            InlineKeyboardButton(f"{'🔴 ' if hard_val==600 else '⚪ '}Hard: 600s", callback_data="set_t_hard_600")
        ],
        [InlineKeyboardButton("🔙 𝐁ᴀᴄᴋ ᴛᴏ 𝐒ᴇᴛᴛɪɴɢs", callback_data="set_back")]
    ])

@app.on_message(filters.command(["settings", "setting"]))
async def settings_cmd(_, message: Message):
    if not message.from_user or not await is_admin_or_owner(message.chat, message.from_user.id):
        return await message.reply_text("<blockquote>❌ <b>Only group admins can configure settings.</b></blockquote>", parse_mode=ParseMode.HTML)

    s = get_settings(message.chat.id)
    cur_diff = s["default_diff"] if "default_diff" in s.keys() else "medium"
    status_btn = InlineKeyboardButton("⏹️ 𝐒ᴛᴏᴘ 𝐆ᴀᴍᴇ", callback_data="set_stop_game") if s["is_active"] else InlineKeyboardButton("▶️ 𝐒ᴛᴀʀᴛ 𝐆ᴀᴍᴇ", callback_data="set_start_game")
    del_btn = InlineKeyboardButton("🗑️ 𝐀ᴜᴛᴏ-𝐃ᴇʟ: 𝐎𝐍", callback_data="set_toggle_autodel") if s["auto_delete"] else InlineKeyboardButton("🗑️ 𝐀ᴜᴛᴏ-𝐃ᴇʟ: 𝐎𝐅𝐅", callback_data="set_toggle_autodel")

    p_easy = get_global_config("points_easy", 10)
    p_med = get_global_config("points_medium", 20)
    p_hard = get_global_config("points_hard", 30)

    h_easy = get_global_config("hints_easy", 3)
    h_med = get_global_config("hints_medium", 3)
    h_hard = get_global_config("hints_hard", 3)

    kb = InlineKeyboardMarkup([
        [
            status_btn,
            InlineKeyboardButton(f"🎯 𝐌ᴏᴅᴇ: {str(cur_diff).upper()}", callback_data="set_menu_mode")
        ],
        [
            InlineKeyboardButton("⏱️ 𝐓ɪᴍᴇʀs", callback_data="set_menu_timers"),
            del_btn
        ],
        [
            InlineKeyboardButton("❌ 𝐂𝐥𝐨𝐬𝐞", callback_data="close_panel")
        ]
    ])
    await message.reply_text(
        f"<blockquote>⚙️ <b>𝐉𝐔𝐌𝐁𝐋𝐄 𝐆𝐑𝐎𝐔𝐏 𝐂𝐎𝐍𝐅𝐈𝐆𝐔𝐑𝐀𝐓𝐈𝐎𝐍</b>\n\n"
        f"🟢 <b>Status:</b> <code>{'Running' if s['is_active'] else 'Stopped'}</code>\n"
        f"🗑️ <b>Auto Delete Old:</b> <code>{'Enabled' if s['auto_delete'] else 'Disabled'}</code>\n"
        f"🎯 <b>Default Difficulty:</b> <code>{str(cur_diff).title()}</code>\n"
        f"⏱️ <b>Group Timers:</b> Easy: <code>{s['easy']}s</code> | Med: <code>{s['medium']}s</code> | Hard: <code>{s['hard']}s</code>\n\n"
        f"🌍 <b>Global Rewards:</b> Easy: <code>+{p_easy}</code> | Med: <code>+{p_med}</code> | Hard: <code>+{p_hard}</code>\n"
        f"💡 <b>Hint Limits:</b> Easy: <code>{h_easy}</code> | Med: <code>{h_med}</code> | Hard: <code>{h_hard}</code></blockquote>",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )

# ============================================================
# CONFIG / REWARD COMMANDS
# ============================================================

@app.on_message(filters.command("setpoints"))
async def set_points_global(_, message: Message):
    if not message.from_user or not is_authed(message.from_user.id):
        return await message.reply_text("<blockquote>❌ <b>Sirf Owner aur Auth users global points set kar sakte hain.</b></blockquote>", parse_mode=ParseMode.HTML)

    args = message.command[1:]
    if len(args) == 1:
        try:
            pts = int(args[0])
        except ValueError:
            return await message.reply_text("❌ Invalid points number.")

        set_global_config("points_easy", pts)
        set_global_config("points_medium", pts)
        set_global_config("points_hard", pts)
        return await message.reply_text(f"<blockquote>🌍 <b>GLOBAL REWARD UPDATED!</b>\n\nSabhi modes ke liye reward <b>{pts} points</b> set kar diya gaya.</blockquote>", parse_mode=ParseMode.HTML)

    elif len(args) == 2:
        category = args[0].lower()
        if category not in ("easy", "medium", "hard"):
            return await message.reply_text("❌ Category must be: <code>easy</code>, <code>medium</code>, ya <code>hard</code>.", parse_mode=ParseMode.HTML)

        try:
            pts = int(args[1])
        except ValueError:
            return await message.reply_text("❌ Invalid points number.")

        set_global_config(f"points_{category}", pts)
        return await message.reply_text(f"<blockquote>🌍 <b>GLOBAL REWARD UPDATED!</b>\n\n<b>{category.title()}</b> reward <b>{pts} points</b> set kar diya gaya.</blockquote>", parse_mode=ParseMode.HTML)

    else:
        return await message.reply_text(
            "<blockquote><b>Usage:</b>\n"
            "• <code>/setpoints 20</code> (All categories)\n"
            "• <code>/setpoints easy 10</code>\n"
            "• <code>/setpoints medium 25</code>\n"
            "• <code>/setpoints hard 50</code></blockquote>",
            parse_mode=ParseMode.HTML
        )

@app.on_message(filters.command("sethint"))
async def sethint_global(_, message: Message):
    if not message.from_user or not is_authed(message.from_user.id):
        return await message.reply_text("<blockquote>❌ <b>Sirf Owner aur Auth users global hints set kar sakte hain.</b></blockquote>", parse_mode=ParseMode.HTML)

    args = message.command[1:]
    if len(args) == 1:
        try:
            h = int(args[0])
        except ValueError:
            return await message.reply_text("❌ Invalid hint number.")

        set_global_config("hints_easy", h)
        set_global_config("hints_medium", h)
        set_global_config("hints_hard", h)
        return await message.reply_text(f"<blockquote>🌍 <b>GLOBAL HINTS UPDATED!</b>\n\nSabhi modes ke liye hints limit <b>{h} hints/round</b> set kar di gayi.</blockquote>", parse_mode=ParseMode.HTML)

    elif len(args) == 2:
        category = args[0].lower()
        if category not in ("easy", "medium", "hard"):
            return await message.reply_text("❌ Category must be: <code>easy</code>, <code>medium</code>, ya <code>hard</code>.", parse_mode=ParseMode.HTML)

        try:
            h = int(args[1])
        except ValueError:
            return await message.reply_text("❌ Invalid hint number.")

        set_global_config(f"hints_{category}", h)
        return await message.reply_text(f"<blockquote>🌍 <b>GLOBAL HINTS UPDATED!</b>\n\n<b>{category.title()}</b> hints limit <b>{h} hints/round</b> set kar di gayi.</blockquote>", parse_mode=ParseMode.HTML)

    else:
        return await message.reply_text(
            "<blockquote><b>Usage:</b>\n"
            "• <code>/sethint 3</code>\n"
            "• <code>/sethint easy 5</code>\n"
            "• <code>/sethint medium 3</code>\n"
            "• <code>/sethint hard 2</code></blockquote>",
            parse_mode=ParseMode.HTML
        )

@app.on_message(filters.command("setdaily"))
async def set_daily_cmd(_, message: Message):
    if not message.from_user or not is_authed(message.from_user.id):
        return await message.reply_text("❌ Sirf Owner aur Auth users daily reward set kar sakte hain.")

    if len(message.command) < 2:
        return await message.reply_text("Usage: <code>/setdaily 100</code>", parse_mode=ParseMode.HTML)

    try:
        val = int(message.command[1])
    except ValueError:
        return await message.reply_text("❌ Invalid number.")

    set_global_config("daily_points", val)
    await message.reply_text(f"<blockquote>✅ <b>Daily claim reward <b>{val} points</b> set kar diya gaya.</b></blockquote>", parse_mode=ParseMode.HTML)

@app.on_message(filters.command("setbonus"))
async def set_bonus_cmd(_, message: Message):
    if not message.from_user or not is_authed(message.from_user.id):
        return await message.reply_text("❌ Sirf Owner aur Auth users group bonus reward set kar sakte hain.")

    if len(message.command) < 2:
        return await message.reply_text("Usage: <code>/setbonus 200</code>", parse_mode=ParseMode.HTML)

    try:
        val = int(message.command[1])
    except ValueError:
        return await message.reply_text("❌ Invalid number.")

    set_global_config("bonus_points", val)
    await message.reply_text(f"<blockquote>✅ <b>Group admin bonus reward <b>{val} points</b> set kar diya gaya.</b></blockquote>", parse_mode=ParseMode.HTML)

@app.on_message(filters.command("daily"))
async def daily_cmd(_, message: Message):
    if not message.from_user:
        return
    if message.chat.type != ChatType.PRIVATE:
        return await message.reply_text("<blockquote>❌ <b><code>/daily</code> command sirf bot ke DM (Private Chat) mein use kar sakte hain.</b></blockquote>", parse_mode=ParseMode.HTML)

    ensure_user(message.from_user)
    u = get_user(message.from_user.id)
    now = time.time()
    last = u["last_daily"] or 0
    cooldown = 86400

    if now - last < cooldown:
        rem = int(cooldown - (now - last))
        hrs = rem // 3600
        mins = (rem % 3600) // 60
        return await message.reply_text(f"<blockquote>⏳ <b>Daily reward already claimed!</b>\nNext claim available in: <b>{hrs}h {mins}m</b></blockquote>", parse_mode=ParseMode.HTML)

    reward = get_global_config("daily_points", 50)
    DB.execute("""
        UPDATE users 
        SET points = points + ?, last_daily = ?
        WHERE user_id = ?
    """, (reward, now, message.from_user.id))

    DB.execute("""
        INSERT INTO score_history (user_id, chat_id, points, timestamp)
        VALUES (?, 0, ?, ?)
    """, (message.from_user.id, reward, now))
    DB.commit()

    await message.reply_text(
        f"<blockquote>🎁 <b>𝐃𝐀𝐈𝐋𝐘 𝐑𝐄𝐖𝐀𝐑𝐃 𝐂𝐋𝐀𝐈𝐌𝐄𝐃!</b>\n\n"
        f"⭐ <b>+{reward} Points</b> balance mein add kar diye gaye hain!\n"
        f"Come back again after 24 hours!</blockquote>",
        parse_mode=ParseMode.HTML
    )

@app.on_message(filters.command("bonus"))
async def bonus_cmd(_, message: Message):
    if not message.from_user:
        return
    if not is_group(message):
        return await message.reply_text("<blockquote>❌ <b><code>/bonus</code> command sirf us group mein chal sakti hai jahan bot admin ho.</b></blockquote>", parse_mode=ParseMode.HTML)

    ensure_user(message.from_user)
    chat_id = message.chat.id
    user_id = message.from_user.id

    promoted_by_user_id = None
    try:
        bot_member = await message.chat.get_member("me")
        if bot_member.status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
            return await message.reply_text("<blockquote>⚠️ <b>Bonus claim karne ke liye bot ko Admin Rights dein!</b></blockquote>", parse_mode=ParseMode.HTML)

        if getattr(bot_member, "promoted_by", None):
            promoted_by_user_id = bot_member.promoted_by.id
    except Exception:
        return await message.reply_text("<blockquote>❌ <b>Admin status verify nahi hua.</b></blockquote>", parse_mode=ParseMode.HTML)

    claimed = DB.execute("SELECT * FROM group_bonus WHERE chat_id=?", (chat_id,)).fetchone()
    if claimed:
        return await message.reply_text("<blockquote>⚠️ <b>Is group ka bonus already claim kiya ja chuka hai!</b></blockquote>", parse_mode=ParseMode.HTML)

    adder_row = DB.execute("SELECT user_id FROM group_adders WHERE chat_id=?", (chat_id,)).fetchone()
    valid_claimant_id = adder_row["user_id"] if adder_row else promoted_by_user_id

    if not valid_claimant_id:
        try:
            member = await message.chat.get_member(user_id)
            if member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
                valid_claimant_id = user_id
                DB.execute("""
                    INSERT INTO group_adders (chat_id, user_id, added_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(chat_id) DO UPDATE SET user_id=excluded.user_id
                """, (chat_id, user_id, time.time()))
                DB.commit()
        except Exception:
            pass

    if valid_claimant_id and user_id != valid_claimant_id and not is_owner(user_id):
        return await message.reply_text("<blockquote>❌ <b>Yeh bonus sirf bot ko add ya admin banane wala user hi claim kar sakta hai!</b></blockquote>", parse_mode=ParseMode.HTML)

    bonus_pts = get_global_config("bonus_points", 100)
    now = time.time()

    DB.execute("INSERT INTO group_bonus (chat_id, user_id, claimed_at) VALUES (?, ?, ?)", (chat_id, user_id, now))
    DB.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (bonus_pts, user_id))
    DB.execute("INSERT INTO score_history (user_id, chat_id, points, timestamp) VALUES (?, ?, ?, ?)", (user_id, chat_id, bonus_pts, now))
    DB.commit()

    mention = get_mention(message.from_user)
    await message.reply_text(
        f"<blockquote>🎉 <b>𝐆𝐑𝐎𝐔𝐏 𝐁𝐎𝐍𝐔𝐒 𝐂𝐋𝐀𝐈𝐌𝐄𝐃!</b>\n\n"
        f"👤 {mention}\n"
        f"⭐ <b>+{bonus_pts} Points</b> successfully aapke profile mein credit kar diye gaye hain!</blockquote>",
        parse_mode=ParseMode.HTML
    )

# ============================================================
# POINTS MANAGEMENT (OWNER / AUTH ONLY)
# ============================================================

async def resolve_target_and_amount(message: Message):
    args = message.command[1:]
    target = None
    amount = 0

    if message.reply_to_message and message.reply_to_message.from_user:
        target = message.reply_to_message.from_user
        for a in args:
            if a.isdigit():
                amount = int(a)
                break
    elif len(args) >= 2:
        user_param = args[0]
        try:
            if user_param.isdigit():
                target = await app.get_users(int(user_param))
            else:
                target = await app.get_users(user_param)
        except Exception:
            pass

        for a in args[1:]:
            if a.isdigit():
                amount = int(a)
                break
    elif message.entities and len(args) >= 2:
        for entity in message.entities:
            if entity.type.name == "TEXT_MENTION" and entity.user:
                target = entity.user
                break
        for a in args:
            if a.isdigit():
                amount = int(a)
                break

    return target, amount

@app.on_message(filters.command(["addstar", "addpoints"]))
async def addstar_cmd(_, message: Message):
    if not message.from_user or not is_authed(message.from_user.id):
        return await message.reply_text("<blockquote>❌ <b>Sirf Owner aur Authorized users points add kar sakte hain.</b></blockquote>", parse_mode=ParseMode.HTML)

    target, amount = await resolve_target_and_amount(message)
    if not target or amount <= 0:
        return await message.reply_text("Usage:\n• Reply: <code>/addstar 100</code>\n• Tag: <code>/addstar @user 100</code>", parse_mode=ParseMode.HTML)

    if target.is_bot:
        return await message.reply_text("❌ Bots cannot have points.")

    ensure_user(target)
    now = time.time()
    chat_id = message.chat.id if is_group(message) else 0

    DB.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (amount, target.id))
    DB.execute("INSERT INTO score_history (user_id, chat_id, points, timestamp) VALUES (?, ?, ?, ?)", (target.id, chat_id, amount, now))
    DB.commit()

    u = get_user(target.id)
    target_mention = get_mention(target)
    res = await message.reply_text(
        f"<blockquote>⭐ <b>𝐒𝐓𝐀𝐑𝐒 / 𝐏𝐎𝐈𝐍𝐓𝐒 𝐂𝐑𝐄𝐃𝐈𝐓𝐄𝐃!</b>\n\n"
        f"👤 <b>Player:</b> {target_mention} (<code>{target.id}</code>)\n"
        f"➕ <b>Credit:</b> <code>+{amount} points</code>\n"
        f"💰 <b>Balance:</b> <code>{u['points']} points</code></blockquote>",
        parse_mode=ParseMode.HTML
    )
    asyncio.create_task(delete_after(message, 6))
    asyncio.create_task(delete_after(res, 6))

@app.on_message(filters.command(["deductstar", "deductpoints", "removestar"]))
async def deductstar_cmd(_, message: Message):
    if not message.from_user or not is_authed(message.from_user.id):
        return await message.reply_text("<blockquote>❌ <b>Sirf Owner aur Authorized users points deduct kar sakte hain.</b></blockquote>", parse_mode=ParseMode.HTML)

    target, amount = await resolve_target_and_amount(message)
    if not target or amount <= 0:
        return await message.reply_text("Usage:\n• Reply: <code>/deductstar 50</code>\n• Tag: <code>/deductstar @user 50</code>", parse_mode=ParseMode.HTML)

    if target.is_bot:
        return await message.reply_text("❌ Bots cannot have points.")

    ensure_user(target)
    u = get_user(target.id)
    current_points = u["points"] if u else 0
    actual_deduct = min(current_points, amount)

    now = time.time()
    chat_id = message.chat.id if is_group(message) else 0

    DB.execute("UPDATE users SET points = points - ? WHERE user_id = ?", (actual_deduct, target.id))
    DB.execute("INSERT INTO score_history (user_id, chat_id, points, timestamp) VALUES (?, ?, ?, ?)", (target.id, chat_id, -actual_deduct, now))
    DB.commit()

    u_updated = get_user(target.id)
    target_mention = get_mention(target)
    res = await message.reply_text(
        f"<blockquote>🛡️ <b>𝐒𝐓𝐀𝐑𝐒 / 𝐏𝐎𝐈𝐍𝐓𝐒 𝐃𝐄𝐃𝐔𝐂𝐓𝐄𝐃!</b>\n\n"
        f"👤 <b>Player:</b> {target_mention} (<code>{target.id}</code>)\n"
        f"➖ <b>Debit:</b> <code>-{actual_deduct} points</code>\n"
        f"💰 <b>Balance:</b> <code>{u_updated['points']} points</code></blockquote>",
        parse_mode=ParseMode.HTML
    )
    asyncio.create_task(delete_after(message, 6))
    asyncio.create_task(delete_after(res, 6))

# ============================================================
# PRIVACY SETTINGS
# ============================================================

@app.on_message(filters.command("private"))
async def private_cmd(_, message: Message):
    if not message.from_user:
        return
    ensure_user(message.from_user)
    DB.execute("UPDATE users SET is_private=1 WHERE user_id=?", (message.from_user.id,))
    DB.commit()

    await message.reply_text(
        "<blockquote>🔒 <b>𝐏𝐑𝐈𝐕𝐀𝐂𝐘 𝐄𝐍𝐀𝐁𝐋𝐄𝐃!</b>\n\n"
        "Leaderboard par aapka <b>Tag, Link aur User ID hide</b> kar diya gaya hai. Sirf plain text name dikhega.\n"
        "Unhide karne ke liye <code>/public</code> use karein.</blockquote>",
        parse_mode=ParseMode.HTML
    )

@app.on_message(filters.command("public"))
async def public_cmd(_, message: Message):
    if not message.from_user:
        return
    ensure_user(message.from_user)
    DB.execute("UPDATE users SET is_private=0 WHERE user_id=?", (message.from_user.id,))
    DB.commit()

    await message.reply_text(
        "<blockquote>🌐 <b>𝐏𝐔𝐁𝐋𝐈𝐂 𝐌𝐎𝐃𝐄 𝐄𝐍𝐀𝐁𝐋𝐄𝐃!</b>\n\n"
        "Leaderboard par aapka <b>Profile Link, Username aur ID</b> normal dikhega.</blockquote>",
        parse_mode=ParseMode.HTML
    )

# ============================================================
# GIT UPDATER
# ============================================================

@app.on_message(filters.command(["update", "gitpull"]))
async def update_bot_cmd(_, message: Message):
    if not message.from_user or not is_authed(message.from_user.id):
        return await message.reply_text("❌ Sirf Authorized users bot update kar sakte hain.")

    msg = await message.reply_text("<blockquote>🔄 <b>Pulling latest commits from GitHub...</b></blockquote>", parse_mode=ParseMode.HTML)
    try:
        subprocess.run(["git", "stash"], check=True, capture_output=True, text=True)
        pull_res = subprocess.run(["git", "pull"], check=True, capture_output=True, text=True)
        out = pull_res.stdout or "Updated successfully."

        await msg.edit_text(f"<blockquote>✅ <b>Git Update Completed:</b>\n<code>{out[:400]}</code>\n\n🚀 Restarting bot...</blockquote>", parse_mode=ParseMode.HTML)
        await asyncio.sleep(1.5)
        os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception as e:
        await msg.edit_text(f"<blockquote>❌ <b>Update Failed:</b>\n<code>{str(e)}</code></blockquote>", parse_mode=ParseMode.HTML)

# ============================================================
# AUTH SYSTEM
# ============================================================

@app.on_message(filters.command("auth"))
async def auth_cmd(_, message: Message):
    if not message.from_user or not is_owner(message.from_user.id):
        return await message.reply_text("❌ Sirf Bot Owner auth grant kar sakta hai.")

    target = None
    if message.reply_to_message and message.reply_to_message.from_user:
        target = message.reply_to_message.from_user
    elif len(message.command) >= 2:
        try:
            arg = message.command[1]
            target = await app.get_users(int(arg) if arg.isdigit() else arg)
        except Exception:
            return await message.reply_text("❌ User nahi mila.")
    else:
        return await message.reply_text("Usage: <code>/auth @username</code> ya Reply karein.", parse_mode=ParseMode.HTML)

    if target.is_bot:
        return await message.reply_text("❌ Bots cannot be authorized.")

    DB.execute("""
        INSERT INTO auth_users(user_id, username, name, added_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username=excluded.username,
            name=excluded.name
    """, (target.id, target.username or "", target.first_name or "User", time.time()))
    DB.commit()

    mention = get_mention(target)
    res = await message.reply_text(f"<blockquote>✅ {mention} (<code>{target.id}</code>) ko <b>Auth Privileges</b> de diye gaye.</blockquote>", parse_mode=ParseMode.HTML)
    asyncio.create_task(delete_after(message, 5))
    asyncio.create_task(delete_after(res, 5))

@app.on_message(filters.command("unauth"))
async def unauth_cmd(_, message: Message):
    if not message.from_user or not is_owner(message.from_user.id):
        return await message.reply_text("❌ Sirf Bot Owner unauth kar sakta hai.")

    target = None
    if message.reply_to_message and message.reply_to_message.from_user:
        target = message.reply_to_message.from_user
    elif len(message.command) >= 2:
        try:
            arg = message.command[1]
            target = await app.get_users(int(arg) if arg.isdigit() else arg)
        except Exception:
            return await message.reply_text("❌ User nahi mila.")
    else:
        return await message.reply_text("Usage: <code>/unauth @username</code> ya Reply karein.", parse_mode=ParseMode.HTML)

    DB.execute("DELETE FROM auth_users WHERE user_id=?", (target.id,))
    DB.commit()

    mention = get_mention(target)
    res = await message.reply_text(f"<blockquote>🚫 {mention} (<code>{target.id}</code>) se Auth access revoke kar diya gaya.</blockquote>", parse_mode=ParseMode.HTML)
    asyncio.create_task(delete_after(message, 5))
    asyncio.create_task(delete_after(res, 5))

@app.on_message(filters.command("authlist"))
async def authlist_cmd(_, message: Message):
    if not message.from_user or not is_authed(message.from_user.id):
        return await message.reply_text("❌ Sirf Owner aur Auth users authlist dekh sakte hain.")

    rows = DB.execute("SELECT * FROM auth_users ORDER BY added_at DESC").fetchall()
    text = "<blockquote>🔐 <b>𝐀𝐔𝐓𝐇𝐎𝐑𝐈𝐙𝐄𝐃 𝐔𝐒𝐄𝐑𝐒 𝐋𝐈𝐒𝐓</b>\n\n"
    text += f"👑 <b>Owner:</b> <code>{OWNER_ID}</code>\n\n"

    if not rows:
        text += "Koi additional authorized user nahi hai."
    else:
        for i, row in enumerate(rows, 1):
            m = get_mention(user_id=row['user_id'], first_name=row['name'], username=row['username'])
            text += f"<code>#{i:02d}</code> {m} — ID: <code>{row['user_id']}</code>\n"
    text += "</blockquote>"

    res = await message.reply_text(text, parse_mode=ParseMode.HTML)
    asyncio.create_task(delete_after(message, 10))
    asyncio.create_task(delete_after(res, 10))

# ============================================================
# WORD BANK SYSTEM
# ============================================================

def process_bulk_words_addition(difficulty: str, raw_text: str):
    difficulty = difficulty.lower().strip()
    if difficulty not in WORDS:
        return None, None

    tokens = re.split(r"[\s,;\"'\n\r]+", str(raw_text))
    added = []
    skipped = []

    for token in tokens:
        w = "".join(c.lower() for c in token if c.isalpha()).strip()
        if len(w) >= 3:
            if w not in WORDS[difficulty]:
                WORDS[difficulty].append(w)
                DB.execute("INSERT OR IGNORE INTO custom_words(difficulty, word) VALUES (?, ?)", (difficulty, w))
                added.append(w)
            else:
                skipped.append(w)

    DB.commit()
    return added, skipped

@app.on_message(filters.command(["addword", "addwords", "word", "words"]))
async def addword_cmd(_, message: Message):
    if not message.from_user or not is_authed(message.from_user.id):
        return await message.reply_text("<blockquote>❌ <b>Aap authorized nahi hain.</b></blockquote>", parse_mode=ParseMode.HTML)

    cmd_text = message.text or ""
    parts = cmd_text.split()

    if len(parts) == 1:
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(f"🟢 𝐄ᴀsʏ ({len(WORDS['easy'])})", callback_data="wb_easy_1"),
                InlineKeyboardButton(f"🟡 𝐌ᴇᴅɪᴜᴍ ({len(WORDS['medium'])})", callback_data="wb_medium_1"),
                InlineKeyboardButton(f"🔴 𝐇ᴀʀᴅ ({len(WORDS['hard'])})", callback_data="wb_hard_1")
            ],
            [
                InlineKeyboardButton("❌ 𝐂𝐥𝐨𝐬𝐞", callback_data="close_panel")
            ]
        ])

        await message.reply_text(
            "<blockquote>📚 <b>𝐉𝐔𝐌𝐁𝐋𝐄 𝐖𝐎𝐑𝐃 𝐁𝐀𝐍𝐊</b>\n\n"
            f"🟢 <b>Easy Words:</b> <code>{len(WORDS['easy'])}</code>\n"
            f"🟡 <b>Medium Words:</b> <code>{len(WORDS['medium'])}</code>\n"
            f"🔴 <b>Hard Words:</b> <code>{len(WORDS['hard'])}</code>\n\n"
            "📌 <b>Add Words in Bulk:</b>\n"
            "<code>/addword easy cat dog bird lion tiger</code></blockquote>",
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
        asyncio.create_task(delete_after(message, 3))
        return

    difficulty = parts[1].lower().strip() if len(parts) > 1 else ""
    if difficulty not in ("easy", "medium", "hard"):
        return await message.reply_text("<blockquote>❌ <b>Category must be:</b> <code>easy</code>, <code>medium</code>, ya <code>hard</code>.</blockquote>", parse_mode=ParseMode.HTML)

    raw_payload = ""
    if len(parts) >= 3:
        raw_payload = cmd_text.split(None, 2)[2]
    elif message.reply_to_message and (message.reply_to_message.text or message.reply_to_message.caption):
        raw_payload = message.reply_to_message.text or message.reply_to_message.caption

    if not raw_payload.strip():
        return await message.reply_text("<blockquote>❌ <b>Words list provide karein:</b> <code>/addword easy apple mango banana</code></blockquote>", parse_mode=ParseMode.HTML)

    added, skipped = process_bulk_words_addition(difficulty, raw_payload)
    if not added and not skipped:
        return await message.reply_text("<blockquote>❌ <b>Koi valid word (minimum 3 letters) nahi mila.</b></blockquote>", parse_mode=ParseMode.HTML)

    msg_text = f"<blockquote>✅ <b>{len(added)}</b> words successfully added to <b>{difficulty.upper()}</b> bank!"
    if skipped:
        msg_text += f"\n⚠️ <i>{len(skipped)} words already exist karte the.</i>"
    msg_text += "</blockquote>"

    res = await message.reply_text(msg_text, parse_mode=ParseMode.HTML)
    asyncio.create_task(delete_after(message, 5))
    asyncio.create_task(delete_after(res, 5))

@app.on_message(filters.command("delword"))
async def delword_cmd(_, message: Message):
    if not message.from_user or not is_authed(message.from_user.id):
        return await message.reply_text("❌ Aap authorized nahi hain.")

    if len(message.command) < 3:
        return await message.reply_text("Usage:\n<code>/delword easy apple</code>", parse_mode=ParseMode.HTML)

    difficulty = message.command[1].lower().strip()
    word_to_del = clean_answer(message.command[2])

    if difficulty not in WORDS:
        return await message.reply_text("❌ Valid difficulties: <code>easy</code>, <code>medium</code>, <code>hard</code>.", parse_mode=ParseMode.HTML)

    if word_to_del not in WORDS[difficulty]:
        res = await message.reply_text(f"<blockquote>❌ Word <b>'{word_to_del.upper()}'</b> nahi mila.</blockquote>", parse_mode=ParseMode.HTML)
        asyncio.create_task(delete_after(message, 5))
        asyncio.create_task(delete_after(res, 5))
        return

    WORDS[difficulty].remove(word_to_del)
    DB.execute("DELETE FROM custom_words WHERE difficulty=? AND word=?", (difficulty, word_to_del))
    DB.execute("DELETE FROM used_words WHERE difficulty=? AND word=?", (difficulty, word_to_del))
    DB.commit()

    res = await message.reply_text(f"<blockquote>🗑️ Word <b>'{word_to_del.upper()}'</b> deleted from {difficulty.upper()}!</blockquote>", parse_mode=ParseMode.HTML)
    asyncio.create_task(delete_after(message, 5))
    asyncio.create_task(delete_after(res, 5))

@app.on_message(filters.command(["delallword", "delallwords", "clearword", "clearwords"]))
async def del_all_words_cmd(_, message: Message):
    if not message.from_user or not is_authed(message.from_user.id):
        return await message.reply_text("<blockquote>❌ <b>Sirf Owner aur Auth users words clear kar sakte hain.</b></blockquote>", parse_mode=ParseMode.HTML)

    if len(message.command) < 2:
        return await message.reply_text("Usage: <code>/delallword easy</code>", parse_mode=ParseMode.HTML)

    diff = message.command[1].lower().strip()
    if diff not in WORDS:
        return await message.reply_text("<blockquote>❌ <b>Category must be:</b> <code>easy</code>, <code>medium</code>, ya <code>hard</code>.</blockquote>", parse_mode=ParseMode.HTML)

    count = len(WORDS[diff])
    WORDS[diff] = []

    DB.execute("DELETE FROM custom_words WHERE difficulty=?", (diff,))
    DB.execute("DELETE FROM used_words WHERE difficulty=?", (diff,))
    DB.commit()

    res = await message.reply_text(f"<blockquote>🗑️ <b>{diff.upper()} BANK CLEARED!</b>\nTotal {count} words deleted.</blockquote>", parse_mode=ParseMode.HTML)
    asyncio.create_task(delete_after(message, 5))
    asyncio.create_task(delete_after(res, 5))

# ============================================================
# JUMBLE COMMAND (LOOP PUZZLE LAUNCHER)
# ============================================================

@app.on_message(filters.command("jumble"))
async def jumble_cmd(_, message: Message):
    ensure_user(message.from_user)
    if message.chat.id in JUMBLE_FIGHT:
        return await message.reply_text("<blockquote>⚔️ <b>Jumble Fight chal rahi hai, wait karein.</b></blockquote>", parse_mode=ParseMode.HTML)

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
# 1v1 FIGHT COMMAND
# ============================================================

@app.on_message(filters.command(["jumblefight", "fight", "rapido"]))
async def jumble_fight_cmd(client: Client, message: Message):
    if not is_group(message):
        return await message.reply_text("<blockquote>❌ <b>Jumble Fight sirf groups mein chal sakta hai.</b></blockquote>", parse_mode=ParseMode.HTML)

    target_user = await resolve_target_user(client, message)
    if not target_user:
        return await message.reply_text("<blockquote>⚔️ <b>Player mention karein:</b> <code>/jumblefight @username</code> ya reply karein.</blockquote>", parse_mode=ParseMode.HTML)

    if message.from_user and target_user.id == message.from_user.id:
        return await message.reply_text("<blockquote>❌ <b>Khud ke sath match nahi ho sakta.</b></blockquote>", parse_mode=ParseMode.HTML)

    if target_user.is_bot:
        return await message.reply_text("<blockquote>❌ <b>Bots ke sath duel nahi khel sakte.</b></blockquote>", parse_mode=ParseMode.HTML)

    ensure_user(message.from_user)
    ensure_user(target_user)

    key = message.chat.id
    if key in JUMBLE_FIGHT:
        return await message.reply_text("<blockquote>⚔️ <b>Is group mein already duel chal raha hai.</b></blockquote>", parse_mode=ParseMode.HTML)

    m1 = get_mention(message.from_user) if message.from_user else "Player 1"
    m2 = get_mention(target_user)
    p1_id = message.from_user.id if message.from_user else 0

    FIGHT_LOBBY[key] = {
        "p1": p1_id,
        "p2": target_user.id,
        "p1_name": message.from_user.first_name if message.from_user else "Player 1",
        "p2_name": target_user.first_name,
        "m1": m1,
        "m2": m2,
        "difficulty": "medium",
        "timer": 60,
        "is_bet": False,
        "bet_amount": 0
    }

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🟢 𝐄ᴀsʏ", callback_data="f_diff_easy"),
            InlineKeyboardButton("🟡 𝐌ᴇᴅɪᴜᴍ", callback_data="f_diff_medium"),
            InlineKeyboardButton("🔴 𝐇ᴀʀᴅ", callback_data="f_diff_hard")
        ],
        [
            InlineKeyboardButton("⏱️ 30s", callback_data="f_time_30"),
            InlineKeyboardButton("⏱️ 45s", callback_data="f_time_45"),
            InlineKeyboardButton("⏱️ 60s", callback_data="f_time_60")
        ],
        [
            InlineKeyboardButton("⚔️ 𝐀ᴄᴄᴇᴘᴛ 𝐃ᴜᴇʟ", callback_data="f_accept"),
            InlineKeyboardButton("❌ 𝐃ᴇᴄʟɪɴᴇ", callback_data="f_decline")
        ]
    ])

    await message.reply_text(
        f"<blockquote>⚔️ <b>𝐉𝐔𝐌𝐁𝐋𝐄 1v1 𝐃𝐔𝐄𝐋 𝐂𝐇𝐀𝐋𝐋𝐄𝐍𝐆𝐄!</b>\n\n"
        f"👤 <b>Challenger:</b> {m1} (<code>{p1_id}</code>)\n"
        f"🎯 <b>Opponent:</b> {m2} (<code>{target_user.id}</code>)\n\n"
        f"⚙️ <b>Current Mode:</b> <code>Medium</code> | ⏱️ <b>Timer:</b> <code>60s</code>\n\n"
        f"👉 {m2}, duel start karne ke liye <b>Accept Duel</b> par click karein!</blockquote>",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )

# ============================================================
# BET FIGHT COMMAND
# ============================================================

@app.on_message(filters.command(["jumblebetfight", "betfight"]))
async def jumble_bet_fight_cmd(client: Client, message: Message):
    if not is_group(message):
        return await message.reply_text("<blockquote>❌ <b>Bet fight sirf group mein chal sakti hai.</b></blockquote>", parse_mode=ParseMode.HTML)

    if not message.from_user:
        return

    ensure_user(message.from_user)
    u1 = get_user(message.from_user.id)

    target_user = None
    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user

    parts = message.command[1:]
    diff = "medium"
    amount = 0

    for p in parts:
        if p.startswith("@") and not target_user:
            try:
                target_user = await client.get_users(p)
            except Exception:
                pass
        elif p.isdigit() and int(p) >= 100:
            amount = int(p)
        elif p.lower() in ("easy", "medium", "hard"):
            diff = p.lower()
        elif not target_user:
            try:
                target_user = await client.get_users(p)
            except Exception:
                pass

    if not target_user or amount < 100:
        return await message.reply_text(
            "<blockquote>💰 <b>𝐉𝐔𝐌𝐁𝐋𝐄 𝐁𝐄𝐓 𝐅𝐈𝐆𝐇𝐓 𝐔𝐒𝐀𝐆𝐄:</b>\n\n"
            "• <code>/jumblebetfight easy 500 @user</code>\n"
            "• <code>/jumblebetfight hard 1000 12345678</code>\n"
            "• Reply: <code>/jumblebetfight medium 200</code>\n\n"
            "📌 <b>Rules:</b> Minimum Bet: <b>100 points</b>\n"
            "🏆 75% Winner Reward | 🛡️ 25% Loser Cashback</blockquote>",
            parse_mode=ParseMode.HTML
        )

    if target_user.id == message.from_user.id:
        return await message.reply_text("<blockquote>❌ <b>Khud ke sath bet nahi khel sakte.</b></blockquote>", parse_mode=ParseMode.HTML)

    if target_user.is_bot:
        return await message.reply_text("<blockquote>❌ <b>Bots ke sath bet match nahi ho sakta.</b></blockquote>", parse_mode=ParseMode.HTML)

    ensure_user(target_user)
    u2 = get_user(target_user.id)

    if u1["points"] < amount:
        return await message.reply_text(f"<blockquote>❌ <b>Points kam hain!</b> Aapka balance: <code>{u1['points']} pts</code> | Bet: <code>{amount} pts</code></blockquote>", parse_mode=ParseMode.HTML)

    if u2["points"] < amount:
        m2_temp = get_mention(target_user)
        return await message.reply_text(f"<blockquote>❌ {m2_temp} ke balance me <code>{amount} pts</code> nahi hain!</blockquote>", parse_mode=ParseMode.HTML)

    key = message.chat.id
    if key in JUMBLE_FIGHT:
        return await message.reply_text("<blockquote>⚔️ <b>Already match running hai.</b></blockquote>", parse_mode=ParseMode.HTML)

    m1 = get_mention(message.from_user)
    m2 = get_mention(target_user)

    FIGHT_LOBBY[key] = {
        "p1": message.from_user.id,
        "p2": target_user.id,
        "p1_name": message.from_user.first_name,
        "p2_name": target_user.first_name,
        "m1": m1,
        "m2": m2,
        "difficulty": diff,
        "timer": 60,
        "is_bet": True,
        "bet_amount": amount,
        "is_rebet": False,
        "orig_stake": amount
    }

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"{'🟢 ' if diff=='easy' else '⚪ '}Easy", callback_data="f_diff_easy"),
            InlineKeyboardButton(f"{'🟡 ' if diff=='medium' else '⚪ '}Med", callback_data="f_diff_medium"),
            InlineKeyboardButton(f"{'🔴 ' if diff=='hard' else '⚪ '}Hard", callback_data="f_diff_hard")
        ],
        [
            InlineKeyboardButton("⏱️ 30s", callback_data="f_time_30"),
            InlineKeyboardButton("⏱️ 45s", callback_data="f_time_45"),
            InlineKeyboardButton("⏱️ 60s", callback_data="f_time_60")
        ],
        [
            InlineKeyboardButton("💰 𝐀ᴄᴄᴇᴘᴛ 𝐁ᴇᴛ", callback_data="f_accept"),
            InlineKeyboardButton("❌ 𝐃ᴇᴄʟɪɴᴇ", callback_data="f_decline")
        ]
    ])

    await message.reply_text(
        f"<blockquote>💰 <b>𝐉𝐔𝐌𝐁𝐋𝐄 𝐁𝐄𝐓 𝐅𝐈𝐆𝐇𝐓 𝐂𝐇𝐀𝐋𝐋𝐄𝐍𝐆𝐄!</b>\n\n"
        f"👤 <b>Challenger:</b> {m1}\n"
        f"🎯 <b>Opponent:</b> {m2}\n\n"
        f"💵 <b>Staked:</b> <code>{amount} pts each</code> (Pot: <code>{amount * 2} pts</code>)\n"
        f"🏆 <b>75% Winner Win:</b> <code>+{int(amount * 2 * 0.75)} pts</code>\n"
        f"🛡️ <b>25% Cashback:</b> <code>+{amount * 2 - int(amount * 2 * 0.75)} pts</code>\n\n"
        f"👉 {m2}, <b>Accept Bet</b> par click karein!</blockquote>",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )

# ============================================================
# ANSWER CHECKER
# ============================================================

ALL_BOT_COMMANDS = {
    "start", "help", "jumble", "jumblefight", "fight", "rapido", "jumblebetfight", "betfight",
    "settings", "setting", "setpoints", "sethint", "setdaily", "setbonus", "daily", "bonus",
    "private", "public", "addword", "addwords", "delword", "delallword", "delallwords",
    "clearword", "clearwords", "word", "words", "auth", "unauth", "authlist", "update", "gitpull",
    "stats", "stat", "mystats", "score", "profile", "leaderboard", "top", "rank", "lb",
    "backup", "dbbackup", "getdb", "addstar", "addpoints", "deductstar", "deductpoints", "removestar"
}

@app.on_message(filters.text & filters.group)
async def group_answer_handler(_, message: Message):
    if not message.from_user or not message.text:
        return

    txt = message.text.strip()
    if txt.startswith(("/", "!", ".")):
        cmd_candidate = txt[1:].split()[0].split("@")[0].lower()
        if cmd_candidate in ALL_BOT_COMMANDS:
            return

    chat_id = message.chat.id
    user_id = message.from_user.id
    cleaned_input = clean_answer(txt)

    if not cleaned_input:
        return

    if chat_id in JUMBLE_FIGHT:
        async with LOCK:
            game = JUMBLE_FIGHT.get(chat_id)
            if not game or user_id not in game["players"]:
                return

            if time.time() <= game["expires"] and cleaned_input == clean_answer(game["word"]):
                curr = asyncio.current_task()
                if game.get("task") and game["task"] is not curr and not game["task"].done():
                    try:
                        game["task"].cancel()
                    except Exception:
                        pass

                game["scores"][user_id] += 1

                s = get_settings(chat_id)
                if s["auto_delete"] and game.get("msg_id"):
                    await safe_delete_and_unpin(chat_id, game["msg_id"])

                u_mention = get_mention(message.from_user)
                r_msg = await message.reply_text(
                    f"<blockquote>⚡ {u_mention} <b>𝐖𝐎𝐍 𝐑𝐎𝐔𝐍𝐃 {game['round']}!</b>\n"
                    f"🏆 <b>Round Points:</b> <code>{game['scores'][user_id]}</code></blockquote>",
                    parse_mode=ParseMode.HTML
                )
                if s["auto_delete"]:
                    asyncio.create_task(delete_after(r_msg, 4))

                await asyncio.sleep(2.5)
                asyncio.create_task(fight_next(chat_id))
                return
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
        settings = get_settings(chat_id)
        pts_reward = get_global_config(f"points_{game['difficulty']}", 10)

        new_streak = u["streak"] + 1
        best = max(new_streak, u["best_streak"])

        DB.execute("""
            UPDATE users
            SET points=points+?, solved=solved+1, streak=?, best_streak=?
            WHERE user_id=?
        """, (pts_reward, new_streak, best, user_id))

        DB.execute("""
            INSERT INTO score_history (user_id, chat_id, points, timestamp)
            VALUES (?, ?, ?, ?)
        """, (user_id, chat_id, pts_reward, time.time()))
        DB.commit()

        if settings["auto_delete"] and game["message_id"]:
            await safe_delete_and_unpin(chat_id, game["message_id"])

        u_mention = get_mention(message.from_user)
        c_msg = await message.reply_text(
            f"<blockquote>🎉 <b>𝐂𝐎𝐑𝐑𝐄𝐂𝐓 𝐀𝐍𝐒𝐖𝐄𝐑!</b>\n\n"
            f"👤 {u_mention}\n"
            f"✅ <b>Word:</b> <code>{game['word'].upper()}</code>\n"
            f"⭐ <b>Reward:</b> <code>+{pts_reward} pts</code>\n"
            f"🔥 <b>Current Streak:</b> <code>{new_streak}</code>\n\n"
            f"🔄 <i>Next puzzle coming in 3s...</i></blockquote>",
            parse_mode=ParseMode.HTML
        )

        if settings["auto_delete"]:
            asyncio.create_task(delete_after(c_msg, 4))

        await asyncio.sleep(3)
        s = get_settings(chat_id)
        if chat_id not in JUMBLE_FIGHT and s["is_active"]:
            next_diff = s["default_diff"] if "default_diff" in s.keys() else "medium"
            asyncio.create_task(start_game(chat_id, next_diff, chat_id))

# ============================================================
# CALLBACK QUERIES ROUTER
# ============================================================

@app.on_callback_query()
async def callback_router(client: Client, query: CallbackQuery):
    data = query.data
    chat_id = query.message.chat.id
    user_id = query.from_user.id

    if data == "hint":
        game = DB.execute("SELECT * FROM games WHERE chat_id=? AND solved=0", (chat_id,)).fetchone()
        if not game:
            return await query.answer("Active puzzle nahi hai!", show_alert=True)

        ensure_user(query.from_user)
        puzzle_id = game["puzzle_id"]
        word = game["word"]
        difficulty = game["difficulty"]

        hint_limit = get_global_config(f"hints_{difficulty}", 3)
        hint_row = DB.execute("SELECT * FROM puzzle_hints WHERE chat_id=? AND puzzle_id=? AND user_id=?", (chat_id, puzzle_id, user_id)).fetchone()
        hints_used = hint_row["hints_used"] if hint_row else 0
        revealed_indices = [int(i) for i in hint_row["revealed_indices"].split(",") if i] if hint_row else []

        if hints_used >= hint_limit:
            return await query.answer(f"❌ Aapki {hint_limit} hints limit khatam ho chuki hai!", show_alert=True)

        available_indices = [i for i in range(len(word)) if i not in revealed_indices]
        if not available_indices:
            return await query.answer("❌ Aur letters reveal nahi kiye ja sakte.", show_alert=True)

        chosen_index = random.choice(available_indices)
        revealed_indices.append(chosen_index)
        hints_used += 1

        DB.execute("""
            INSERT INTO puzzle_hints(chat_id, puzzle_id, user_id, hints_used, revealed_indices)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, puzzle_id, user_id) DO UPDATE SET
                hints_used=excluded.hints_used,
                revealed_indices=excluded.revealed_indices
        """, (chat_id, puzzle_id, user_id, hints_used, ",".join(map(str, revealed_indices))))
        DB.commit()

        letter = word[chosen_index].upper()
        return await query.answer(f"💡 Letter #{chosen_index + 1} is '{letter}'\nHints Left: {hint_limit - hints_used}/{hint_limit}", show_alert=True)

    elif data == "fight_hint":
        game = JUMBLE_FIGHT.get(chat_id)
        if not game or user_id not in game["players"]:
            return await query.answer("❌ Sirf dueling players hints use kar sakte hain.", show_alert=True)

        left = game["hints_left"].get(user_id, 0)
        total_allowed = game.get("max_hints", 3)

        if left <= 0:
            return await query.answer(f"❌ Is round ke {total_allowed} hints use ho chuke hain!", show_alert=True)

        word = game["word"]
        revealed = game["round_revealed"][user_id]
        avail = [i for i in range(len(word)) if i not in revealed]
        if not avail:
            return await query.answer("❌ Saare letters already open hain.", show_alert=True)

        idx = random.choice(avail)
        revealed.append(idx)
        game["hints_left"][user_id] -= 1
        rem = game["hints_left"][user_id]

        return await query.answer(f"💡 Clue: Letter #{idx + 1} is '{word[idx].upper()}'\nRound Hints Remaining: {rem}/{total_allowed}", show_alert=True)

    elif data == "lb_open_inline":
        await query.answer()
        scope = "daily" if is_group(query.message) else "global"
        text, kb = build_leaderboard_text_and_kb(scope, chat_id)
        return await query.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

    elif data.startswith("refresh_stats_"):
        target_uid = int(data.split("_")[2])
        u = get_user(target_uid)
        if not u:
            return await query.answer("User record not found!", show_alert=True)

        card_text, kb = generate_stats_card(u)
        try:
            await query.message.edit_text(card_text, reply_markup=kb, parse_mode=ParseMode.HTML)
            await query.answer("Stats updated!")
        except MessageNotModified:
            await query.answer("Already updated.")

    elif data.startswith("lb_"):
        await query.answer()
        parts = data.split("_")
        scope = parts[1]
        target_chat = int(parts[2]) if parts[2] != "0" else chat_id

        text, kb = build_leaderboard_text_and_kb(scope, target_chat)
        try:
            await query.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        except MessageNotModified:
            pass

    elif data.startswith("wb_"):
        await query.answer()
        if not is_authed(user_id):
            return await query.answer("❌ Sirf Auth Users word bank dekh sakte hain.", show_alert=True)

        _, diff, page_str = data.split("_")
        page = int(page_str)
        word_list = sorted(WORDS.get(diff, []))
        total_words = len(word_list)
        per_page = 20
        total_pages = max(1, (total_words + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))

        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        page_words = word_list[start_idx:end_idx]

        formatted_list = "  •  ".join(f"<code>{w.upper()}</code>" for w in page_words) if page_words else "<i>Koi words available nahi hain.</i>"

        nav_row = []
        if page > 1:
            nav_row.append(InlineKeyboardButton("⬅️ 𝐏ʀᴇᴠ", callback_data=f"wb_{diff}_{page - 1}"))
        nav_row.append(InlineKeyboardButton(f"📄 {page}/{total_pages}", callback_data="noop_page"))
        if page < total_pages:
            nav_row.append(InlineKeyboardButton("𝐍ᴇxᴛ ➡️", callback_data=f"wb_{diff}_{page + 1}"))

        kb = InlineKeyboardMarkup([
            nav_row,
            [
                InlineKeyboardButton("🟢 𝐄ᴀsʏ", callback_data="wb_easy_1"),
                InlineKeyboardButton("🟡 𝐌ᴇᴅɪᴜᴍ", callback_data="wb_medium_1"),
                InlineKeyboardButton("🔴 𝐇ᴀʀᴅ", callback_data="wb_hard_1")
            ],
            [
                InlineKeyboardButton("🔙 𝐁ᴀᴄᴋ ᴛᴏ 𝐌ᴇɴᴜ", callback_data="back_to_words_menu"),
                InlineKeyboardButton("❌ 𝐂𝐥𝐨𝐬𝐞", callback_data="close_panel")
            ]
        ])

        msg = (
            f"<blockquote>📚 <b>{diff.upper()} 𝐖𝐎𝐑𝐃𝐒 𝐁𝐀𝐍𝐊</b> (Total: <code>{total_words}</code>)\n"
            f"📌 <i>Tap to copy:</i>\n\n"
            f"{formatted_list}\n\n"
            f"➕ <b>Add:</b> <code>/addword {diff} word</code>\n"
            f"🗑️ <b>Del:</b> <code>/delword {diff} word</code></blockquote>"
        )
        try:
            await query.message.edit_text(msg, reply_markup=kb, parse_mode=ParseMode.HTML)
        except MessageNotModified:
            pass

    elif data == "noop_page":
        await query.answer("Page indicator", show_alert=False)

    elif data == "back_to_words_menu":
        await query.answer()
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(f"🟢 𝐄ᴀsʏ ({len(WORDS['easy'])})", callback_data="wb_easy_1"),
                InlineKeyboardButton(f"🟡 𝐌ᴇᴅɪᴜᴍ ({len(WORDS['medium'])})", callback_data="wb_medium_1"),
                InlineKeyboardButton(f"🔴 𝐇ᴀʀᴅ ({len(WORDS['hard'])})", callback_data="wb_hard_1")
            ],
            [
                InlineKeyboardButton("❌ 𝐂𝐥𝐨𝐬𝐞", callback_data="close_panel")
            ]
        ])
        try:
            await query.message.edit_text(
                "<blockquote>📚 <b>𝐉𝐔𝐌𝐁𝐋𝐄 𝐖𝐎𝐑𝐃 𝐁𝐀𝐍𝐊</b>\n\n"
                f"🟢 <b>Easy Words:</b> <code>{len(WORDS['easy'])}</code>\n"
                f"🟡 <b>Medium Words:</b> <code>{len(WORDS['medium'])}</code>\n"
                f"🔴 <b>Hard Words:</b> <code>{len(WORDS['hard'])}</code>\n\n"
                "📌 <b>Add Words in Bulk:</b>\n"
                "<code>/addword easy cat dog bird lion tiger</code></blockquote>",
                reply_markup=kb,
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass

    elif data == "rebet_challenge":
        rebet = REBET_LOBBY.get(chat_id)
        if not rebet:
            return await query.answer("Rebet challenge expire ho chuka hai.", show_alert=True)

        if user_id != rebet["original_loser"]:
            return await query.answer("❌ Yeh comeback option sirf pichle match loser ke liye hai!", show_alert=True)

        if chat_id in JUMBLE_FIGHT:
            return await query.answer("Match already ongoing hai.", show_alert=True)

        u_loser = get_user(rebet["original_loser"])
        u_winner = get_user(rebet["original_winner"])
        rebet_amt = rebet["rebet_amount"]

        if u_loser["points"] < rebet_amt:
            return await query.answer(f"Aapke paas {rebet_amt} points nahi hain.", show_alert=True)
        if u_winner["points"] < rebet_amt:
            return await query.answer(f"Opponent ke paas {rebet_amt} points nahi hain.", show_alert=True)

        FIGHT_LOBBY[chat_id] = {
            "p1": rebet["original_loser"],
            "p2": rebet["original_winner"],
            "p1_name": u_loser["name"],
            "p2_name": u_winner["name"],
            "m1": rebet["loser_mention"],
            "m2": rebet["winner_mention"],
            "difficulty": rebet["difficulty"],
            "timer": rebet["timer"],
            "is_bet": True,
            "bet_amount": rebet_amt,
            "is_rebet": True,
            "orig_stake": rebet.get("orig_stake", rebet_amt * 4)
        }

        del REBET_LOBBY[chat_id]
        await query.answer("Comeback match proposed!")

        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔥 𝐀ᴄᴄᴇᴘᴛ 𝐂ᴏᴍᴇʙᴀᴄᴋ", callback_data="f_accept"),
                InlineKeyboardButton("❌ 𝐃ᴇᴄʟɪɴᴇ", callback_data="f_decline")
            ]
        ])

        await app.send_message(
            chat_id,
            f"<blockquote>⚔️ <b>25% 𝐂𝐎𝐌𝐄𝐁𝐀𝐂𝐊 𝐑𝐄-𝐁𝐄𝐓 𝐂𝐇𝐀𝐋𝐋𝐄𝐍𝐆𝐄!</b>\n\n"
            f"👤 <b>Challenger (Comeback):</b> {rebet['loser_mention']}\n"
            f"🎯 <b>Opponent (Champion):</b> {rebet['winner_mention']}\n\n"
            f"💵 <b>Stake:</b> <code>{rebet_amt} pts each</code> (Pot: <code>{rebet_amt * 2} pts</code>)\n"
            f"🏆 <b>Total Win:</b> <code>{rebet_amt * 2 + 100} points</code> (+100 Comeback Stars included!)\n\n"
            f"👉 {rebet['winner_mention']}, comeback rematch accept karein?</blockquote>",
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )

    elif data.startswith("f_"):
        lobby = FIGHT_LOBBY.get(chat_id)
        if not lobby:
            return await query.answer("Challenge expired.", show_alert=True)

        if data == "f_decline":
            if user_id != lobby["p2"] and user_id != lobby["p1"] and not await is_admin_or_owner(query.message.chat, user_id):
                return await query.answer("❌ Match players hi decline kar sakte hain.", show_alert=True)

            del FIGHT_LOBBY[chat_id]
            await query.message.delete()
            return await query.answer("Match declined.")

        if data == "f_accept":
            if user_id != lobby["p2"]:
                return await query.answer("❌ Challenge target player hi accept kar sakta hai!", show_alert=True)

            diff = lobby["difficulty"]
            per_round_hints = int(get_global_config(f"hints_{diff}", 3))

            if lobby.get("is_bet"):
                b_amt = lobby["bet_amount"]
                u1 = get_user(lobby["p1"])
                u2 = get_user(lobby["p2"])

                if u1["points"] < b_amt:
                    del FIGHT_LOBBY[chat_id]
                    return await query.message.edit_text(f"<blockquote>❌ Challenger ke paas <code>{b_amt} pts</code> nahi hain. Cancelled.</blockquote>", parse_mode=ParseMode.HTML)

                if u2["points"] < b_amt:
                    del FIGHT_LOBBY[chat_id]
                    return await query.message.edit_text(f"<blockquote>❌ Opponent ke paas <code>{b_amt} pts</code> nahi hain. Cancelled.</blockquote>", parse_mode=ParseMode.HTML)

                DB.execute("UPDATE users SET points = points - ? WHERE user_id = ?", (b_amt, lobby["p1"]))
                DB.execute("UPDATE users SET points = points - ? WHERE user_id = ?", (b_amt, lobby["p2"]))

                now = time.time()
                DB.execute("INSERT INTO score_history (user_id, chat_id, points, timestamp) VALUES (?, ?, ?, ?)", (lobby["p1"], chat_id, -b_amt, now))
                DB.execute("INSERT INTO score_history (user_id, chat_id, points, timestamp) VALUES (?, ?, ?, ?)", (lobby["p2"], chat_id, -b_amt, now))
                DB.commit()

            JUMBLE_FIGHT[chat_id] = {
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
                "is_bet": lobby.get("is_bet", False),
                "bet_amount": lobby.get("bet_amount", 0),
                "is_rebet": lobby.get("is_rebet", False),
                "orig_stake": lobby.get("orig_stake", lobby.get("bet_amount", 0)),
                "max_hints": per_round_hints,
                "hints_left": {
                    lobby["p1"]: per_round_hints,
                    lobby["p2"]: per_round_hints
                },
                "round_revealed": {
                    lobby["p1"]: [],
                    lobby["p2"]: []
                }
            }
            del FIGHT_LOBBY[chat_id]

            await query.message.delete()
            await query.answer("🚀 Match Commencing!")

            bet_text = f" (Bet: <b>{JUMBLE_FIGHT[chat_id]['bet_amount']} pts</b> each)" if JUMBLE_FIGHT[chat_id]["is_bet"] else ""
            announcement = await app.send_message(
                chat_id,
                f"<blockquote>🔥 <b>𝐃𝐔𝐄𝐋 𝐀𝐂𝐂𝐄𝐏𝐓𝐄𝐃 𝐁𝐘 {lobby['m2']}!</b>\n\n"
                f"⚔️ <b>{lobby['m1']}</b> 🆚 <b>{lobby['m2']}</b>{bet_text}\n"
                f"💡 <b>Hints:</b> <code>{per_round_hints} hints/round</code>\n"
                f"🚀 <i>Battle starting in 3 seconds...</i></blockquote>",
                parse_mode=ParseMode.HTML
            )
            asyncio.create_task(delete_after(announcement, 4))

            await asyncio.sleep(3)
            asyncio.create_task(fight_next(chat_id))
            return

        if user_id not in (lobby["p1"], lobby["p2"]) and not await is_admin_or_owner(query.message.chat, user_id):
            return await query.answer("❌ Only players can adjust duel settings.", show_alert=True)

        if data.startswith("f_diff_"):
            lobby["difficulty"] = data.split("_")[2]
            await query.answer(f"Difficulty: {lobby['difficulty'].upper()}")
        elif data.startswith("f_time_"):
            lobby["timer"] = int(data.split("_")[2])
            await query.answer(f"Timer: {lobby['timer']}s")

        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(f"{'🟢 ' if lobby['difficulty']=='easy' else '⚪ '}Easy", callback_data="f_diff_easy"),
                InlineKeyboardButton(f"{'🟡 ' if lobby['difficulty']=='medium' else '⚪ '}Med", callback_data="f_diff_medium"),
                InlineKeyboardButton(f"{'🔴 ' if lobby['difficulty']=='hard' else '⚪ '}Hard", callback_data="f_diff_hard")
            ],
            [
                InlineKeyboardButton(f"{'⏱️ ' if lobby['timer']==30 else '⚪ '}30s", callback_data="f_time_30"),
                InlineKeyboardButton(f"{'⏱️ ' if lobby['timer']==45 else '⚪ '}45s", callback_data="f_time_45"),
                InlineKeyboardButton(f"{'⏱️ ' if lobby['timer']==60 else '⚪ '}60s", callback_data="f_time_60")
            ],
            [
                InlineKeyboardButton("⚔️ 𝐀ᴄᴄᴇᴘᴛ 𝐃ᴜᴇʟ", callback_data="f_accept"),
                InlineKeyboardButton("❌ 𝐃ᴇᴄʟɪɴᴇ", callback_data="f_decline")
            ]
        ])

        header_str = "💰 <b>𝐉𝐔𝐌𝐁𝐋𝐄 𝐁𝐄𝐓 𝐅𝐈𝐆𝐇𝐓 1v1!</b>" if lobby.get("is_bet") else "⚔️ <b>𝐉𝐔𝐌𝐁𝐋𝐄 1v1 𝐃𝐔𝐄𝐋!</b>"
        bet_info = f"\n💵 <b>Stake:</b> <code>{lobby['bet_amount']} pts each</code>" if lobby.get("is_bet") else ""

        try:
            await query.message.edit_text(
                f"<blockquote>{header_str}\n\n"
                f"👤 <b>Challenger:</b> {lobby['m1']}\n"
                f"🎯 <b>Opponent:</b> {lobby['m2']}\n\n"
                f"⚙️ <b>Mode:</b> <code>{lobby['difficulty'].title()}</code> | ⏱️ <b>Timer:</b> <code>{lobby['timer']}s</code>{bet_info}\n\n"
                f"👉 {lobby['m2']}, <b>Accept Duel</b> par click karein!</blockquote>",
                reply_markup=kb,
                parse_mode=ParseMode.HTML
            )
        except MessageNotModified:
            pass

    elif data.startswith("set_"):
        if not query.from_user or not await is_admin_or_owner(query.message.chat, user_id):
            return await query.answer("❌ Only group admins can manage settings.", show_alert=True)

        if data == "set_start_game":
            DB.execute("UPDATE settings SET is_active=1 WHERE chat_id=?", (chat_id,))
            DB.commit()
            await query.answer("▶️ Game started!")
            await show_settings_panel(query.message, chat_id)
            s = get_settings(chat_id)
            asyncio.create_task(start_game(chat_id, s["default_diff"], query.message))

        elif data == "set_stop_game":
            DB.execute("UPDATE settings SET is_active=0 WHERE chat_id=?", (chat_id,))
            old_g = DB.execute("SELECT message_id FROM games WHERE chat_id=?", (chat_id,)).fetchone()
            s = get_settings(chat_id)
            if old_g and s["auto_delete"] and old_g["message_id"]:
                await safe_delete_and_unpin(chat_id, old_g["message_id"])
            DB.execute("DELETE FROM games WHERE chat_id=?", (chat_id,))
            DB.commit()
            await query.answer("⏹️ Game stopped!")
            await show_settings_panel(query.message, chat_id)

        elif data == "set_toggle_autodel":
            s = get_settings(chat_id)
            new_val = 0 if s["auto_delete"] else 1
            DB.execute("UPDATE settings SET auto_delete=? WHERE chat_id=?", (new_val, chat_id))
            DB.commit()
            await query.answer(f"Auto Delete {'Enabled' if new_val else 'Disabled'}")
            await show_settings_panel(query.message, chat_id)

        elif data == "set_menu_mode":
            kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🟢 𝐄ᴀsʏ", callback_data="set_def_easy"),
                    InlineKeyboardButton("🟡 𝐌ᴇᴅɪᴜᴍ", callback_data="set_def_medium"),
                    InlineKeyboardButton("🔴 𝐇ᴀʀᴅ", callback_data="set_def_hard")
                ],
                [InlineKeyboardButton("🔙 𝐁ᴀᴄᴋ", callback_data="set_back")]
            ])
            try:
                await query.message.edit_text("<blockquote>🎯 <b>Default Difficulty Select Karein:</b></blockquote>", reply_markup=kb, parse_mode=ParseMode.HTML)
            except MessageNotModified:
                pass

        elif data == "set_menu_timers":
            s = get_settings(chat_id)
            kb = build_timers_keyboard(s)
            try:
                await query.message.edit_text("<blockquote>⏱️ <b>Select Duration per Round:</b></blockquote>", reply_markup=kb, parse_mode=ParseMode.HTML)
            except MessageNotModified:
                pass

        elif data.startswith("set_def_"):
            d = data.split("_")[2]
            DB.execute("UPDATE settings SET default_diff=? WHERE chat_id=?", (d, chat_id))
            DB.commit()
            await query.answer(f"Default: {d.upper()}")
            await show_settings_panel(query.message, chat_id)

        elif data.startswith("set_t_"):
            parts = data.split("_")
            diff = parts[2].lower()
            secs = int(parts[3])

            if diff in ("easy", "medium", "hard"):
                DB.execute(f"UPDATE settings SET {diff}=? WHERE chat_id=?", (secs, chat_id))
                DB.commit()
                await query.answer(f"✅ {diff.title()} timer updated to {secs}s")

            s = get_settings(chat_id)
            kb = build_timers_keyboard(s)
            try:
                await query.message.edit_reply_markup(reply_markup=kb)
            except MessageNotModified:
                pass

        elif data == "set_back":
            await show_settings_panel(query.message, chat_id)

    elif data == "skip":
        if not query.from_user or not await is_admin_or_owner(query.message.chat, user_id):
            return await query.answer("❌ Only admins can skip.", show_alert=True)

        game = DB.execute("SELECT * FROM games WHERE chat_id=? AND solved=0", (chat_id,)).fetchone()
        if not game:
            return await query.answer("Active puzzle nahi mila.", show_alert=True)

        DB.execute("UPDATE games SET solved=1 WHERE chat_id=?", (chat_id,))
        DB.commit()

        s = get_settings(chat_id)
        if s["auto_delete"] and game["message_id"]:
            await safe_delete_and_unpin(chat_id, game["message_id"])

        sk_msg = await query.message.reply_text(f"<blockquote>⏭️ <b>𝐒𝐊𝐈𝐏𝐏𝐄𝐃!</b>\n<b>Answer:</b> <code>{game['word'].upper()}</code>\n\n🔄 <i>Next in 3s...</i></blockquote>", parse_mode=ParseMode.HTML)
        if s["auto_delete"]:
            asyncio.create_task(delete_after(sk_msg, 4))

        await query.answer("Skipped.")
        await asyncio.sleep(3)
        s = get_settings(chat_id)
        if s["is_active"]:
            next_diff = s["default_diff"] if "default_diff" in s.keys() else "medium"
            asyncio.create_task(start_game(chat_id, next_diff, chat_id))

    elif data == "newword":
        old = DB.execute("SELECT * FROM games WHERE chat_id=?", (chat_id,)).fetchone()
        if old and not old["solved"] and time.time() <= old["expires"]:
            return await query.answer("❌ Current puzzle abhi chal raha hai.", show_alert=True)

        s = get_settings(chat_id)
        difficulty = s["default_diff"] if "default_diff" in s.keys() else "medium"
        await query.answer("🧩 Loading new word...")
        asyncio.create_task(start_game(chat_id, difficulty, query.message))

    elif data == "close_panel":
        await query.message.delete()

async def show_settings_panel(message_obj, chat_id):
    s = get_settings(chat_id)
    cur_diff = s["default_diff"] if "default_diff" in s.keys() else "medium"
    status_btn = InlineKeyboardButton("⏹️ 𝐒ᴛᴏᴘ 𝐆ᴀᴍᴇ", callback_data="set_stop_game") if s["is_active"] else InlineKeyboardButton("▶️ 𝐒ᴛᴀʀᴛ 𝐆ᴀᴍᴇ", callback_data="set_start_game")
    del_btn = InlineKeyboardButton("🗑️ 𝐀ᴜᴛᴏ-𝐃ᴇʟ: 𝐎𝐍", callback_data="set_toggle_autodel") if s["auto_delete"] else InlineKeyboardButton("🗑️ 𝐀ᴜᴛᴏ-𝐃ᴇʟ: 𝐎𝐅𝐅", callback_data="set_toggle_autodel")

    p_easy = get_global_config("points_easy", 10)
    p_med = get_global_config("points_medium", 20)
    p_hard = get_global_config("points_hard", 30)

    h_easy = get_global_config("hints_easy", 3)
    h_med = get_global_config("hints_medium", 3)
    h_hard = get_global_config("hints_hard", 3)

    kb = InlineKeyboardMarkup([
        [
            status_btn,
            InlineKeyboardButton(f"🎯 𝐌ᴏᴅᴇ: {str(cur_diff).upper()}", callback_data="set_menu_mode")
        ],
        [
            InlineKeyboardButton("⏱️ 𝐓ɪᴍᴇʀs", callback_data="set_menu_timers"),
            del_btn
        ],
        [
            InlineKeyboardButton("❌ 𝐂𝐥𝐨𝐬𝐞", callback_data="close_panel")
        ]
    ])
    text = (
        f"<blockquote>⚙️ <b>𝐉𝐔𝐌𝐁𝐋𝐄 𝐆𝐑𝐎𝐔𝐏 𝐂𝐎𝐍𝐅𝐈𝐆𝐔𝐑𝐀𝐓𝐈𝐎𝐍</b>\n\n"
        f"🟢 <b>Status:</b> <code>{'Running' if s['is_active'] else 'Stopped'}</code>\n"
        f"🗑️ <b>Auto Delete Old:</b> <code>{'Enabled' if s['auto_delete'] else 'Disabled'}</code>\n"
        f"🎯 <b>Default Difficulty:</b> <code>{str(cur_diff).title()}</code>\n"
        f"⏱️ <b>Group Timers:</b> Easy: <code>{s['easy']}s</code> | Med: <code>{s['medium']}s</code> | Hard: <code>{s['hard']}s</code>\n\n"
        f"🌍 <b>Global Rewards:</b> Easy: <code>+{p_easy}</code> | Med: <code>+{p_med}</code> | Hard: <code>+{p_hard}</code>\n"
        f"💡 <b>Hint Limits:</b> Easy: <code>{h_easy}</code> | Med: <code>{h_med}</code> | Hard: <code>{h_hard}</code></blockquote>"
    )
    try:
        await message_obj.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except MessageNotModified:
        pass

# ============================================================
# AUTO-RESUME GAMES
# ============================================================

async def resume_all_active_games():
    await asyncio.sleep(3)
    rows = DB.execute("SELECT chat_id, default_diff FROM settings WHERE is_active = 1 AND chat_id != 0").fetchall()
    for row in rows:
        c_id = row["chat_id"]
        diff = row["default_diff"] or "medium"
        try:
            DB.execute("DELETE FROM games WHERE chat_id=?", (c_id,))
            DB.commit()
            await start_game(c_id, diff, c_id)
            await asyncio.sleep(0.8)
        except Exception as e:
            print(f"Error resuming group {c_id}: {e}")

# ============================================================
# START BOT
# ============================================================

if __name__ == "__main__":
    print("🚀 Upgraded Modern Jumble Bot Starting...")
    asyncio.get_event_loop().create_task(resume_all_active_games())
    asyncio.get_event_loop().create_task(auto_backup_task())
    app.run()
