import asyncio
import ctypes
import html
import http.server
import logging
import os
import re
import socketserver
import sys
import threading
import time
from datetime import datetime
from typing import Optional
import pytz
import requests

# Гарантуємо UTF-8 виведення в консолі
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from commute import run_commute_check
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TIMEZONE
import db
from reminder_parser import parse_reminder
from brsm import format_brsm_fuel_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("assistant_bot")

KYIV = pytz.timezone(TIMEZONE)
API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

MAIN_KEYBOARD = {
    "keyboard": [
        [{"text": "🚗 Затори зараз"}, {"text": "⛽ Пальне БРСМ"}],
        [{"text": "📋 Мої нагадування"}, {"text": "🌅 На роботу"}, {"text": "🌇 Додому"}],
    ],
    "resize_keyboard": True,
}


class HealthHandler(http.server.BaseHTTPRequestHandler):
    """Обробник для хмарних сервісів (Render, Railway, Koyeb), що вимагають HTTP-порту."""
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"OK: Kyiv Commute & Reminder Bot is active and running 24/7!")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        pass  # вимикаємо зайвий лог пінгу


def run_health_server():
    """Запускає легкий HTTP health-check сервер для хмари."""
    port_str = os.getenv("PORT", "8080")
    try:
        port = int(port_str)
        # Дозволяємо повторне використання сокета
        socketserver.TCPServer.allow_reuse_address = True
        with socketserver.TCPServer(("", port), HealthHandler) as httpd:
            logger.info(f"🌐 Хмарний health-сервер активний на порту {port}")
            httpd.serve_forever()
    except Exception as e:
        logger.warning(f"Не вдалося запустити health-сервер на порту {port_str}: {e}")


def prevent_windows_sleep():
    """Запобігає засинанню Windows під час роботи бота."""
    if os.name == "nt":
        try:
            # ES_CONTINUOUS = 0x80000000, ES_SYSTEM_REQUIRED = 0x00000001
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
            logger.info("🛡 Захист від автоматичного сну Windows активовано.")
        except Exception as e:
            logger.warning(f"Не вдалося активувати захист від сну: {e}")


def send_message(
    chat_id: int,
    text: str,
    reply_markup: Optional[dict] = None,
    parse_mode: str = "HTML",
) -> bool:
    url = f"{API_BASE}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        resp = requests.post(url, json=payload, timeout=(5, 10))
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Помилка відправлення повідомлення: {e}")
        return False


def format_delta_ua(target_dt: datetime, base_dt: datetime) -> str:
    diff = target_dt - base_dt
    total_seconds = int(diff.total_seconds())
    if total_seconds <= 0:
        return "прямо зараз"

    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    parts = []
    if days > 0:
        parts.append(f"{days} дн.")
    if hours > 0:
        parts.append(f"{hours} год.")
    if minutes > 0:
        parts.append(f"{minutes} хв")
    if not parts and seconds > 0:
        parts.append(f"{seconds} сек")

    return "через " + " ".join(parts)


def handle_reminder_text(chat_id: int, text: str):
    now = datetime.now(KYIV)
    action, target_dt = parse_reminder(text, now)

    if not action or not target_dt:
        help_msg = (
            "🤔 <b>Не вдалося розпізнати дату або час.</b>\n\n"
            "Спробуйте написати, наприклад:\n"
            "• <i>Нагадай поміняти гуму в п'ятницю о 14:00</i>\n"
            "• <i>Нагадай на 15:00 зустріч</i>\n"
            "• <i>Нагадай випити ліки через 40 хв</i>\n"
            "• <i>Нагадай завтра о 10:30 подзвонити лікарю</i>\n"
            "• <i>через 20 секунд перевірити таймер</i>"
        )
        send_message(chat_id, help_msg, reply_markup=MAIN_KEYBOARD)
        return

    # Зберігаємо в базу даних
    rem_id = db.add_reminder(chat_id, action, target_dt)

    ua_weekdays = [
        "понеділок",
        "вівторок",
        "середа",
        "четвер",
        "п'ятниця",
        "субота",
        "неділя",
    ]
    w_name = ua_weekdays[target_dt.weekday()]
    dt_formatted = target_dt.strftime("%d.%m.%Y о %H:%M")
    delta_str = format_delta_ua(target_dt, now)

    confirm_msg = (
        f"✅ <b>Нагадування встановлено!</b>\n\n"
        f"📌 <b>Справа:</b> {html.escape(action)}\n"
        f"⏰ <b>Коли:</b> {dt_formatted} ({w_name})\n"
        f"⏳ <i>({delta_str})</i>\n\n"
        f"🆔 №<code>{rem_id}</code> (для скасування: /del_{rem_id})"
    )
    send_message(chat_id, confirm_msg, reply_markup=MAIN_KEYBOARD)


