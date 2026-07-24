import os
import sqlite3

# ══════════════════════════════════════════════════════════════════════════════
# 🔑  BOT CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════
# The bot token must NOT be hardcoded here. Set it as an environment variable
# named TELEGRAM_BOT_TOKEN (e.g. in Railway's service variables). For local
# development only, you may optionally set BOT_TOKEN below as a fallback —
# never commit a real token to the repository.
BOT_TOKEN = None   # ← Optional local dev fallback; leave as None in production
# ══════════════════════════════════════════════════════════════════════════════
import logging
import random
import requests
from datetime import datetime
from typing import Optional, Dict

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ConversationHandler,
    CallbackQueryHandler, filters, ContextTypes
)
from telegram.error import TelegramError

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
CHANNELS    = ["@earnwithsakx", "@blankkdealz"]
CHAN_LINKS  = ["https://t.me/earnwithsakx", "https://t.me/blankkdealz"]
ADMIN_IDS   = [6894923643, 1446058092]
DB_PATH     = "bot/bot.db"
REFERRAL_POINTS = 2
DEFAULT_BREVI_REF = "SAKS240387"   # initial global default; admins can change it

INDIAN_FIRST = [
    "Arjun","Aarav","Vihaan","Vivaan","Ananya","Diya","Aadhya","Sai",
    "Rohan","Siddharth","Kunal","Rahul","Priya","Neha","Pooja","Anjali",
    "Raj","Amit","Vikram","Tarun","Meera","Kavya","Ishita","Tanvi",
    "Aditya","Karthik","Varun","Dhruv","Shreya","Riya","Sanya","Navya"
]
INDIAN_LAST = [
    "Sharma","Verma","Patel","Kumar","Singh","Reddy","Gupta","Joshi",
    "Nair","Menon","Shetty","Rao","Desai","Mehta","Choudhury","Malhotra",
    "Khanna","Kapoor","Sinha","Thakur","Yadav","Mishra","Tripathi","Dwivedi"
]

# ── Conversation states ───────────────────────────────────────────────────────
(
    MAIN_MENU,
    MOBILE, OTP_EXISTING, EMAIL, OTP_NEW,
    ADMIN_GIVE_USER, ADMIN_GIVE_AMOUNT, ADMIN_SET_POINTS,
    SET_REF_CODE, ADMIN_SET_REFCODE
) = range(10)

# ── Database ──────────────────────────────────────────────────────────────────

def db():
    return sqlite3.connect(DB_PATH)


def init_db():
    con = db()
    c = con.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id   INTEGER PRIMARY KEY,
            username  TEXT,
            first_name TEXT,
            points    INTEGER DEFAULT 0,
            referred_by INTEGER,
            verified  INTEGER DEFAULT 0,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS referrals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER,
            referred_id INTEGER,
            completed   INTEGER DEFAULT 0,
            created_at  TEXT
        );
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    # Add brevi_ref_code column if it doesn't exist yet (migration-safe)
    try:
        c.execute("ALTER TABLE users ADD COLUMN brevi_ref_code TEXT")
    except Exception:
        pass
    c.execute("INSERT OR IGNORE INTO settings VALUES ('points_per_run','1')")
    c.execute("INSERT OR IGNORE INTO settings VALUES ('brevi_ref_code', ?)", (DEFAULT_BREVI_REF,))
    con.commit()
    con.close()


def get_user(user_id: int):
    con = db(); c = con.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone(); con.close(); return row

def ensure_user(user_id: int, username: str, first_name: str, referred_by: int = None):
    con = db(); c = con.cursor()
    c.execute(
        "INSERT OR IGNORE INTO users (user_id,username,first_name,referred_by,created_at) VALUES (?,?,?,?,?)",
        (user_id, username, first_name, referred_by, datetime.now().isoformat())
    )
    con.commit(); con.close()

def get_points(user_id: int) -> int:
    con = db(); c = con.cursor()
    c.execute("SELECT points FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone(); con.close()
    return row[0] if row else 0

def add_points(user_id: int, amount: int):
    con = db(); c = con.cursor()
    c.execute("UPDATE users SET points=points+? WHERE user_id=?", (amount, user_id))
    con.commit(); con.close()

def deduct_points(user_id: int, amount: int):
    con = db(); c = con.cursor()
    c.execute("UPDATE users SET points=MAX(0,points-?) WHERE user_id=?", (amount, user_id))
    con.commit(); con.close()

def set_verified(user_id: int):
    con = db(); c = con.cursor()
    c.execute("UPDATE users SET verified=1 WHERE user_id=?", (user_id,))
    con.commit(); con.close()

def is_verified(user_id: int) -> bool:
    con = db(); c = con.cursor()
    c.execute("SELECT verified FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone(); con.close()
    return bool(row and row[0])

def get_setting(key: str) -> str:
    con = db(); c = con.cursor()
    c.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = c.fetchone(); con.close()
    return row[0] if row else "1"

def set_setting(key: str, value: str):
    con = db(); c = con.cursor()
    c.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, value))
    con.commit(); con.close()

