import os
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Load environment variables
load_dotenv()

# Get token
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("No BOT_TOKEN found! Make sure it's set in environment variables.")

# Dictionary to store reminders
# Format: {chat_id: [{'time': datetime, 'text': str, 'job_name': str}]}
user_reminders = {}

# Helper function to parse time from text
def parse_time(text):
    """Parse time from various formats like '10:00', '10am', '2pm', '15:30'"""
    text = text.lower().strip()
    
    # Try HH:MM format (24-hour)
    match = re.match(r'^(\d{1,2}):(\d{2})$', text)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            now = datetime.now()
            reminder_time = datetime(now.year, now.month, now.day, hour, minute)
            if reminder_time < now:
                reminder_time += timedelta(days=1)
            return reminder_time
    
    # Try X:XX AM/PM format
    match = re.match(r'^(\d{1,2}):(\d{2})\s*(am|pm)$', text)
    if match:
        hour, minute, period = int(match.group(1)), int(match.group(2)), match.group(3)
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
    
    # Try X AM/PM format
    match = re.match(r'^(\d{1,2})\s*(am|pm)$', text)
    if match:
        hour, period = int(match.group(1)), match.group(2)
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

# Command: /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_message = (
        "🤖 *Welcome to Reminder Bot!*\n\n"
        "I can help you remember important tasks.\n\n"
        "*Available Commands:*\n"
        "/remind <time> <description> - Set a reminder\n"
        "  Examples:\n"
        "  /remind 10:00 Meeting with team\n"
        "  /remind 2pm Call mom\n"
        "  /remind 15:30 Submit report\n\n"
        "/myreminders - Show all your reminders\n"
        "/cancel <number> - Cancel a reminder\n"
        "/help - Show this message"
    )
    await update.message.reply_text(welcome_message, parse_mode='Markdown')

# Command: /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📚 *How to use this bot:*\n\n"
        "1️⃣ *Set a reminder:*\n"
        "   `/remind 10:00 Buy groceries`\n"
        "   `/remind 2pm Call John`\n"
        "   `/remind 15:30 Submit report`\n\n"
        "2️⃣ *View reminders:* `/myreminders`\n\n"
        "3️⃣ *Cancel a reminder:* `/cancel 1`\n\n"
        "4️⃣ *Start over:* `/start`"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

# Command: /remind
async def remind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    
    # Check if user provided time and description
    parts = user_text.split(maxsplit=2)
    if len(parts) < 3:
        await update.message.reply_text(
            "⚠️ *Please specify time and description.*\n\n"
            "Format: `/remind <time> <description>`\n"
            "Examples:\n"
            "- `/remind 10:00 Meeting with team`\n"
            "- `/remind 2pm Call mom`",
            parse_mode='Markdown'
        )
        return
    
    time_str = parts[1]
    description = parts[2]
    
    # Parse time
    reminder_time = parse_time(time_str)
    
    if not reminder_time:
        await update.message.reply_text(
            "⚠️ *Invalid time format.*\n\n"
            "Try formats like:\n"
            "- `10:00` (24-hour)\n"
            "- `2pm` (12-hour)\n"
            "- `2:30pm` (12-hour with minutes)",
            parse_mode='Markdown'
        )
        return
    
    # Calculate time difference
    now = datetime.now()
    time_diff = (reminder_time - now).total_seconds()
    
    if time_diff <= 0:
        await update.message.reply_text("⚠️ Time must be in the future!")
        return
    
    # Create job name
    job_name = f"reminder_{chat_id}_{len(user_reminders.get(chat_id, []))}"
    
    # Add job to job queue
    job = context.job_queue.run_once(
        send_reminder,
        when=time_diff,
        chat_id=chat_id,
        name=job_name,
        data={'text': description, 'time': reminder_time}
    )
    
    # Store reminder in memory
    if chat_id not in user_reminders:
        user_reminders[chat_id] = []
    user_reminders[chat_id].append({
        'time': reminder_time,
        'text': description,
        'job_name': job_name,
        'job': job
    })
    
    # Format time for display
    time_formatted = reminder_time.strftime('%I:%M %p').lstrip('0')
    
    await update.message.reply_text(
        f"✅ *Reminder set!*\n\n"
        f"📝 *Task:* {description}\n"
        f"⏰ *Time:* {time_formatted}\n\n"
        f"I'll remind you at the scheduled time.",
        parse_mode='Markdown'
    )

# Function to send reminder
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
    
    # Remove from memory after reminder is sent
    if chat_id in user_reminders:
        user_reminders[chat_id] = [r for r in user_reminders[chat_id] if r['job_name'] != job.name]

# Command: /myreminders
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

# Command: /cancel
async def cancel_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    
    # Parse the number
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
    
    # Remove the job
    reminder = user_reminders[chat_id][idx]
    job = reminder.get('job')
    if job:
        job.schedule_removal()
    
    # Remove from memory
    removed = user_reminders[chat_id].pop(idx)
    
    await update.message.reply_text(
        f"✅ *Reminder canceled:*\n"
        f"📝 {removed['text']}",
        parse_mode='Markdown'
    )

# Handle unknown commands
async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❌ Unknown command.\n\n"
        "Use `/start` to see all available commands.",
        parse_mode='Markdown'
    )

# Handle unknown text
async def unknown_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❌ I don't understand that.\n\n"
        "Use `/start` to see all available commands.",
        parse_mode='Markdown'
    )

# Main function
def main():
    print("🤖 Starting Reminder Bot...")
    
    # Create application
    app = Application.builder().token(BOT_TOKEN).build()
    
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
    main()