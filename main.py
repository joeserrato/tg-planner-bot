import os
import re
import threading
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from flask import Flask

# Flask server for Render
flask_app = Flask(__name__)

@flask_app.route('/')
def health():
    return "Bot is running!", 200

# Load environment variables
load_dotenv()

# Get token
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("No BOT_TOKEN found! Make sure it's set in environment variables.")

# Dictionary to store reminders
user_reminders = {}

def parse_time(text):
    """Parse time from various formats"""
    text = text.lower().strip()
    
    # Format: 10:30, 10:30am, 10:30 pm
    match = re.match(r'^(\d{1,2}):(\d{2})\s*(am|pm)?$', text)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2))
        period = match.group(3)
        
        if period == 'pm' and hour != 12:
            hour += 12
        elif period == 'am' and hour == 12:
            hour = 0
        
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            now = datetime.now()
            reminder_time = datetime(now.year, now.month, now.day, hour, minute)
            if reminder_time < now:
                reminder_time += timedelta(days=1)
            return reminder_time
    
    # Format: 2pm, 10am
    match = re.match(r'^(\d{1,2})\s*(am|pm)$', text)
    if match:
        hour = int(match.group(1))
        period = match.group(2)
        
        if period == 'pm' and hour != 12:
            hour += 12
        elif period == 'am' and hour == 12:
            hour = 0
        
        if 0 <= hour <= 23:
            now = datetime.now()
            reminder_time = datetime(now.year, now.month, now.day, hour, 0)
            if reminder_time < now:
                reminder_time += timedelta(days=1)
            return reminder_time
    
    return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_message = (
        "🤖 *Welcome to Reminder Bot!*\n\n"
        "I can help you remember important tasks.\n\n"
        "*Available Commands:*\n"
        "/remind - Show your full schedule\n"
        "/remind <time> <description> - Set a new reminder\n"
        "  Examples:\n"
        "  /remind 10:30 Meeting with team\n"
        "  /remind 2pm Call mom\n"
        "  /remind 15:30 Submit report\n\n"
        "/myreminders - Show all your reminders\n"
        "/cancel <number> - Cancel a reminder\n"
        "/help - Show this message"
    )
    await update.message.reply_text(welcome_message, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📚 *How to use this bot:*\n\n"
        "1️⃣ *View your schedule:* `/remind`\n"
        "2️⃣ *Set a reminder:* `/remind 10:30 Buy groceries`\n"
        "3️⃣ *View reminders:* `/myreminders`\n"
        "4️⃣ *Cancel a reminder:* `/cancel 1`\n\n"
        "⏰ *Time Formats:*\n"
        "- `10:30` (24-hour)\n"
        "- `2pm` (12-hour)\n"
        "- `2:30pm` (12-hour with minutes)\n\n"
        "📝 *Example:* `/remind 2pm Call John`"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def remind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    
    # Check if user just sent /remind without any arguments
    parts = user_text.split(maxsplit=1)
    
    # If only /remind was sent (no arguments), show all reminders
    if len(parts) == 1:
        if chat_id not in user_reminders or not user_reminders[chat_id]:
            await update.message.reply_text(
                "📭 *No reminders scheduled.*\n\n"
                "Set one using: `/remind 10:30 Task description`",
                parse_mode='Markdown'
            )
            return
        
        reminders = user_reminders[chat_id]
        reminder_list = []
        
        for idx, reminder in enumerate(reminders, 1):
            time_str = reminder['time'].strftime('%I:%M %p').lstrip('0')
            reminder_list.append(f"{idx}. {reminder['text']} - ⏰ {time_str}")
        
        response = "📋 *Your Full Schedule:*\n\n" + "\n".join(reminder_list)
        response += "\n\nTo cancel a reminder, use: `/cancel <number>`"
        
        await update.message.reply_text(response, parse_mode='Markdown')
        return
    
    # If user provided time and description
    parts = user_text.split(maxsplit=2)
    
    if len(parts) < 3:
        await update.message.reply_text(
            "⚠️ *Please specify time and description.*\n\n"
            "Format: `/remind <time> <description>`\n"
            "Examples:\n"
            "- `/remind 10:30 Meeting with team`\n"
            "- `/remind 2pm Call mom`\n\n"
            "Or just type `/remind` to see your schedule.",
            parse_mode='Markdown'
        )
        return
    
    time_str = parts[1]
    description = parts[2]
    
    reminder_time = parse_time(time_str)
    
    if not reminder_time:
        await update.message.reply_text(
            f"⚠️ *Invalid time format.*\n\n"
            f"I couldn't understand '{time_str}'.\n\n"
            "Try formats like:\n"
            "- `10:30` (24-hour)\n"
            "- `2pm` (12-hour)\n"
            "- `2:30pm` (12-hour with minutes)",
            parse_mode='Markdown'
        )
        return
    
    now = datetime.now()
    time_diff = (reminder_time - now).total_seconds()
    
    if time_diff <= 0:
        await update.message.reply_text("⚠️ Time must be in the future!")
        return
    
    # Check if job_queue is available
    if context.job_queue is None:
        await update.message.reply_text(
            "⚠️ *Error:* JobQueue is not available.\n\n"
            "Please install: `pip install python-telegram-bot[job-queue]`",
            parse_mode='Markdown'
        )
        return
    
    job_name = f"reminder_{chat_id}_{len(user_reminders.get(chat_id, []))}"
    
    job = context.job_queue.run_once(
        send_reminder,
        when=time_diff,
        chat_id=chat_id,
        name=job_name,
        data={'text': description, 'time': reminder_time}
    )
    
    if chat_id not in user_reminders:
        user_reminders[chat_id] = []
    user_reminders[chat_id].append({
        'time': reminder_time,
        'text': description,
        'job_name': job_name,
        'job': job
    })
    
    time_formatted = reminder_time.strftime('%I:%M %p').lstrip('0')
    
    # Show the new reminder AND the full schedule
    reminders = user_reminders[chat_id]
    reminder_list = []
    
    for idx, reminder in enumerate(reminders, 1):
        time_str = reminder['time'].strftime('%I:%M %p').lstrip('0')
        reminder_list.append(f"{idx}. {reminder['text']} - ⏰ {time_str}")
    
    response = (
        f"✅ *Reminder set!*\n\n"
        f"📝 *Task:* {description}\n"
        f"⏰ *Time:* {time_formatted}\n\n"
        f"📋 *Your Full Schedule:*\n\n"
        + "\n".join(reminder_list)
    )
    
    await update.message.reply_text(response, parse_mode='Markdown')

async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.chat_id
    data = job.data
    
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"⏰ *REMINDER!*\n\n"
             f"📝 *Task:* {data['text']}\n"
             f"⏰ *Scheduled Time:* {data['time'].strftime('%I:%M %p').lstrip('0')}\n\n"
             f"Don't forget to complete this!",
        parse_mode='Markdown'
    )
    
    if chat_id in user_reminders:
        user_reminders[chat_id] = [r for r in user_reminders[chat_id] if r['job_name'] != job.name]