def complete_referral(referred_id: int) -> Optional[int]:
    """Credit referrer with REFERRAL_POINTS if not already done. Returns referrer_id or None."""
    con = db(); c = con.cursor()
    c.execute("SELECT referred_by FROM users WHERE user_id=?", (referred_id,))
    row = c.fetchone()
    if not row or not row[0]:
        con.close(); return None
    referrer_id = row[0]
    c.execute("SELECT id FROM referrals WHERE referred_id=? AND completed=1", (referred_id,))
    if c.fetchone():
        con.close(); return None   # already rewarded
    c.execute("UPDATE users SET points=points+? WHERE user_id=?", (REFERRAL_POINTS, referrer_id))
    c.execute(
        "INSERT INTO referrals (referrer_id,referred_id,completed,created_at) VALUES (?,?,1,?)",
        (referrer_id, referred_id, datetime.now().isoformat())
    )
    con.commit(); con.close()
    return referrer_id

def count_referrals(user_id: int) -> int:
    con = db(); c = con.cursor()
    c.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id=? AND completed=1", (user_id,))
    row = c.fetchone(); con.close()
    return row[0] if row else 0

def get_all_users(limit=20):
    con = db(); c = con.cursor()
    c.execute(
        "SELECT user_id,username,first_name,points,verified FROM users ORDER BY points DESC LIMIT ?",
        (limit,)
    )
    rows = c.fetchall(); con.close(); return rows

def set_user_points(user_id: int, points: int):
    con = db(); c = con.cursor()
    c.execute("UPDATE users SET points=? WHERE user_id=?", (points, user_id))
    affected = c.rowcount; con.commit(); con.close()
    return affected > 0

def get_user_brevi_ref(user_id: int) -> Optional[str]:
    """Return user's personal Brevistay ref code, or None if not set."""
    con = db(); c = con.cursor()
    c.execute("SELECT brevi_ref_code FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone(); con.close()
    return row[0] if row and row[0] else None

def set_user_brevi_ref(user_id: int, code: str):
    con = db(); c = con.cursor()
    c.execute("UPDATE users SET brevi_ref_code=? WHERE user_id=?", (code.strip().upper(), user_id))
    con.commit(); con.close()

def get_global_brevi_ref() -> str:
    """Return admin-set global default Brevistay referral code."""
    return get_setting("brevi_ref_code") or DEFAULT_BREVI_REF

def effective_brevi_ref(user_id: int) -> str:
    """User's personal code takes priority; falls back to global default."""
    return get_user_brevi_ref(user_id) or get_global_brevi_ref()

# ── Brevistay client ──────────────────────────────────────────────────────────

class BrevistayClient:
    def __init__(self):
        self.base_url = "https://cst.brevistay.com"
        self.web_url  = "https://www.brevistay.com"
        self.session  = requests.Session()
        self.token = self.user_name = self.user_last_name = None
        self.user_email = self.user_mobile = None
        self.default_headers = {
            "User-Agent": "okhttp/4.12.0",
            "Accept-Encoding": "gzip",
            "brevi-channel": "ANDROID",
            "brevi-channel-version": "6.0.8"
        }
        self.web_headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; Mobile) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "com.brevistay.customer",
            "Referer": "https://www.brevistay.com/"
        }

    @staticmethod
    def random_name():
        return random.choice(INDIAN_FIRST), random.choice(INDIAN_LAST)

    @staticmethod
    def random_email(first, last, mobile):
        domains = ["gmail.com","yahoo.com","outlook.com","protonmail.com","hotmail.com"]
        return f"{first.lower()}.{last.lower()}{mobile[-4:]}{random.randint(100,999)}@{random.choice(domains)}"

    def _post(self, url, **kw):
        return self.session.post(url, headers={**self.default_headers,"Content-Type":"application/json; charset=UTF-8"}, **kw)

    def send_otp(self, mobile: str) -> dict:
        return self._post(f"{self.base_url}/app-api/login",
            json={"is_otp":1,"is_password":0,"mobile":mobile,"otp":123456,"password":""}
        ).json()

    def login(self, mobile: str, otp: str, ref_code: str = DEFAULT_BREVI_REF) -> dict:
        data = self._post(f"{self.base_url}/app-api/verify-user",
            json={"channel":"MOBILE","is_otp":1,"is_password":0,
                  "mobile":mobile,"otp":int(otp),"ref_code":ref_code}
        ).json()
        self._save_token(data); return data

    def register(self, email, mobile, name, last_name, otp,
                 ref_code: str = DEFAULT_BREVI_REF) -> dict:
        data = self._post(f"{self.base_url}/app-api/verify-user",
            json={"channel":"MOBILE","email":email,"is_otp":1,"is_password":0,
                  "lastName":last_name,"mobile":int(mobile),"name":name,
                  "otp":int(otp),"password":"12345","ref_code":ref_code}
        ).json()
        if data.get("token"):
            self.user_name = name; self.user_last_name = last_name
            self.user_email = email; self.user_mobile = mobile
        self._save_token(data); return data

    def get_profile(self) -> dict:
        return self.session.post(f"{self.base_url}/app-api/user-profile",
            headers={**self.default_headers,"Content-Length":"0"}, data=""
        ).json()

    def resend_email_verify(self) -> dict:
        return self.session.get(f"{self.web_url}/cst/app-api/resend_email_verification",
            headers={**self.web_headers,"authorization":f"Bearer {self.token}"}
        ).json()

    def _save_token(self, data: dict):
        if data.get("token"):
            self.token = data["token"]
            self.user_name      = data.get("user_first_name") or self.user_name
            self.user_last_name = data.get("user_last_name")  or self.user_last_name
            self.user_email     = data.get("user_email_id")   or self.user_email
            self.user_mobile    = data.get("user_mobile_number") or self.user_mobile
            b = f"Bearer {self.token}"
            self.default_headers["authorization"] = b
            self.web_headers["authorization"]     = b

