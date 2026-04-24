# -*- coding: utf-8 -*-
import gspread
import requests
from datetime import datetime
from google.oauth2.service_account import Credentials

GREEN_API_INSTANCE = "7107599042"
GREEN_API_TOKEN    = "1a6012c4f46348c896f3146282aa2befcdf93f6be2674957b0"
SPREADSHEET_ID     = "16oNWO9igly5Eaff_g-qcIaADl9fwA9ul1hBX8IBvWWg"

MORNING_TIME = "09:00"
EVENING_TIME = "19:00"

def message_text():
    return (
        f"Добрый день! Сегодня у вас оплата.\n\n"
        f"По номеру карты\n"
        f"2200 1520 4571 8817\n"
        f"Альфа-банк\n\n"
        f"Либо по платежной ссылке\n"
        f"https://pay.alfabank.ru/sc/pQtIqtQXJkuoauSF\n\n"
        f"После оплаты скиньте чек"
    )

def get_clients():
    scope = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file("credentials.json", scopes=scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID).sheet1
    return sheet.get_all_values()

def send_whatsapp(phone, message):
    url = f"https://api.green-api.com/waInstance{GREEN_API_INSTANCE}/sendMessage/{GREEN_API_TOKEN}"
    data = {"chatId": f"{phone}@c.us", "message": message}
    try:
        response = requests.post(url, json=data, timeout=10)
        print(f"  OK -> {phone}: {response.json()}")
    except Exception as e:
        print(f"  ERROR -> {phone}: {e}")

def send_reminders():
    today = datetime.today().strftime("%Y-%m-%d")
    print(f"Zapusk: {today}")
    rows = get_clients()
    print(f"Klientov: {len(rows) - 1}")

    for row in rows[1:]:
        if len(row) < 5:
            continue
        name   = row[0]
        phone  = row[1]
        amount = row[2]
        date   = row[3]
        status = row[4]

        if date == today and status == "ojidanie":
            print(f"Otpravlyaem: {name} ({phone})")
            send_whatsapp(phone, message_text())

send_reminders()
