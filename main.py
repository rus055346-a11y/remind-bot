# -*- coding: utf-8 -*-
from flask import Flask, request, jsonify
import gspread
import requests
from datetime import datetime
from dateutil.relativedelta import relativedelta
from google.oauth2.service_account import Credentials

app = Flask(__name__)

GREEN_API_INSTANCE = "7107599042"
GREEN_API_TOKEN    = "1a6012c4f46348c896f3146282aa2befcdf93f6be2674957b0"
SPREADSHEET_ID     = "16oNWO9igly5Eaff_g-qcIaADl9fwA9ul1hBX8IBvWWg"
MY_PHONE           = "79150979579"

state = {}

def get_sheet():
    scope = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file("credentials.json", scopes=scope)
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID).sheet1

def send_whatsapp(phone, message):
    url = f"https://api.green-api.com/waInstance{GREEN_API_INSTANCE}/sendMessage/{GREEN_API_TOKEN}"
    data = {"chatId": f"{phone}@c.us", "message": message}
    try:
        requests.post(url, json=data, timeout=10)
    except Exception as e:
        print(f"Send error: {e}")

def get_unpaid_clients():
    sheet = get_sheet()
    rows = sheet.get_all_values()
    unpaid = []
    for i, row in enumerate(rows[1:], start=2):
        if len(row) < 5:
            continue
        name   = row[0]
        phone  = row[1]
        date   = row[3]
        status = row[4]
        paid   = row[5] if len(row) > 5 else ""
        if status == "ojidanie" and paid != "da":
            unpaid.append({"row": i, "name": name, "phone": phone, "date": date})
    return unpaid

def get_todays_clients():
    today = datetime.today().strftime("%Y-%m-%d")
    sheet = get_sheet()
    rows = sheet.get_all_values()
    clients = []
    for i, row in enumerate(rows[1:], start=2):
        if len(row) < 5:
            continue
        name   = row[0]
        phone  = row[1]
        date   = row[3]
        status = row[4]
        paid   = row[5] if len(row) > 5 else ""
        if date == today and status == "ojidanie" and paid != "da":
            clients.append({"row": i, "name": name, "phone": phone, "date": date})
    return clients

def mark_paid_and_reschedule(row_index):
    sheet = get_sheet()
    row = sheet.row_values(row_index)
    date_str = row[3]
    try:
        current_date = datetime.strptime(date_str, "%Y-%m-%d")
        next_date = current_date + relativedelta(months=1)
        next_date_str = next_date.strftime("%Y-%m-%d")
    except:
        next_date_str = date_str
    sheet.update_cell(row_index, 5, "ojidanie")
    sheet.update_cell(row_index, 6, "")
    sheet.update_cell(row_index, 4, next_date_str)

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    if not data:
        return jsonify({"status": "ok"})

    try:
        msg_type = data.get("typeWebhook", "")
        print(f"Webhook: {msg_type}")

        if msg_type == "incomingMessageReceived":
            sender = data["senderData"]["chatId"].replace("@c.us", "")
            message_data = data.get("messageData", {})
            text = ""

            if "textMessageData" in message_data:
                text = message_data["textMessageData"].get("textMessage", "").strip()
            elif "extendedTextMessageData" in message_data:
                text = message_data["extendedTextMessageData"].get("text", "").strip()

            print(f"От: {sender}, текст: '{text}'")

            if "fileMessageData" in message_data or "imageMessageData" in message_data:
                if sender != MY_PHONE:
                    sheet = get_sheet()
                    rows = sheet.get_all_values()
                    found = None
                    for i, row in enumerate(rows[1:], start=2):
                        if len(row) >= 2 and row[1] == sender:
                            found = {"row": i, "name": row[0]}
                            break
                    if found:
                        state[MY_PHONE] = {"action": "confirm_payment", "row": found["row"], "name": found["name"]}
                        send_whatsapp(MY_PHONE, f"{found['name']} прислал(а) файл. Отметить как оплатившего?\n\nОтветь: ДА или НЕТ")
                return jsonify({"status": "ok"})

            if sender == MY_PHONE and text:
                text_upper = text.upper()
                print(f"Команда: {text_upper}")

                if MY_PHONE in state:
                    action = state[MY_PHONE].get("action")

                    if action == "confirm_payment":
                        if text_upper == "ДА":
                            row = state[MY_PHONE]["row"]
                            name = state[MY_PHONE]["name"]
                            mark_paid_and_reschedule(row)
                            del state[MY_PHONE]
                            send_whatsapp(MY_PHONE, f"{name} отмечен как оплативший. Дата перенесена на следующий месяц.")
                        elif text_upper == "НЕТ":
                            del state[MY_PHONE]
                            send_whatsapp(MY_PHONE, "Хорошо, оплата не отмечена.")
                        return jsonify({"status": "ok"})

                    if action in ("select_paid", "select_debtor"):
                        try:
                            index = int(text) - 1
                            clients = state[MY_PHONE]["clients"]
                            if 0 <= index < len(clients):
                                selected = clients[index]
                                mark_paid_and_reschedule(selected["row"])
                                del state[MY_PHONE]
                                send_whatsapp(MY_PHONE, f"{selected['name']} отмечен как оплативший. Дата перенесена на следующий месяц.")
                            else:
                                send_whatsapp(MY_PHONE, "Неверный номер. Попробуй ещё раз.")
                        except:
                            send_whatsapp(MY_PHONE, "Отправь номер из списка (например: 1)")
                        return jsonify({"status": "ok"})

                if text_upper == "ОПЛАЧЕНО":
                    clients = get_todays_clients()
                    if not clients:
                        send_whatsapp(MY_PHONE, "Сегодня все оплатили или нет активных клиентов.")
                    else:
                        msg = "Кто оплатил сегодня?\n\n"
                        for i, c in enumerate(clients, 1):
                            msg += f"{i}. {c['name']}\n"
                        msg += "\nОтветь цифрой"
                        state[MY_PHONE] = {"action": "select_paid", "clients": clients}
                        send_whatsapp(MY_PHONE, msg)

                elif text_upper == "ДОЛЖНИКИ":
                    clients = get_unpaid_clients()
                    if not clients:
                        send_whatsapp(MY_PHONE, "Все клиенты оплатили!")
                    else:
                        msg = "Не оплатили:\n\n"
                        for i, c in enumerate(clients, 1):
                            msg += f"{i}. {c['name']} (должен был {c['date']})\n"
                        msg += "\nОтветь цифрой чтобы отметить оплату"
                        state[MY_PHONE] = {"action": "select_debtor", "clients": clients}
                        send_whatsapp(MY_PHONE, msg)

    except Exception as e:
        print(f"Error: {e}")

    return jsonify({"status": "ok"})

@app.route("/", methods=["GET"])
def index():
    return "Bot is running!"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