# ── Helpers ───────────────────────────────────────────────────────────────────

async def check_channels(bot, user_id: int) -> bool:
    for ch in CHANNELS:
        try:
            m = await bot.get_chat_member(chat_id=ch, user_id=user_id)
            if m.status in ("left", "kicked", "banned"):
                return False
        except TelegramError:
            return False
    return True

def client_of(context) -> BrevistayClient:
    if "client" not in context.user_data:
        context.user_data["client"] = BrevistayClient()
    return context.user_data["client"]

def points_per_run() -> int:
    return int(get_setting("points_per_run") or "1")

# ── Keyboards ─────────────────────────────────────────────────────────────────

def kb_channels():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Channel 1 — earnwithsakx", url=CHAN_LINKS[0])],
        [InlineKeyboardButton("📢 Channel 2 — blankkdealz",  url=CHAN_LINKS[1])],
        [InlineKeyboardButton("✅ I've Joined Both Channels", callback_data="verify_channels")],
    ])

def kb_main(user_id: int, pts: int):
    ppr = points_per_run()
    rows = [
        [InlineKeyboardButton(f"🚀 Run Brevistay  ({ppr} pt)", callback_data="run_brevistay")],
        [
            InlineKeyboardButton("🔗 Referral Link", callback_data="referral_link"),
            InlineKeyboardButton("📊 My Stats",       callback_data="my_stats"),
        ],
        [InlineKeyboardButton("🎁 My Brevistay Refer Code", callback_data="set_ref_code")],
    ]
    if user_id in ADMIN_IDS:
        rows.append([InlineKeyboardButton("🔧 Admin Panel", callback_data="admin_panel")])
    return InlineKeyboardMarkup(rows)

def kb_admin():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 Give Points to User",      callback_data="adm_give")],
        [InlineKeyboardButton("⚙️ Change Points Per Run",    callback_data="adm_set_ppr")],
        [InlineKeyboardButton("🔑 Set Default Refer Code",   callback_data="adm_set_refcode")],
        [InlineKeyboardButton("📋 View Top Users",           callback_data="adm_users")],
        [InlineKeyboardButton("🔙 Back to Menu",             callback_data="back_menu")],
    ])

def kb_back_admin():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin_panel")]])

def kb_back_menu(user_id: int, pts: int):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="back_menu")]])

def kb_email(auto_email: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅ Use auto email", callback_data="use_auto_email")],
        [InlineKeyboardButton("✏️ Enter my own email", callback_data="enter_own_email")],
    ])

def kb_cancel_flow():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_flow")]])

