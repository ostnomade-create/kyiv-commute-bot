import os
from dataclasses import dataclass
from dotenv import load_dotenv

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(ENV_PATH)

# Coordinates:
# Дім: вул. Юлії Здановської, 36 (Голосіївський р-н)
HOME_COORDS = "50.3893668,30.4746391"
HOME_TITLE = "вул. Юлії Здановської, 36 (Дім)"

# Робота: вул. Олександра Кониського, 15 (Шевченківський р-н)
WORK_COORDS = "50.4495142,30.4935782"
WORK_TITLE = "вул. Олександра Кониського, 15 (Робота)"

# Telegram Credentials
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TIMEZONE = os.getenv("TIMEZONE", "Europe/Kyiv")
