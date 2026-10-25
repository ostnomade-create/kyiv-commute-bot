import json
import logging
import math
import os
import re
import urllib.request
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

HOME_COORDS = (50.3893668, 30.4746391)  # вул. Юлії Здановської, 36
WORK_COORDS = (50.4495142, 30.4935782)  # вул. Олександра Кониського, 15

# Локальний кеш станцій Києва, якщо сервер БРСМ тимчасово недоступний
FALLBACK_KYIV_STATIONS = [
    {
        "id": 37,
        "city": "Київ",
        "address": "вул. Жуковського",
        "building": "22",
        "lat": 50.398273,
        "lng": 30.489777,
        "has_fuel": True,
    },
    {
        "id": 117,
        "city": "Київ",
        "address": "вул. Святослава Хороброго",
        "building": "16",
        "lat": 50.413289,
        "lng": 30.457812,
        "has_fuel": True,
    },
    {
        "id": 168,
        "city": "Київ",
        "address": "вул. Саперно-Слобідська",
        "building": "22",
        "lat": 50.407812,
        "lng": 30.541289,
        "has_fuel": True,
    },
    {
        "id": 132,
        "city": "Київ",
        "address": "вул. Новокостянтинівська",
        "building": "1В",
        "lat": 50.476214,
        "lng": 30.492154,
        "has_fuel": True,
    },
]


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def get_brsm_prices() -> Dict[str, str]:
    """Отримує актуальні ціни БРСМ-Нафта у Києві з моніторингу AUTO.RIA/Мінфін."""
    prices = {"A95": "87.98", "DP": "100.98", "GAS": "50.99"}
    try:
        url = "https://auto.ria.com/uk/toplivo/kiev/"
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            html = resp.read().decode("utf-8")
            m = re.search(r"<tr[^>]*>.*?БРСМ-Нафта.*?</tr>", html, re.S)
            if m:
                cells = [
                    re.sub(r"<[^<]+?>", "", c).strip()
                    for c in re.findall(r"<td[^>]*>(.*?)</td>", m.group(0), re.S)
                ]
                # Формат AUTO.RIA: [..., 'БРСМ-Нафта', '-', '-', 'A95', 'A92', 'DP', 'GAS']
                # cells: ['БРСМ-Нафта', '-', '-', '87.98', '-', '100.98', '50.99']
                val_cells = [c for c in cells if c and c != "-"]
                if len(val_cells) >= 3:
                    # Останні три зазвичай: 95, ДП, Газ
                    prices["A95"] = val_cells[-3]
                    prices["DP"] = val_cells[-2]
                    prices["GAS"] = val_cells[-1]
    except Exception as e:
        logger.warning(f"Не вдалося оновити ціни з мережі: {e}")

    return prices


STATIONS_CACHE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "brsm_stations.json"
)
_stations_mem_cache = None


def get_brsm_stations() -> List[dict]:
    """Отримує список АЗС БРСМ та їхню доступність із кешуванням."""
    global _stations_mem_cache
    if _stations_mem_cache:
        return _stations_mem_cache

    # Спроба з локального файлу
    if os.path.exists(STATIONS_CACHE_FILE):
        try:
            with open(STATIONS_CACHE_FILE, "r", encoding="utf-8") as f:
                _stations_mem_cache = json.load(f)
                if _stations_mem_cache:
                    return _stations_mem_cache
        except Exception:
            pass

    # Якщо немає кешу — завантажуємо
    url = "https://td4.brsm-nafta.com/api/v2/Mobile/get_full_ffs"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            raw_stations = json.loads(resp.read().decode("utf-8"))
            parsed = []
            for s in raw_stations:
                try:
                    slat = float(s["lat"])
                    slng = float(s["lng"])
                    city = s.get("city", "")
                    if "київ" in city.lower() or "київ" in s.get("region", "").lower():
                        parsed.append(
                            {
                                "id": s.get("id"),
                                "city": city,
                                "address": s.get("address", "").strip(),
                                "building": s.get("building", "").strip(),
                                "lat": slat,
                                "lng": slng,
                                "has_fuel": bool(s.get("fuels")),
                            }
                        )
                except Exception:
                    continue
            if parsed:
                _stations_mem_cache = parsed
                try:
                    with open(STATIONS_CACHE_FILE, "w", encoding="utf-8") as f:
                        json.dump(parsed, f, ensure_ascii=False)
                except Exception:
                    pass
                return parsed
    except Exception as e:
        logger.warning(f"Сервер BRSM API недоступний ({e}), використовуємо кеш.")

    return FALLBACK_KYIV_STATIONS


def find_nearest_stations(
    lat: float, lon: float, count: int = 2
) -> List[Tuple[float, dict]]:
    """Знаходить найближчі АЗС БРСМ до заданих координат."""
    stations = get_brsm_stations()
    dist_list = []
    for s in stations:
        d = haversine(lat, lon, s["lat"], s["lng"])
        dist_list.append((d, s))
    dist_list.sort(key=lambda x: x[0])
    return dist_list[:count]


def format_brsm_fuel_report() -> Tuple[str, List[List[dict]]]:
    """Форматує красиве повідомлення для Telegram з цінами та найближчими АЗС."""
    prices = get_brsm_prices()
    near_home = find_nearest_stations(HOME_COORDS[0], HOME_COORDS[1], count=1)
    near_work = find_nearest_stations(WORK_COORDS[0], WORK_COORDS[1], count=1)

    lines = [
        "⛽ <b>БРСМ-Нафта • Моніторинг цін та АЗК</b>",
        "📍 <i>Місто: Київ</i>",
        "",
        "💰 <b>Актуальні ціни на стелі:</b>",
        f"• <b>Бензин А-95:</b> <code>{prices.get('A95', '87.98')} грн/л</code>",
        f"• <b>Дизель (ДП):</b> <code>{prices.get('DP', '100.98')} грн/л</code>",
        f"• <b>Газ (LPG):</b> <code>{prices.get('GAS', '50.99')} грн/л</code>",
        "",
        "🛣 <b>Найближчі АЗК до вашого маршруту:</b>",
    ]

    inline_keyboard = []

    if near_home:
        d, s = near_home[0]
        status = "✅ Пальне в наявності" if s["has_fuel"] else "⚠️ Тимчасово немає"
        addr = f"{s['address']} {s['building']}".strip()
        lines.append(f"🏠 <b>Біля дому ({d:.1f} км):</b>")
        lines.append(f"   АЗК #{s['id']} ({addr})")
        lines.append(f"   Статус: {status}\n")

        waze_url = f"https://waze.com/ul?ll={s['lat']},{s['lng']}&navigate=yes"
        inline_keyboard.append([{"text": f"🚗 Waze до АЗК #{s['id']} (Дім)", "url": waze_url}])

    if near_work:
        d, s = near_work[0]
        status = "✅ Пальне в наявності" if s["has_fuel"] else "⚠️ Тимчасово немає"
        addr = f"{s['address']} {s['building']}".strip()
        lines.append(f"🏢 <b>У бік роботи ({d:.1f} км):</b>")
        lines.append(f"   АЗК #{s['id']} ({addr})")
        lines.append(f"   Статус: {status}\n")

        waze_url = f"https://waze.com/ul?ll={s['lat']},{s['lng']}&navigate=yes"
        inline_keyboard.append([{"text": f"🚗 Waze до АЗК #{s['id']} (Робота)", "url": waze_url}])

    return "\n".join(lines), inline_keyboard