# ── /start ────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    args = context.args or []
    referred_by = None
    if args and args[0].startswith("ref_"):
        try:
            referred_by = int(args[0][4:])
            if referred_by == user.id:
                referred_by = None  # can't refer yourself
        except ValueError:
            pass

    # Ensure user exists in DB
    ensure_user(user.id, user.username or "", user.first_name or "", referred_by)
    context.user_data.clear()

    # Channel gate
    already_verified = is_verified(user.id)
    if already_verified or await check_channels(context.bot, user.id):
        if not already_verified:
            set_verified(user.id)
            ref_id = complete_referral(user.id)
            if ref_id:
                try:
                    await context.bot.send_message(
                        ref_id,
                        f"🎉 Your referral joined and verified!\n"
                        f"You earned *{REFERRAL_POINTS} points*! 🏆",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
        return await show_main_menu(update, context)
    else:
        await update.message.reply_text(
            "👋 *Welcome to Brevistay Bot!*\n\n"
            "To access this bot you must join *both* our channels first:\n\n"
            "1️⃣ @earnwithsakx\n"
            "2️⃣ @blankkdealz\n\n"
            "Join them and then tap ✅ below 👇",
            parse_mode="Markdown",
            reply_markup=kb_channels()
        )
        return MAIN_MENU

# ── Show main menu ────────────────────────────────────────────────────────────

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    pts  = get_points(user.id)
    ppr  = points_per_run()
    text = (
        f"🏠 *Main Menu*\n\n"
        f"👤 {user.first_name}\n"
        f"💰 Points: *{pts}*\n"
        f"⚡ Cost per run: *{ppr} pt*\n\n"
        f"Refer friends to earn {REFERRAL_POINTS} points each! 🎁"
    )
    kb = kb_main(user.id, pts)
    msg = update.message or (update.callback_query and update.callback_query.message)
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
        except Exception:
            await context.bot.send_message(update.effective_chat.id, text, parse_mode="Markdown", reply_markup=kb)
    else:
        await msg.reply_text(text, parse_mode="Markdown", reply_markup=kb)
    return MAIN_MENU

# ── Callback query router ─────────────────────────────────────────────────────

async def cb_verify_channels(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    user = update.effective_user
    if await check_channels(context.bot, user.id):
        set_verified(user.id)
        ref_id = complete_referral(user.id)
        if ref_id:
            try:
                await context.bot.send_message(
                    ref_id,
                    f"🎉 Your referral joined and verified!\n"
                    f"You earned *{REFERRAL_POINTS} points*! 🏆",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
        await q.edit_message_text(
            "✅ *Channels verified!* Welcome aboard! 🎉",
            parse_mode="Markdown"
        )
        return await show_main_menu(update, context)
    else:
        await q.answer("❌ You haven't joined both channels yet!", show_alert=True)
        return MAIN_MENU


async def cb_back_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    context.user_data.pop("admin_target_id", None)
    return await show_main_menu(update, context)


async def cb_my_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    user = update.effective_user
    pts  = get_points(user.id)
    refs = count_referrals(user.id)
    ppr  = points_per_run()
    await q.edit_message_text(
        f"📊 *Your Stats*\n\n"
        f"👤 Name: {user.first_name}\n"
        f"🆔 ID: `{user.id}`\n"
        f"💰 Points: *{pts}*\n"
        f"🔗 Successful Referrals: *{refs}*\n"
        f"⚡ Points per run: *{ppr}*\n\n"
        f"Each referral earns you *{REFERRAL_POINTS} points* when they join! 🎁",
        parse_mode="Markdown",
        reply_markup=kb_back_menu(user.id, pts)
    )
    return MAIN_MENU


async def cb_referral_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    user = update.effective_user
    bot_info = await context.bot.get_me()
    link = f"https://t.me/{bot_info.username}?start=ref_{user.id}"
    pts  = get_points(user.id)
    await q.edit_message_text(
        f"🔗 *Your Referral Link*\n\n"
        f"`{link}`\n\n"
        f"Share this link with friends!\n"
        f"You earn *{REFERRAL_POINTS} points* for each friend who:\n"
        f"  1️⃣ Clicks your link\n"
        f"  2️⃣ Joins both channels\n\n"
        f"💰 Your current points: *{pts}*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 Share Link", switch_inline_query=link)],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="back_menu")],
        ])
    )
    return MAIN_MENU