async def myreminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if chat_id not in user_reminders or not user_reminders[chat_id]:
        await update.message.reply_text("📭 *No reminders scheduled.*\n\nUse `/remind` to set one!", parse_mode='Markdown')
        return
    
    reminders = user_reminders[chat_id]
    reminder_list = []
    
    for idx, reminder in enumerate(reminders, 1):
        time_str = reminder['time'].strftime('%I:%M %p').lstrip('0')
        reminder_list.append(f"{idx}. {reminder['text']} - ⏰ {time_str}")
    
    response = "📋 *Your Reminders:*\n\n" + "\n".join(reminder_list)
    response += "\n\nTo cancel a reminder, use: `/cancel <number>`"
    
    await update.message.reply_text(response, parse_mode='Markdown')

async def cancel_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    
    parts = user_text.split()
    if len(parts) != 2:
        await update.message.reply_text(
            "⚠️ *Please specify which reminder to cancel.*\n\n"
            "Format: `/cancel <number>`\n"
            "Example: `/cancel 1`\n\n"
            "Use `/myreminders` to see the numbers.",
            parse_mode='Markdown'
        )
        return
    
    try:
        idx = int(parts[1]) - 1
    except ValueError:
        await update.message.reply_text("⚠️ Please enter a valid number.")
        return
    
    if chat_id not in user_reminders or idx < 0 or idx >= len(user_reminders[chat_id]):
        await update.message.reply_text("❌ Reminder not found.\n\nUse `/myreminders` to see your reminders.", parse_mode='Markdown')
        return
    
    reminder = user_reminders[chat_id][idx]
    job = reminder.get('job')
    if job:
        job.schedule_removal()
    
    removed = user_reminders[chat_id].pop(idx)
    
    await update.message.reply_text(
        f"✅ *Reminder canceled:*\n"
        f"📝 {removed['text']}",
        parse_mode='Markdown'
    )

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❌ Unknown command.\n\n"
        "Use `/start` to see all available commands.",
        parse_mode='Markdown'
    )

async def unknown_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❌ I don't understand that.\n\n"
        "Use `/start` to see all available commands.",
        parse_mode='Markdown'
    )

def main():
    print("🤖 Starting Reminder Bot...")
    
    # Build the application
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Check if job_queue is available
    if app.job_queue is None:
        print("⚠️ JobQueue is not available! Please install python-telegram-bot[job-queue]")
        return
    
    # Add command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("remind", remind))
    app.add_handler(CommandHandler("myreminders", myreminders))
    app.add_handler(CommandHandler("cancel", cancel_reminder))
    
    # Handle unknown commands and text
    app.add_handler(MessageHandler(filters.COMMAND, unknown))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_text))
    
    print("Bot is running! Waiting for messages...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    def run_flask():
        flask_app.run(host='0.0.0.0', port=10000)
    
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    main()