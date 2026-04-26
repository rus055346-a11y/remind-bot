# -*- coding: utf-8 -*-
"""
Скрипт автоматической отправки напоминаний.
Запускается планировщиком Windows:
  10:00 → 1-е напоминание (всем у кого сегодня оплата)
  19:00 → 2-е напоминание (только тем, кто за день не написал ничего и не прислал чек)

Использование:
  python bot.py          # режим определяется по времени (до 14:00 — first, после — second)
  python bot.py first    # принудительно 1-е напоминание
  python bot.py second   # принудительно 2-е напоминание
"""
import sys
import os
import gspread
import requests
import logging
from datetime import datetime
from google.oauth2.service_account import Credentials

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_PATH = os.path.join(BASE_DIR, "credentials.json")

# Логи в файл bot.log + в stdout. Без этого утренние ошибки доставки невидимы.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(BASE_DIR, "bot.log"), encoding="utf-8"),
    ],
)
log = logging.getLogger("bot")

GREEN_API_INSTANCE = "7107599042"
GREEN_API_TOKEN    = "1a6012c4f46348c896f3146282aa2befcdf93f6be2674957b0"
SPREADSHEET_ID     = "16oNWO9igly5Eaff_g-qcIaADl9fwA9ul1hBX8IBvWWg"

REMINDER_MESSAGES = {
    "first": (
        "Добрый день! Сегодня у вас оплата.\n\n"
        "По номеру карты\n"
        "2200 1520 4571 8817\n"
        "Альфа-банк\n\n"
        "Либо по платежной ссылке\n"
        "https://pay.alfabank.ru/sc/pQtIqtQXJkuoauSF\n\n"
        "После оплаты скиньте чек"
    ),
    "second": "Сегодня ждать оплату?",
}

# ---------- Google Sheets ----------

def _gs_book():
    scope = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=scope)
    return gspread.authorize(creds).open_by_key(SPREADSHEET_ID)

def get_sheet():
    return _gs_book().sheet1

def get_messages_sheet(book=None):
    book = book or _gs_book()
    try:
        return book.worksheet("messages")
    except gspread.WorksheetNotFound:
        return None  # лист ещё не создан → значит входящих не было

# ---------- WhatsApp ----------

def send_whatsapp(phone, message):
    """Возвращает (success: bool, info: str). Не замалчивает ошибки Green API."""
    if not phone:
        return False, "пустой телефон"
    url = f"https://api.green-api.com/waInstance{GREEN_API_INSTANCE}/sendMessage/{GREEN_API_TOKEN}"
    data = {"chatId": f"{str(phone).strip()}@c.us", "message": message}
    try:
        resp = requests.post(url, json=data, timeout=15)
    except Exception as e:
        log.error(f"WhatsApp EXCEPTION -> {phone}: {e}")
        return False, str(e)
    try:
        payload = resp.json()
    except Exception:
        payload = {"raw": resp.text[:300]}
    if resp.status_code != 200 or not payload.get("idMessage"):
        log.error(f"WhatsApp FAIL {resp.status_code} -> {phone}: {payload}")
        return False, f"HTTP {resp.status_code}: {payload}"
    log.info(f"WhatsApp OK -> {phone}: idMessage={payload['idMessage']}")
    return True, payload["idMessage"]

# ---------- Логика «клиент ответил сегодня?» ----------

def get_phones_with_response_today(book):
    """Возвращает множество телефонов, с которых сегодня было входящее сообщение."""
    msgs = get_messages_sheet(book)
    if msgs is None:
        return set()
    today_iso = datetime.today().strftime("%Y-%m-%d")
    phones = set()
    try:
        all_rows = msgs.get_all_values()
    except Exception as e:
        log.warning(f": не удалось прочитать messages: {e}")
        return set()
    if len(all_rows) < 2:
        return set()
    headers = all_rows[0]
    try:
        ph_idx = headers.index("phone")
        ts_idx = headers.index("created_at")
    except ValueError:
        return set()
    for r in all_rows[1:]:
        if len(r) <= max(ph_idx, ts_idx):
            continue
        if r[ts_idx].startswith(today_iso) and r[ph_idx]:
            phones.add(r[ph_idx])
    return phones

# ---------- Основной цикл ----------

def send_reminders(mode):
    today = datetime.today().strftime("%Y-%m-%d")
    today_dm = datetime.today().strftime("%d.%m.%Y")
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    log.info(f"=== Напоминания [{mode}] [{today}] {now} ===")

    book = _gs_book()
    sheet = book.sheet1
    rows = sheet.get_all_values()

    responded = get_phones_with_response_today(book) if mode == "second" else set()
    if mode == "second":
        log.info(f"  ответили сегодня: {len(responded)} клиент(ов)")

    sent = skipped_responded = skipped_no_first = 0

    for i, row in enumerate(rows[1:], start=2):
        if len(row) < 4 or not row[1]:
            continue
        phone  = row[1]
        date   = row[3]
        status = row[4] if len(row) > 4 else "ojidanie"
        last_sent = row[5] if len(row) > 5 else ""

        if date != today or status != "ojidanie":
            continue

        if mode == "first":
            log.info(f"-> 1-е: {row[0]} ({phone})")
            ok, info = send_whatsapp(phone, REMINDER_MESSAGES["first"])
            if ok:
                sheet.update_cell(i, 6, now)
                sent += 1
            else:
                log.error(f"   НЕ отправлено: {info}")

        elif mode == "second":
            # 2-е шлём только если клиент ничего не написал сегодня
            # и при этом 1-е сегодня уже было отправлено (иначе нелогично)
            if phone in responded:
                log.info(f"   пропуск (ответил): {row[0]} ({phone})")
                skipped_responded += 1
                continue
            if not last_sent.startswith(today_dm):
                log.info(f"   пропуск (1-е сегодня не отправлялось): {row[0]} ({phone})")
                skipped_no_first += 1
                continue
            log.info(f"-> 2-е: {row[0]} ({phone})")
            ok, info = send_whatsapp(phone, REMINDER_MESSAGES["second"])
            if ok:
                sheet.update_cell(i, 6, now)
                sent += 1
            else:
                log.error(f"   НЕ отправлено: {info}")

    log.info(f"=== Итог режима {mode}: отправлено {sent} ===")
    if mode == "second":
        log.info(f"Пропущено (ответил): {skipped_responded}")
        log.info(f"Пропущено (1-е не было): {skipped_no_first}")

def detect_mode():
    """Если режим не задан — определяем по времени суток."""
    if len(sys.argv) > 1:
        arg = sys.argv[1].strip().lower()
        if arg in ("first", "1", "morning"):
            return "first"
        if arg in ("second", "2", "evening"):
            return "second"
    # авто: до 14:00 — первое, после — второе
    return "first" if datetime.now().hour < 14 else "second"

if __name__ == "__main__":
    send_reminders(detect_mode())