async def cb_run_brevistay(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    user = update.effective_user
    pts  = get_points(user.id)
    ppr  = points_per_run()
    if pts < ppr:
        await q.edit_message_text(
            f"❌ *Not enough points!*\n\n"
            f"💰 You have: *{pts} pt*\n"
            f"⚡ Required: *{ppr} pt*\n\n"
            f"Refer friends to earn more points! 🎁",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔗 Get Referral Link", callback_data="referral_link")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="back_menu")],
            ])
        )
        return MAIN_MENU

    await q.edit_message_text(
        f"📱 *Brevistay — Enter Mobile Number*\n\n"
        f"Send your *10-digit Indian mobile number* (without +91):\n\n"
        f"💰 This will cost *{ppr} point(s)*.",
        parse_mode="Markdown",
        reply_markup=kb_cancel_flow()
    )
    return MOBILE


async def cb_cancel_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    # Clear brevistay state
    for k in ["mobile","is_registered","first_name","last_name","auto_email","email","awaiting_custom_email"]:
        context.user_data.pop(k, None)
    return await show_main_menu(update, context)

# ── Brevistay flow ────────────────────────────────────────────────────────────

async def handle_mobile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    mobile = update.message.text.strip()
    if not mobile.isdigit() or len(mobile) != 10:
        await update.message.reply_text(
            "❌ Invalid number. Send exactly *10 digits* (no +91):",
            parse_mode="Markdown", reply_markup=kb_cancel_flow()
        )
        return MOBILE

    await update.message.reply_text("📡 Sending OTP…")
    client = client_of(context)
    try:
        resp = client.send_otp(mobile)
    except Exception as e:
        await update.message.reply_text(
            f"⚠️ Network error: {e}\n\nTry again:",
            reply_markup=kb_cancel_flow()
        )
        return MOBILE

    if resp.get("is_otp_sent") != "1":
        await update.message.reply_text(
            f"❌ Could not send OTP: _{resp.get('msg','Unknown error')}_\n\nTry a different number:",
            parse_mode="Markdown", reply_markup=kb_cancel_flow()
        )
        return MOBILE

    context.user_data["mobile"] = mobile
    is_registered = resp.get("is_user_registered") == "1"
    context.user_data["is_registered"] = is_registered

    if is_registered:
        await update.message.reply_text(
            "✅ OTP sent!\n\nℹ️ *Existing user detected.*\n\n🔐 Enter the OTP received on your mobile:",
            parse_mode="Markdown", reply_markup=kb_cancel_flow()
        )
        return OTP_EXISTING
    else:
        first, last = BrevistayClient.random_name()
        context.user_data.update(first_name=first, last_name=last)
        await update.message.reply_text(
            f"✅ OTP sent!\n\n🆕 *New user detected.*\n\n"
            f"📝 Auto-generated profile:\n"
            f"   👤 *{first} {last}*\n\n"
            f"📧 Apna email address enter karo:",
            parse_mode="Markdown",
            reply_markup=kb_cancel_flow()
        )
        return EMAIL


async def cb_use_auto_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    context.user_data["email"] = context.user_data["auto_email"]
    await q.edit_message_text(
        f"📧 Using: `{context.user_data['email']}`\n\n🔐 Enter the OTP received on your mobile:",
        parse_mode="Markdown", reply_markup=kb_cancel_flow()
    )
    return OTP_NEW


async def cb_enter_own_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    context.user_data["awaiting_custom_email"] = True
    await q.edit_message_text(
        "📧 Send your email address:",
        reply_markup=kb_cancel_flow()
    )
    return EMAIL


async def handle_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if "@" in text and "." in text:
        context.user_data["email"] = text
        context.user_data.pop("awaiting_custom_email", None)
        await update.message.reply_text(
            f"👍 Email: `{text}`\n\n🔐 Enter the OTP received on your mobile:",
            parse_mode="Markdown", reply_markup=kb_cancel_flow()
        )
        return OTP_NEW
    await update.message.reply_text("❌ Invalid email. Try again:", reply_markup=kb_cancel_flow())
    return EMAIL


async def handle_otp_existing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    otp = update.message.text.strip()
    if not otp.isdigit():
        await update.message.reply_text("❌ OTP must be digits only:", reply_markup=kb_cancel_flow())
        return OTP_EXISTING

    await update.message.reply_text("🔄 Verifying OTP…")
    client = client_of(context)
    ref_code = effective_brevi_ref(update.effective_user.id)
    try:
        resp = client.login(context.user_data["mobile"], otp, ref_code=ref_code)
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: {e}", reply_markup=kb_cancel_flow())
        return OTP_EXISTING

    if resp.get("status") == "SUCCESS":
        deduct_points(update.effective_user.id, points_per_run())
        await update.message.reply_text(
            "✅ *Login Successful!*\n\n"
            f"👤 {client.user_name} {client.user_last_name}\n"
            f"📧 {client.user_email}\n"
            f"🎁 Referral Code: `{resp.get('user_referral_code','N/A')}`\n"
            f"💰 Points left: *{get_points(update.effective_user.id)}*",
            parse_mode="Markdown"
        )
        await _extra(update, client)
        return await _done(update, context)
    else:
        await update.message.reply_text(
            f"❌ Login failed: _{resp.get('msg','Unknown error')}_\n\nTry again:",
            parse_mode="Markdown", reply_markup=kb_cancel_flow()
        )
        return OTP_EXISTING


