import re
from datetime import datetime, timedelta
from typing import Optional, Tuple
import pytz

KYIV = pytz.timezone("Europe/Kyiv")

WEEKDAYS = {
    "понеділок": 0,
    "вівторок": 1,
    "середу": 2,
    "середа": 2,
    "четвер": 3,
    "п'ятницю": 4,
    "п’ятницю": 4,
    "пʼятницю": 4,
    "пятницю": 4,
    "п'ятниця": 4,
    "п’ятниця": 4,
    "пʼятниця": 4,
    "пятниця": 4,
    "суботу": 5,
    "субота": 5,
    "неділю": 6,
    "неділя": 6,
}

MONTHS = {
    "січня": 1,
    "лютого": 2,
    "березня": 3,
    "квітня": 4,
    "травня": 5,
    "червня": 6,
    "липня": 7,
    "серпня": 8,
    "вересня": 9,
    "жовтня": 10,
    "листопада": 11,
    "грудня": 12,
}


def remove_spans(text: str, spans: list) -> str:
    sorted_spans = sorted(spans, key=lambda s: s[0], reverse=True)
    res = text
    for start, end in sorted_spans:
        res = res[:start] + " " + res[end:]
    res = re.sub(r"\s+", " ", res).strip()
    return res


def parse_reminder(text: str, base_dt: Optional[datetime] = None) -> Tuple[Optional[str], Optional[datetime]]:
    if base_dt is None:
        base_dt = datetime.now(KYIV)

    t = text.strip()

    # Прибираємо вступні слова: "Нагадай", "Постав нагадування", "Напомни" тощо
    t = re.sub(
        r"^(будь ласка,?\s*)?(постав|створи|зроби|додай)?\s*(нагадування|напоминание)?\s*(нагадай|нагадати|напомни|напомнить|remind)?\s*(мені\s+)?",
        "",
        t,
        flags=re.I,
    ).strip()

    spans_to_remove = []

    # 1. Відносний час ("через X хвилин / годин / днів / секунд")
    rel_m = re.search(
        r"\bчерез\s+(\d+)\s*(хв|хвилин[а-я]*|год|годин[а-я]*|дн[іе]в|дня|день|сек|секунд[а-я]*)\b",
        t,
        re.I,
    )
    if rel_m:
        num = int(rel_m.group(1))
        unit = rel_m.group(2).lower()
        if unit.startswith("хв"):
            delta = timedelta(minutes=num)
        elif unit.startswith("год"):
            delta = timedelta(hours=num)
        elif unit.startswith("сек"):
            delta = timedelta(seconds=num)
        elif unit.startswith("дн") or unit.startswith("ден"):
            delta = timedelta(days=num)
        else:
            delta = timedelta(minutes=num)

        target_dt = base_dt + delta
        spans_to_remove.append(rel_m.span())
        action_text = remove_spans(t, spans_to_remove)
        action_text = re.sub(r"^(що|щоб|про|про те,? що)\s+", "", action_text, flags=re.I).strip()
        return action_text or "Нагадування", target_dt

    # 1b. Через півгодини / півтори години
    half_m = re.search(r"\bчерез\s+(півгодини|пів години|півтора? години)\b", t, re.I)
    if half_m:
        phr = half_m.group(1).lower()
        delta = timedelta(minutes=90 if "півтор" in phr else 30)
        target_dt = base_dt + delta
        spans_to_remove.append(half_m.span())
        action_text = remove_spans(t, spans_to_remove)
        action_text = re.sub(r"^(що|щоб|про|про те,? що)\s+", "", action_text, flags=re.I).strip()
        return action_text or "Нагадування", target_dt

    # 2. Шукаємо час:
    # 2a: з прийменником (о, об, в, у, на): "на 15:00", "о 17-45", "в 14", "о 9 ранку"
    time_m = re.search(
        r"\b(?:о|об|в|у|на)\s+(\d{1,2})(?:[:.-](\d{2}))?\s*(ранку|вечора|дня)?\b",
        t,
        re.I,
    )
    has_explicit_time = False
    hours, minutes = 9, 0

    if time_m:
        hours = int(time_m.group(1))
        minutes = int(time_m.group(2)) if time_m.group(2) else 0
        mod = time_m.group(3)
        if mod:
            m_str = mod.lower()
            if ("веч" in m_str or "дня" in m_str) and hours < 12:
                hours += 12
            elif "ран" in m_str and hours == 12:
                hours = 0
        has_explicit_time = True
        spans_to_remove.append(time_m.span())
    else:
        # 2b: прямий час без прийменника: "15:00", "17-45", "14.30"
        direct_time_m = re.search(r"\b(\d{1,2})[:.-](\d{2})\b", t)
        if direct_time_m:
            hours = int(direct_time_m.group(1))
            minutes = int(direct_time_m.group(2))
            if 0 <= hours <= 23 and 0 <= minutes <= 59:
                has_explicit_time = True
                spans_to_remove.append(direct_time_m.span())

    # 3. Шукаємо дату:
    target_date = None

    # а) Специфічні слова: сьогодні, завтра, післязавтра
    day_rel_m = re.search(r"\b(?:на\s+)?(сьогодні|завтра|післязавтра)\b", t, re.I)
    if day_rel_m:
        word = day_rel_m.group(1).lower()
        offset = 0 if word == "сьогодні" else (1 if word == "завтра" else 2)
        target_date = base_dt.date() + timedelta(days=offset)
        spans_to_remove.append(day_rel_m.span())

    # б) День тижня: "в п'ятницю", "на п'ятницю", "у середу"
    if not target_date:
        weekdays_regex = r"(?:понеділок|вівторок|середу|середа|четвер|п['’ʼ`]?ятницю|п['’ʼ`]?ятниця|пятницю|пятниця|суботу|субота|неділю|неділя)"
        w_m = re.search(
            rf"\b(?:в|у|на|у наступн[уий]|в наступн[уий])?\s*({weekdays_regex})\b",
            t,
            re.I,
        )
        if w_m:
            w_raw = w_m.group(1).lower().replace("’", "'").replace("ʼ", "'").replace("`", "'")
            target_weekday = None
            for k, val in WEEKDAYS.items():
                if k == w_raw or k.replace("'", "") == w_raw.replace("'", ""):
                    target_weekday = val
                    break
            if target_weekday is not None:
                days_ahead = target_weekday - base_dt.weekday()
                cand_date = base_dt.date() + timedelta(days=days_ahead)
                if cand_date < base_dt.date() or (
                    cand_date == base_dt.date()
                    and base_dt.replace(hour=hours, minute=minutes, second=0, microsecond=0) <= base_dt
                ):
                    cand_date += timedelta(days=7)
                target_date = cand_date
                spans_to_remove.append(w_m.span())

    # в) Число місяця: "25 жовтня", "1 січня"
    if not target_date:
        months_pattern = "|".join(re.escape(k) for k in MONTHS.keys())
        cal_m = re.search(rf"\b(\d{1,2})\s*({months_pattern})\b", t, re.I)
        if cal_m:
            day = int(cal_m.group(1))
            month = MONTHS[cal_m.group(2).lower()]
            year = base_dt.year
            cand_dt = base_dt.replace(year=year, month=month, day=day)
            if cand_dt.date() < base_dt.date():
                cand_dt = cand_dt.replace(year=year + 1)
            target_date = cand_dt.date()
            spans_to_remove.append(cal_m.span())

    if target_date and not has_explicit_time:
        hours, minutes = 9, 0

    if not target_date and has_explicit_time:
        cand_dt = base_dt.replace(hour=hours, minute=minutes, second=0, microsecond=0)
        if cand_dt <= base_dt:
            cand_dt += timedelta(days=1)
        target_date = cand_dt.date()

    if not target_date:
        return None, None

    final_dt = base_dt.replace(
        year=target_date.year,
        month=target_date.month,
        day=target_date.day,
        hour=hours,
        minute=minutes,
        second=0,
        microsecond=0,
    )

    action_text = remove_spans(t, spans_to_remove)
    action_text = re.sub(r"^(що|щоб|про|про те,? що)\s+", "", action_text, flags=re.I).strip()

    return action_text or "Нагадування", final_dt
