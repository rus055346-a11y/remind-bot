# -*- coding: utf-8 -*-
import gspread
import requests
from datetime import datetime
from google.oauth2.service_account import Credentials

GREEN_API_INSTANCE = "7107599042"
GREEN_API_TOKEN    = "1a6012c4f46348c896f3146282aa2befcdf93f6be2674957b0"
SPREADSHEET_ID = "16oNWO9igly5Eaff_g-qcIaADl9fwA9ul1hBX8IBvWWg"

def get_clients():
    scope = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file("credentials.json", scopes=scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID).sheet1
    rows = sheet.get_all_values()
    return rows

def send_whatsapp(phone, message):
    url = f"https://api.green-api.com/waInstance{GREEN_API_INSTANCE}/sendMessage/{GREEN_API_TOKEN}"
    data = {"chatId": f"{phone}@c.us", "message": message}
    response = requests.post(url, json=data, timeout=10)
    print(response.json())

today = datetime.today().strftime("%Y-%m-%d")
rows = get_clients()
print(f"Strok v tablice: {len(rows)}")

# Propuskaem zagolovok (pervaya stroka)
for row in rows[1:]:
    name   = row[0]  # Imya
    phone  = row[1]  # Telefon
    amount = row[2]  # Summa
    date   = row[3]  # Data napominaniya
    status = row[4]  # Status

    print(f"Klient: {name}, data: {date}, status: {status}, segodnya: {today}")

    if date == today and status == "ojidanie":
        print(f"Otpravlyaem {name}...")
        send_whatsapp(phone, f"Zdravstvuyte, {name}! Napominaem ob oplate: {amount} rub.")