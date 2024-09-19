import os
import logging

import cyrtranslit
import pytubefix
import pytubefix.extract
from pytubefix.cli import on_progress
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters


# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO)
logger = logging.getLogger(__name__)


# Define a function to handle /start command
async def start(update, context):
    """Send a message when the command /start is issued."""
    await update.message.reply_text(
        'Hi! Send me a YouTube video link and I will send you the audio file.')


# Define a function to handle incoming messages
async def message_handler(update, context):
    """Download audio from YouTube video and send it back as an audio file."""
    message_text = update.message.text.strip()
    logger.info(f"Received message: {message_text}")
    
    # Check if message contains a valid YouTube link
    try:
        pytubefix.extract.video_id(message_text)
    except Exception:
        await update.message.reply_text(
            "Please send me a valid YouTube video link.",
            reply_to_message_id=update.message.message_id,
        )
        return
    
    # Download audio from YouTube video
    await update.message.reply_text(
        "Trying to download the audio file.",
        reply_to_message_id=update.message.message_id,
    )
    logger.info("Trying to download the audio file.")
    try:
        yt = pytubefix.YouTube(message_text, on_progress_callback=on_progress)
        audio_stream = yt.streams.get_audio_only()
        audio_filename = f"{audio_stream.default_filename[:-4]}.mp3"
        # transliterate name if cyrillic
        audio_filename = cyrtranslit.to_latin(audio_filename, 'ru')
        audio_stream.download(output_path=".", filename=audio_filename)
    except Exception as e:
        await update.message.reply_text(
            "An error occurred while downloading the audio file.",
            reply_to_message_id=update.message.message_id,
        )
        logger.exception(e)
        return
    
    # Send audio file back to user
    logger.info("Download completed, Sending the audio file.")
    await update.message.reply_text(
        "Download completed, Sending the audio file.",
        reply_to_message_id=update.message.message_id,
    )
    with open(audio_filename, 'rb') as audio_file:
        await update.effective_message.reply_audio(
            audio_file,
            read_timeout=1000,
            write_timeout=1000,
        )

    # Delete audio file from server
    os.remove(audio_filename)


# Define a main function to start the bot
def main():
    # Get Telegram bot token from environment variable
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    
    # Create the Application and pass it your bot's token.
    application = (
        Application.builder()
        .token(token)
        # .read_timeout(30)
        # .write_timeout(600)
        .build()
    )
    
    # Commands
    application.add_handler(CommandHandler('start', start))
    
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
