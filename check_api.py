# -*- coding: utf-8 -*-
"""
Диагностика Green API: смотрим состояние инстанса и пробуем тестовую отправку.
Запуск: python check_api.py [тестовый_телефон]
"""
import sys
import json
import requests

GREEN_API_INSTANCE = "7107599042"
GREEN_API_TOKEN    = "1a6012c4f46348c896f3146282aa2befcdf93f6be2674957b0"
BASE = f"https://api.green-api.com/waInstance{GREEN_API_INSTANCE}"

def show(title, url, payload=None):
    print(f"\n=== {title} ===")
    try:
        if payload is None:
            r = requests.get(url, timeout=15)
        else:
            r = requests.post(url, json=payload, timeout=15)
        print(f"HTTP {r.status_code}")
        try:
            print(json.dumps(r.json(), indent=2, ensure_ascii=False))
        except Exception:
            print(r.text[:600])
    except Exception as e:
        print(f"EXCEPTION: {e}")

# 1. Состояние инстанса
show("getStateInstance (должно быть 'authorized')",
     f"{BASE}/getStateInstance/{GREEN_API_TOKEN}")

# 2. Состояние сокета (соединение с WhatsApp)
show("getStatusInstance (должно быть 'online')",
     f"{BASE}/getStatusInstance/{GREEN_API_TOKEN}")

# 3. Настройки инстанса (увидим webhookUrl, instanceState и т.п.)
show("getSettings",
     f"{BASE}/getSettings/{GREEN_API_TOKEN}")

# 4. Опциональная тестовая отправка
if len(sys.argv) > 1:
    phone = sys.argv[1].strip()
    show(f"sendMessage → {phone} (тестовая отправка)",
         f"{BASE}/sendMessage/{GREEN_API_TOKEN}",
         {"chatId": f"{phone}@c.us", "message": "Тест Green API"})
else:
    print("\n(чтобы попробовать отправить — запусти: python check_api.py 79161234567)")
