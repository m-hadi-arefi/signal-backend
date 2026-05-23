from config import API_ID, API_HASH, PHONE
from telethon import TelegramClient
from services.producers.telegram.config import SESSION_STRING_TELEGRAM

from telethon.sessions import StringSession

client = TelegramClient(
    StringSession(SESSION_STRING_TELEGRAM),
    API_ID,
    API_HASH
)