def handle_list_reminders(chat_id: int):
    items = db.get_active_reminders(chat_id)
    if not items:
        send_message(
            chat_id,
            "📭 <b>У вас немає активних нагадувань.</b>\n\n"
            "Щоб створити нове, просто напишіть, наприклад:\n"
            "• <i>Нагадай на 15:00</i>\n"
            "• <i>Нагадай випити ліки через 40 хв</i>\n"
            "• <i>Нагадай завтра о 10:00</i>",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    now = datetime.now(KYIV)
    lines = ["📋 <b>Ваші активні нагадування:</b>\n"]
    for row in items:
        dt = datetime.fromisoformat(row["remind_at"]).astimezone(KYIV)
        delta_str = format_delta_ua(dt, now)
        lines.append(
            f"🔹 <b>{html.escape(row['text'])}</b>\n"
            f"   ⏰ {dt.strftime('%d.%m о %H:%M')} <i>({delta_str})</i>\n"
            f"   ❌ Скасувати: /del_{row['id']}\n"
        )

    send_message(chat_id, "\n".join(lines), reply_markup=MAIN_KEYBOARD)


def handle_delete_reminder(chat_id: int, text: str):
    m = re.search(r"\d+", text)
    if not m:
        send_message(chat_id, "Вкажіть номер нагадування, наприклад: <code>/del 1</code>")
        return
    rem_id = int(m.group())
    success = db.delete_reminder(rem_id, chat_id)
    if success:
        send_message(chat_id, f"🗑 Нагадування №{rem_id} скасовано.")
    else:
        send_message(chat_id, f"⚠️ Нагадування №{rem_id} не знайдено або вже виконано.")


def handle_incoming_message(msg: dict):
    chat = msg.get("chat", {})
    chat_id = chat.get("id")
    text = msg.get("text", "").strip()

    if not chat_id or not text:
        return

    logger.info(f"Отримано повідомлення від {chat_id}: {text}")

    # Команда /start або /help
    if text.startswith("/start") or text.startswith("/help"):
        welcome = (
            "👋 <b>Привіт! Я ваш особистий київський помічник.</b>\n\n"
            "⏰ <b>Розумні нагадування людською мовою:</b>\n"
            "Просто напишіть мені будь-яку фразу, наприклад:\n"
            "• <i>Нагадай на 15:00</i>\n"
            "• <i>Нагадай поміняти гуму в п'ятницю о 14:00</i>\n"
            "• <i>Нагадай випити ліки через 40 хв</i>\n"
            "• <i>Нагадай завтра о 10:30 подзвонити лікарю</i>\n"
            "• <i>через 15 хвилин вимкнути духовку</i>\n\n"
            "🚗 <b>Затори та навігація (на вимогу):</b>\n"
            "• Натисніть кнопку <b>«🚗 Затори зараз»</b> у будь-який момент\n"
            "• Або швидкі кнопки: <b>«🌅 На роботу»</b> / <b>«🌇 Додому»</b>\n\n"
            "⛽ <b>БРСМ-Нафта:</b>\n"
            "• Натисніть <b>«⛽ Пальне БРСМ»</b> для перегляду актуальних цін та наявності на АЗК біля маршруту\n\n"
            "📋 <b>Керування нагадуваннями:</b>\n"
            "• <b>«📋 Мої нагадування»</b> або <code>/list</code>\n"
            "• <code>/del ID</code> — скасувати нагадування"
        )
        send_message(chat_id, welcome, reply_markup=MAIN_KEYBOARD)
        return

    # Перевірка цін та АЗК БРСМ
    if text in ["⛽ Пальне БРСМ", "/brsm", "/fuel", "брсм", "пальне", "бензин", "газ"]:
        report_text, buttons = format_brsm_fuel_report()
        reply_markup = {"inline_keyboard": buttons} if buttons else None
        send_message(chat_id, report_text, reply_markup=reply_markup)
        return

    # Кнопки заторів
    if text in ["🚗 Затори зараз", "/now", "затори", "пробки"]:
        now = datetime.now(KYIV)
        direction = "morning" if now.hour < 13 else "evening"
        send_message(chat_id, "🔍 Отримую актуальні дані про затори у Waze...")
        threading.Thread(
            target=lambda: asyncio.run(run_commute_check(direction=direction)),
            daemon=True,
        ).start()
        return

    if text in ["🌅 На роботу", "/morning"]:
        send_message(chat_id, "🔍 Перевіряю маршрут: Дім ➡️ Робота...")
        threading.Thread(
            target=lambda: asyncio.run(run_commute_check(direction="morning")),
            daemon=True,
        ).start()
        return

    if text in ["🌇 Додому", "/evening"]:
        send_message(chat_id, "🔍 Перевіряю маршрут: Робота ➡️ Дім...")
        threading.Thread(
            target=lambda: asyncio.run(run_commute_check(direction="evening")),
            daemon=True,
        ).start()
        return

    # Перегляд нагадувань
    if text in ["📋 Мої нагадування", "/list", "/reminders", "список"]:
        handle_list_reminders(chat_id)
        return

    # Скасування нагадування (/del, /delete, /del_123)
    if text.startswith("/del"):
        handle_delete_reminder(chat_id, text)
        return

    # Будь-який інший текст обробляємо як нагадування
    handle_reminder_text(chat_id, text)


def reminder_scheduler_loop():
    """
    Окремий незалежний потік перевірки нагадувань.
    Працює щосекунди і ніколи не блокується довгими запитами до мережі.
    """
    logger.info("⏱ Фоновий потік планувальника запущено.")

    while True:
        try:
            now = datetime.now(KYIV)

            # Перевіряємо та надсилаємо нагадування, час яких настав
            due_items = db.get_due_reminders(now)
            for row in due_items:
                chat_id = row["chat_id"]
                action = row["text"]
                rem_id = row["id"]
                remind_time = datetime.fromisoformat(row["remind_at"]).astimezone(KYIV)

                alert_text = (
                    f"🔔 <b>НАГАДУВАННЯ!</b>\n\n"
                    f"📌 <b>{html.escape(action)}</b>\n\n"
                    f"🕒 <i>Заплановано на: {remind_time.strftime('%H:%M')}</i>"
                )
                success = send_message(chat_id, alert_text, reply_markup=MAIN_KEYBOARD)
                if success:
                    db.mark_as_sent(rem_id)
                    logger.info(f"✅ Нагадування #{rem_id} надіслано вчасно користувачу {chat_id}")

        except Exception as e:
            logger.error(f"Помилка в планувальнику: {e}")

        time.sleep(1)


def run_bot():
    """Головний цикл бота: Long Polling для миттєвої обробки повідомлень."""
    db.init_db()
    prevent_windows_sleep()

    # Запускаємо легкий health-сервер для хмари (Render / Railway)
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()

    # Запускаємо незалежний потік таймерів нагадувань
    scheduler_thread = threading.Thread(target=reminder_scheduler_loop, daemon=True)
    scheduler_thread.start()

    logger.info("🚀 Бот-асистент активний! Очікування повідомлень...")

    last_update_id = 0
    session = requests.Session()

    try:
        init_resp = session.get(f"{API_BASE}/getUpdates?offset=-1", timeout=(5, 10)).json()
        if init_resp.get("ok") and init_resp.get("result"):
            last_update_id = init_resp["result"][-1]["update_id"]
    except Exception as e:
        logger.warning(f"Ініціалізація update_id: {e}")

    consecutive_errors = 0

    while True:
        try:
            url = f"{API_BASE}/getUpdates?offset={last_update_id + 1}&timeout=3"
            resp = session.get(url, timeout=(5, 10))

            if resp.status_code == 200:
                consecutive_errors = 0
                data = resp.json()
                for update in data.get("result", []):
                    last_update_id = update["update_id"]
                    if "message" in update:
                        handle_incoming_message(update["message"])
            else:
                logger.warning(f"Telegram API status: {resp.status_code}")
                time.sleep(2)

        except requests.exceptions.RequestException as e:
            consecutive_errors += 1
            if consecutive_errors % 5 == 0:
                logger.warning(f"Тимчасовий збій мережі Telegram ({consecutive_errors}): {e}")
            # Перестворюємо сесію при повторних збоях
            session = requests.Session()
            time.sleep(min(consecutive_errors, 5))
        except KeyboardInterrupt:
            logger.info("Бот зупинено користувачем.")
            break
        except Exception as e:
            logger.error(f"Непередбачена помилка: {e}")
            time.sleep(2)


if __name__ == "__main__":
    run_bot()
