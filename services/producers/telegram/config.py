import os
from dotenv import load_dotenv

load_dotenv()

SESSION_STRING_TELEGRAM = os.getenv("SESSION_STRING_TELEGRAM")
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
PHONE = os.getenv("PHONE")



