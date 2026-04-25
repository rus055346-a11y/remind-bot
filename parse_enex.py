# -*- coding: utf-8 -*-
"""
Парсер Downloads.enex → строки для Google Sheets (Имя, Телефон, Сумма, Дата платежа).
Запуск: python parse_enex.py            # только парсит и показывает превью
        python parse_enex.py --upload   # заливает в Google Sheets (после подтверждения)
"""
import re
import sys
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENEX_FILE = os.path.join(BASE_DIR, "Downloads.enex")
SPREADSHEET_ID = "16oNWO9igly5Eaff_g-qcIaADl9fwA9ul1hBX8IBvWWg"
CREDENTIALS_PATH = os.path.join(BASE_DIR, "credentials.json")

# ---------- Парсинг ----------

def parse_amount_value(s):
    """'10000' -> '10000', '383.000' -> '383000', '10000+3000' -> '13000', '10' -> '10'"""
    if '+' in s:
        try:
            parts = [int(p.replace('.', '').replace(',', '').replace(' ', '')) for p in s.split('+')]
            return str(sum(parts))
        except Exception:
            return s
    return s.replace('.', '').replace(',', '').replace(' ', '')

NUMBER_TOKEN = re.compile(r'^\d+(?:[.,]\d+)?(?:\+\d+(?:[.,]\d+)?)*$')

def parse_title(title):
    """'Акрам Строймастер 10000' -> ('Акрам Строймастер', '10000').
       'Георгий Лианозово 356000 с марта 383.000' -> ('Георгий Лианозово', '383000') — берём ПОСЛЕДНЮЮ сумму."""
    parts = title.strip().split()
    first_idx = last_idx = None
    for i, t in enumerate(parts):
        if NUMBER_TOKEN.fullmatch(t):
            if first_idx is None:
                first_idx = i
            last_idx = i
    if first_idx is None:
        return title.strip(), ""
    name = ' '.join(parts[:first_idx]).strip()
    return name, parse_amount_value(parts[last_idx])

PHONE_RE = re.compile(r'(?:\+?\s?7|8)[\s\-\(\)\d]{9,18}')

def extract_phone(content):
    """Берём первый осмысленный номер из content. Возвращаем только цифры в формате 7XXXXXXXXXX."""
    text = re.sub(r'<[^>]+>', ' ', content or '')
    for raw in PHONE_RE.findall(text):
        digits = re.sub(r'\D', '', raw)
        if len(digits) == 11:
            if digits.startswith('8'):
                digits = '7' + digits[1:]
            return digits
        if len(digits) == 10:
            return '7' + digits
    return ""

def parse_reminder(s):
    """'20251116T060000Z' -> '2025-11-16'."""
    if not s:
        return ""
    m = re.match(r'(\d{4})(\d{2})(\d{2})', s)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""

def parse_enex(path):
    src = open(path, encoding='utf-8').read()
    notes = re.findall(r'<note>.*?</note>', src, re.DOTALL)
    out = []
    skipped_no_reminder = []
    for n in notes:
        title_m = re.search(r'<title>([^<]*)</title>', n)
        title = title_m.group(1) if title_m else ""
        rem_m = re.search(r'<reminder-time>([^<]*)</reminder-time>', n)
        if not rem_m:
            skipped_no_reminder.append(title)
            continue
        date = parse_reminder(rem_m.group(1))
        content_m = re.search(r'<content>(.*?)</content>', n, re.DOTALL)
        content = content_m.group(1) if content_m else ""
        name, amount = parse_title(title)
        phone = extract_phone(content)
        out.append({
            "name": name or title,
            "phone": phone,
            "amount": amount,
            "date": date,
            "raw_title": title,
        })
    return out, skipped_no_reminder

# ---------- Превью ----------

def preview(rows):
    print(f"\nРаспаршено: {len(rows)} записей\n")
    print(f"{'#':>3} | {'Имя':<35} | {'Телефон':<13} | {'Сумма':>8} | {'Дата':<10}")
    print("-" * 90)
    for i, r in enumerate(rows, 1):
        phone_disp = r['phone'] or '⚠ нет'
        print(f"{i:>3} | {r['name'][:35]:<35} | {phone_disp:<13} | {r['amount']:>8} | {r['date']:<10}")
    no_phone = [r for r in rows if not r['phone']]
    if no_phone:
        print(f"\n⚠ Без телефона: {len(no_phone)} записей — будут залиты с пустой колонкой B, заполнишь вручную")

# ---------- Загрузка в Sheets ----------

def upload(rows, mode):
    import gspread
    from google.oauth2.service_account import Credentials
    scope = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=scope)
    sheet = gspread.authorize(creds).open_by_key(SPREADSHEET_ID).sheet1

    if mode == "replace":
        existing = sheet.get_all_values()
        if len(existing) > 1:
            # очищаем со 2-й строки
            sheet.batch_clear([f"A2:F{len(existing)}"])
            print(f"Очистил старые {len(existing)-1} строк(и)")

    payload = []
    for r in rows:
        payload.append([r['name'], r['phone'], r['amount'], r['date'], "ojidanie", ""])

    # append блоком
    sheet.append_rows(payload, value_input_option="USER_ENTERED")
    print(f"Залито {len(payload)} строк(и) в Google Sheets ✓")

# ---------- main ----------

if __name__ == "__main__":
    rows, skipped = parse_enex(ENEX_FILE)
    if skipped:
        print("Пропущено (нет reminder-time):")
        for s in skipped:
            print(f"  - {s}")

    rows.sort(key=lambda r: r['date'])
    preview(rows)

    if "--upload" in sys.argv:
        mode = "replace" if "--replace" in sys.argv else "append"
        ans = input(f"\nЗалить эти {len(rows)} записей режим={mode}? (yes/no): ").strip().lower()
        if ans in ("yes", "y", "да", "д"):
            upload(rows, mode)
        else:
            print("Отменено.")