async def handle_otp_new(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    otp = update.message.text.strip()
    if not otp.isdigit():
        await update.message.reply_text("❌ OTP must be digits only:", reply_markup=kb_cancel_flow())
        return OTP_NEW

    await update.message.reply_text("🔄 Registering account…")
    client = client_of(context)
    ref_code = effective_brevi_ref(update.effective_user.id)
    try:
        resp = client.register(
            email=context.user_data["email"],
            mobile=context.user_data["mobile"],
            name=context.user_data["first_name"],
            last_name=context.user_data["last_name"],
            otp=otp,
            ref_code=ref_code
        )
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: {e}", reply_markup=kb_cancel_flow())
        return OTP_NEW

    if resp.get("status") == "SUCCESS":
        deduct_points(update.effective_user.id, points_per_run())
        await update.message.reply_text(
            "✅ *Registration Successful!*\n\n"
            f"👤 {client.user_name} {client.user_last_name}\n"
            f"📧 {client.user_email}\n"
            f"🎁 Referral Code: `{resp.get('user_referral_code','N/A')}`\n"
            f"💰 Wallet: ₹{resp.get('usr_wallet_bal',0)}\n"
            f"⭐ Points left: *{get_points(update.effective_user.id)}*",
            parse_mode="Markdown"
        )
        await _extra(update, client)
        return await _done(update, context)
    else:
        await update.message.reply_text(
            f"❌ Failed: _{resp.get('msg','Unknown error')}_\n\nSend OTP again:",
            parse_mode="Markdown", reply_markup=kb_cancel_flow()
        )
        return OTP_NEW


async def _extra(update: Update, client: BrevistayClient):
    try:
        p = client.get_profile()
        if p.get("status") == "SUCCESS":
            wallet   = p.get("usr_wallet_bal", 0)
            verified = p.get("usr_is_mail_verified") == "1"
            await update.message.reply_text(
                f"📊 *Profile*\n💰 Wallet: ₹{wallet}\n📧 Email verified: {'✅' if verified else '❌'}",
                parse_mode="Markdown"
            )
    except Exception:
        pass
    try:
        client.resend_email_verify()
    except Exception:
        pass


async def _done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    for k in ["mobile","is_registered","first_name","last_name","auto_email","email","awaiting_custom_email","client"]:
        context.user_data.pop(k, None)
    await update.message.reply_text(
        "*Script by BLANK x SAKX*",
        parse_mode="Markdown"
    )
    return await show_main_menu(update, context)

# ── Brevistay Refer Code (user) ───────────────────────────────────────────────

async def cb_set_ref_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    user_id  = update.effective_user.id
    current  = get_user_brevi_ref(user_id)
    fallback = get_global_brevi_ref()
    await q.edit_message_text(
        f"🎁 *Your Brevistay Referral Code*\n\n"
        f"Current: *{current if current else f'(global default: {fallback})'}*\n\n"
        f"This code is applied when the bot registers/logs in on Brevistay on your behalf.\n\n"
        f"Send your new Brevistay referral code, or tap *Clear* to use the global default:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑 Clear (use global default)", callback_data="clear_ref_code")],
            [InlineKeyboardButton("🏠 Back to Menu",              callback_data="back_menu")],
        ])
    )
    return SET_REF_CODE


async def cb_clear_ref_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    set_user_brevi_ref(update.effective_user.id, "")
    fallback = get_global_brevi_ref()
    await q.edit_message_text(
        f"✅ Cleared! You'll now use the global default code: *{fallback}*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="back_menu")]])
    )
    return MAIN_MENU


async def handle_set_ref_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    code = update.message.text.strip().upper()
    if not code or len(code) > 20:
        await update.message.reply_text(
            "❌ Invalid code. Must be 1–20 characters. Try again:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Cancel", callback_data="back_menu")]])
        )
        return SET_REF_CODE
    set_user_brevi_ref(update.effective_user.id, code)
    await update.message.reply_text(
        f"✅ Your Brevistay referral code set to: *{code}*\n\n"
        f"This will be used in all your future Brevistay runs.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="back_menu")]])
    )
    return MAIN_MENU


