import asyncio
import html
import logging
import sys
from datetime import datetime
from typing import List, Optional, Tuple

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
import pytz
import requests
from pywaze.route_calculator import WazeRouteCalculator

from config import (
    HOME_COORDS,
    HOME_TITLE,
    WORK_COORDS,
    WORK_TITLE,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    TIMEZONE,
)

logger = logging.getLogger(__name__)


def generate_navigation_links(
    start_coords: str, end_coords: str
) -> Tuple[str, str]:
    """Генерує universal deep-links для відкриття в навігаторах."""
    dest_lat, dest_lon = end_coords.split(",")
    # Waze universal link
    waze_url = f"https://waze.com/ul?ll={dest_lat},{dest_lon}&navigate=yes"
    # Google Maps directions URL
    gmaps_url = (
        f"https://www.google.com/maps/dir/?api=1"
        f"&origin={start_coords}&destination={end_coords}&travelmode=driving"
    )
    return waze_url, gmaps_url


async def fetch_waze_routes(
    start_coords: str, end_coords: str, alternatives: int = 3
):
    """Отримує актуальні маршрути з Waze у реальному часі."""
    async with WazeRouteCalculator() as client:
        routes = await client.calc_routes(
            start_coords,
            end_coords,
            alternatives=alternatives,
            real_time=True,
        )
        # Сортуємо маршрути за тривалістю (найшвидший перший)
        routes.sort(key=lambda r: r.duration)
        return routes


def format_telegram_message(
    direction: str,
    from_name: str,
    to_name: str,
    routes: list,
) -> str:
    """Форматує красиве HTML-повідомлення для Telegram."""
    tz = pytz.timezone(TIMEZONE)
    current_time = datetime.now(tz).strftime("%H:%M")

    if direction == "morning":
        header_icon = "🌅"
        direction_title = "Ранкова поїздка на роботу"
    else:
        header_icon = "🌇"
        direction_title = "Вечірня поїздка додому"

    if not routes:
        return (
            f"<b>{header_icon} {direction_title} ({current_time})</b>\n\n"
            f"⚠️ Не вдалося отримати актуальні маршрути від Waze. "
            f"Перевірте навігатори за посиланнями нижче."
        )

    best_route = routes[0]
    best_minutes = round(best_route.duration)
    best_km = best_route.distance

    lines = [
        f"<b>{header_icon} {direction_title}</b>",
        f"🕒 <i>Оновлено: {current_time}</i>",
        f"📍 <b>Маршрут:</b> {html.escape(from_name)} ➡️ {html.escape(to_name)}",
        "",
        f"🏆 <b>НАЙШВИДШИЙ МАРШРУТ (Waze):</b>",
        f"⏱ <b>~{best_minutes} хв</b> ({best_km:.1f} км)",
        f"🛣 <i>{html.escape(best_route.name)}</i>",
        "",
    ]

    if len(routes) > 1:
        lines.append("📊 <b>Альтернативні варіанти:</b>")
        for i, r in enumerate(routes[1:], start=2):
            diff = round(r.duration - best_route.duration)
            diff_str = f"+{diff} хв" if diff > 0 else "однаковий час"
            lines.append(
                f"{i}. <b>{html.escape(r.name)}</b>\n"
                f"   ⏳ {round(r.duration)} хв ({diff_str}) | 📏 {r.distance:.1f} км"
            )
        lines.append("")

    lines.append(
        "💡 <i>Натисніть кнопку нижче, щоб одразу відкрити навігацію з живими заторами:</i>"
    )

    return "\n".join(lines)


def send_telegram_message(
    text: str,
    waze_url: str,
    gmaps_url: str,
    bot_token: Optional[str] = None,
    chat_id: Optional[str] = None,
) -> bool:
    """Надсилає повідомлення з кнопками переходів у Telegram."""
    token = bot_token or TELEGRAM_BOT_TOKEN
    target_chat = chat_id or TELEGRAM_CHAT_ID

    if not token or not target_chat:
        print("\n" + "=" * 50)
        print("⚠️ УВАГА: TELEGRAM_BOT_TOKEN або TELEGRAM_CHAT_ID не вказані.")
        print("Ось вигляд повідомлення, яке було б надіслано в Telegram:")
        print("=" * 50)
        print(text)
        print("-" * 50)
        print(f"Кнопка 1: [🚗 Відкрити у Waze] -> {waze_url}")
        print(f"Кнопка 2: [🗺 Відкрити у Google Maps] -> {gmaps_url}")
        print("=" * 50 + "\n")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": target_chat,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "reply_markup": {
            "inline_keyboard": [
                [
                    {"text": "🚗 Відкрити у Waze", "url": waze_url},
                    {"text": "🗺 Відкрити у Google Maps", "url": gmaps_url},
                ]
            ]
        },
    }

    try:
        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
        if data.get("ok"):
            print("✅ Повідомлення успішно доставлено в Telegram!")
            return True
        else:
            print(f"❌ Помилка Telegram API: {data}")
            return False
    except Exception as e:
        print(f"❌ Помилка при надсиланні в Telegram: {e}")
        return False


async def run_commute_check(direction: str = "morning") -> bool:
    """Виконує одну перевірку маршруту (morning або evening) і надсилає звіт."""
    if direction == "morning":
        start_coords, start_name = HOME_COORDS, HOME_TITLE
        end_coords, end_name = WORK_COORDS, WORK_TITLE
    else:
        start_coords, start_name = WORK_COORDS, WORK_TITLE
        end_coords, end_name = HOME_COORDS, HOME_TITLE

    print(f"🔍 Запит трафіку Waze для: {start_name} ➡️ {end_name}...")
    waze_url, gmaps_url = generate_navigation_links(start_coords, end_coords)

    try:
        routes = await fetch_waze_routes(start_coords, end_coords, alternatives=3)
    except Exception as e:
        print(f"⚠️ Не вдалося отримати маршрути Waze: {e}")
        routes = []

    msg = format_telegram_message(direction, start_name, end_name, routes)
    return send_telegram_message(msg, waze_url, gmaps_url)