# ── Admin panel ───────────────────────────────────────────────────────────────

def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in ADMIN_IDS:
            if update.callback_query:
                await update.callback_query.answer("⛔ Admins only!", show_alert=True)
            return MAIN_MENU
        return await func(update, context)
    return wrapper


@admin_only
async def cb_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    ppr = points_per_run()
    await q.edit_message_text(
        f"🔧 *Admin Panel*\n\n"
        f"⚡ Points per run: *{ppr}*\n"
        f"🔑 Global refer code: *{get_global_brevi_ref()}*\n"
        f"📋 Use buttons below to manage:",
        parse_mode="Markdown",
        reply_markup=kb_admin()
    )
    return MAIN_MENU


@admin_only
async def cb_adm_give(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    await q.edit_message_text(
        "👤 *Give Points*\n\nSend the *Telegram user ID* of the user to give points to:",
        parse_mode="Markdown",
        reply_markup=kb_back_admin()
    )
    return ADMIN_GIVE_USER


async def handle_admin_give_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_user.id not in ADMIN_IDS:
        return MAIN_MENU
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("❌ Send a valid numeric Telegram user ID:")
        return ADMIN_GIVE_USER
    target = int(text)
    u = get_user(target)
    if not u:
        await update.message.reply_text(
            f"❌ User `{target}` not found in DB. They need to /start the bot first.",
            parse_mode="Markdown"
        )
        return ADMIN_GIVE_USER
    context.user_data["admin_target_id"] = target
    current = get_points(target)
    name = u[2] or u[1] or str(target)
    await update.message.reply_text(
        f"👤 *{name}* (`{target}`)\n"
        f"💰 Current points: *{current}*\n\n"
        f"Send the number of points to add (use - to subtract, e.g. `-5`):",
        parse_mode="Markdown",
        reply_markup=kb_back_admin()
    )
    return ADMIN_GIVE_AMOUNT


async def handle_admin_give_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_user.id not in ADMIN_IDS:
        return MAIN_MENU
    text = update.message.text.strip().replace("+", "")
    try:
        amount = int(text)
    except ValueError:
        await update.message.reply_text("❌ Send a valid number (e.g. 5 or -3):")
        return ADMIN_GIVE_AMOUNT

    target = context.user_data.get("admin_target_id")
    if not target:
        await update.message.reply_text("❌ Session expired. Use Admin Panel again.")
        return MAIN_MENU

    if amount >= 0:
        add_points(target, amount)
    else:
        deduct_points(target, abs(amount))

    new_pts = get_points(target)
    context.user_data.pop("admin_target_id", None)

    # Notify target user
    try:
        action = f"+{amount}" if amount >= 0 else str(amount)
        await context.bot.send_message(
            target,
            f"💰 *Points Updated!*\n\n"
            f"Admin adjusted your points by *{action}*.\n"
            f"New balance: *{new_pts} points*",
            parse_mode="Markdown"
        )
    except Exception:
        pass

    await update.message.reply_text(
        f"✅ Done! User `{target}` now has *{new_pts} points*.",
        parse_mode="Markdown",
        reply_markup=kb_admin()
    )
    return MAIN_MENU


@admin_only
async def cb_adm_set_ppr(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    ppr = points_per_run()
    await q.edit_message_text(
        f"⚙️ *Change Points Per Run*\n\n"
        f"Current value: *{ppr}*\n\n"
        f"Send the new number of points required per Brevistay run:",
        parse_mode="Markdown",
        reply_markup=kb_back_admin()
    )
    return ADMIN_SET_POINTS


async def handle_admin_set_points(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_user.id not in ADMIN_IDS:
        return MAIN_MENU
    text = update.message.text.strip()
    if not text.isdigit() or int(text) < 1:
        await update.message.reply_text("❌ Enter a positive integer (e.g. 2):")
        return ADMIN_SET_POINTS
    set_setting("points_per_run", text)
    await update.message.reply_text(
        f"✅ Points per run updated to *{text}*.",
        parse_mode="Markdown",
        reply_markup=kb_admin()
    )
    return MAIN_MENU


@admin_only
async def cb_adm_set_refcode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    current = get_global_brevi_ref()
    await q.edit_message_text(
        f"🔑 *Set Global Default Brevistay Refer Code*\n\n"
        f"Current: *{current}*\n\n"
        f"This code is used for all users who haven't set their own personal code.\n\n"
        f"Send the new global referral code:",
        parse_mode="Markdown",
        reply_markup=kb_back_admin()
    )
    return ADMIN_SET_REFCODE


async def handle_admin_set_refcode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_user.id not in ADMIN_IDS:
        return MAIN_MENU
    code = update.message.text.strip().upper()
    if not code or len(code) > 20:
        await update.message.reply_text("❌ Invalid code. Must be 1–20 characters. Try again:")
        return ADMIN_SET_REFCODE
    set_setting("brevi_ref_code", code)
    await update.message.reply_text(
        f"✅ Global Brevistay referral code updated to: *{code}*\n\n"
        f"All users without a personal code will now use this.",
        parse_mode="Markdown",
        reply_markup=kb_admin()
    )
    return MAIN_MENU


@admin_only
async def cb_adm_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    rows = get_all_users(20)
    if not rows:
        text = "📋 No users yet."
    else:
        lines = ["📋 *Top Users (by points)*\n"]
        for i, (uid, uname, fname, pts, verified) in enumerate(rows, 1):
            vmark = "✅" if verified else "❌"
            name  = fname or uname or str(uid)
            lines.append(f"{i}. {vmark} *{name}* — `{uid}` — {pts} pts")
        text = "\n".join(lines)
    await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb_back_admin())
    return MAIN_MENU

# ── /cancel fallback ──────────────────────────────────────────────────────────

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("❌ Cancelled. Send /start to begin.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    # Prefer the TELEGRAM_BOT_TOKEN environment variable (set this in Railway's
    # service variables for production). Falls back to BOT_TOKEN above, which
    # can be set locally for development but should never contain a real
    # secret in version control.
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or BOT_TOKEN
    if not token:
        raise RuntimeError(
            "No bot token found. Set the TELEGRAM_BOT_TOKEN environment "
            "variable (e.g. in Railway's service variables) or, for local "
            "development, set BOT_TOKEN at the top of this file."
        )


    init_db()

    app = Application.builder().token(token).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(cb_verify_channels,   pattern="^verify_channels$"),
                CallbackQueryHandler(cb_back_menu,         pattern="^back_menu$"),
                CallbackQueryHandler(cb_my_stats,          pattern="^my_stats$"),
                CallbackQueryHandler(cb_referral_link,     pattern="^referral_link$"),
                CallbackQueryHandler(cb_run_brevistay,     pattern="^run_brevistay$"),
                CallbackQueryHandler(cb_cancel_flow,       pattern="^cancel_flow$"),
                CallbackQueryHandler(cb_admin_panel,       pattern="^admin_panel$"),
                CallbackQueryHandler(cb_adm_give,          pattern="^adm_give$"),
                CallbackQueryHandler(cb_adm_set_ppr,       pattern="^adm_set_ppr$"),
                CallbackQueryHandler(cb_adm_set_refcode,   pattern="^adm_set_refcode$"),
                CallbackQueryHandler(cb_adm_users,         pattern="^adm_users$"),
                CallbackQueryHandler(cb_set_ref_code,      pattern="^set_ref_code$"),
                CallbackQueryHandler(cb_clear_ref_code,    pattern="^clear_ref_code$"),
            ],
            MOBILE: [
                CallbackQueryHandler(cb_cancel_flow, pattern="^cancel_flow$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_mobile),
            ],
            OTP_EXISTING: [
                CallbackQueryHandler(cb_cancel_flow, pattern="^cancel_flow$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_otp_existing),
            ],
            EMAIL: [

                CallbackQueryHandler(cb_cancel_flow,     pattern="^cancel_flow$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_email),
            ],
            OTP_NEW: [
                CallbackQueryHandler(cb_cancel_flow, pattern="^cancel_flow$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_otp_new),
            ],
            ADMIN_GIVE_USER: [
                CallbackQueryHandler(cb_admin_panel, pattern="^admin_panel$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_give_user),
            ],
            ADMIN_GIVE_AMOUNT: [
                CallbackQueryHandler(cb_admin_panel, pattern="^admin_panel$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_give_amount),
            ],
            ADMIN_SET_POINTS: [
                CallbackQueryHandler(cb_admin_panel, pattern="^admin_panel$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_set_points),
            ],
            SET_REF_CODE: [
                CallbackQueryHandler(cb_clear_ref_code, pattern="^clear_ref_code$"),
                CallbackQueryHandler(cb_back_menu,      pattern="^back_menu$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_set_ref_code),
            ],
            ADMIN_SET_REFCODE: [
                CallbackQueryHandler(cb_admin_panel, pattern="^admin_panel$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_set_refcode),
            ],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
    )

    app.add_handler(conv)
    logger.info("Brevistay Bot (full featured) starting…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
