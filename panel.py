# -*- coding: utf-8 -*-
"""
Система напоминаний об оплате
- Веб-панель управления
- Отправка WhatsApp через Green API
- Google Sheets как база данных
"""
from flask import Flask, request, jsonify, render_template_string, redirect, session
import gspread
import requests
import os
import traceback
import logging
from datetime import datetime
from dateutil.relativedelta import relativedelta
from google.oauth2.service_account import Credentials
import functools

# Абсолютный путь к папке скрипта — чтобы credentials.json находился независимо от cwd
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_PATH = os.path.join(BASE_DIR, "credentials.json")

# Логи в консоль + в файл рядом со скриптом
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(BASE_DIR, "panel.log"), encoding="utf-8"),
    ],
)
log = logging.getLogger("panel")

app = Flask(__name__)
app.secret_key = "remind_bot_secret_2026"

# ============================================================
# НАСТРОЙКИ
# ============================================================
GREEN_API_INSTANCE = "7107599042"
GREEN_API_TOKEN    = "1a6012c4f46348c896f3146282aa2befcdf93f6be2674957b0"
SPREADSHEET_ID     = "16oNWO9igly5Eaff_g-qcIaADl9fwA9ul1hBX8IBvWWg"
PANEL_PASSWORD     = "1234"  # Поменяй на свой пароль!

# ============================================================
# СТРУКТУРА ТАБЛИЦЫ
# A=Имя, B=Телефон, C=Сумма, D=Дата, E=Статус, F=Последнее сообщение
# ============================================================

HTML_LOGIN = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Вход</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;600;700&display=swap');
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family:'Manrope',sans-serif; background:#0a0a0a; color:#fff; min-height:100vh; display:flex; align-items:center; justify-content:center; }
  .box { background:#141414; border:1px solid #222; border-radius:16px; padding:32px; width:320px; }
  h1 { font-size:20px; margin-bottom:24px; text-align:center; }
  input { width:100%; background:#0a0a0a; border:1px solid #333; border-radius:10px; padding:12px; color:#fff; font-size:15px; font-family:'Manrope',sans-serif; margin-bottom:12px; }
  button { width:100%; background:#44ff88; color:#000; border:none; border-radius:10px; padding:12px; font-size:15px; font-weight:700; cursor:pointer; font-family:'Manrope',sans-serif; }
  .error { color:#ff4444; font-size:13px; text-align:center; margin-bottom:12px; }
</style>
</head>
<body>
<div class="box">
  <h1>🔐 Оплаты</h1>
  {% if error %}<div class="error">Неверный пароль</div>{% endif %}
  <form method="post">
    <input type="password" name="password" placeholder="Пароль" autofocus>
    <button type="submit">Войти</button>
  </form>
</div>
</body>
</html>
"""

HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<title>Оплаты</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700&display=swap');
  * { margin:0; padding:0; box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
  body { font-family:'Manrope',sans-serif; background:#0a0a0a; color:#fff; min-height:100vh; padding:16px; padding-bottom:80px; }
  .header { display:flex; justify-content:space-between; align-items:center; margin-bottom:20px; gap:10px; }
  h1 { font-size:22px; font-weight:700; }
  .sub { color:#666; font-size:12px; margin-top:2px; }
  .header-btns { display:flex; gap:8px; }
  .refresh-btn { background:#1a1a1a; border:1px solid #2a2a2a; color:#fff; border-radius:10px; padding:8px 14px; font-size:13px; font-weight:600; cursor:pointer; font-family:'Manrope',sans-serif; }
  .logout-btn { background:#1a0000; border:1px solid #3a0000; color:#ff4444; border-radius:10px; padding:8px 14px; font-size:13px; font-weight:600; cursor:pointer; font-family:'Manrope',sans-serif; }
  .stats { display:grid; grid-template-columns:repeat(3,1fr); gap:10px; margin-bottom:20px; }
  .stat { background:#141414; border:1px solid #222; border-radius:12px; padding:12px; text-align:center; }
  .stat-num { font-size:28px; font-weight:700; line-height:1; }
  .stat-label { color:#666; font-size:11px; margin-top:4px; }
  .stat.red .stat-num { color:#ff4444; }
  .stat.yellow .stat-num { color:#ffaa44; }
  .stat.green .stat-num { color:#44ff88; }
  .filter-tabs { display:flex; gap:8px; margin-bottom:16px; overflow-x:auto; padding-bottom:4px; }
  .filter-tabs::-webkit-scrollbar { display:none; }
  .tab { border:1px solid #2a2a2a; background:#141414; color:#888; border-radius:20px; padding:6px 14px; font-size:12px; font-weight:600; cursor:pointer; white-space:nowrap; font-family:'Manrope',sans-serif; }
  .tab.active { background:#fff; color:#000; border-color:#fff; }
  .cards { display:flex; flex-direction:column; gap:10px; }
  .card { background:#141414; border:1px solid #222; border-radius:14px; padding:16px; transition:all 0.4s ease; overflow:hidden; max-height:1000px; }
  .card.removing { opacity:0; transform:translateX(100px); max-height:0; padding:0; margin:0; }
  .card-top { display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:12px; gap:10px; }
  .card-name { font-size:16px; font-weight:700; word-break:break-word; }
  .card-phone { color:#666; font-size:12px; margin-top:2px; word-break:break-word; }
  .badge { display:inline-block; padding:4px 10px; border-radius:20px; font-size:11px; font-weight:700; white-space:nowrap; }
  .badge.today { background:#2a1a00; color:#ffaa44; }
  .badge.late { background:#1a0000; color:#ff4444; }
  .badge.future { background:#0a0a1a; color:#4488ff; }
  .card-info { display:flex; gap:16px; margin-bottom:14px; flex-wrap:wrap; }
  .info-label { color:#aaa; font-size:12px; line-height:1.45; word-break:break-word; }
  .info-value { font-size:14px; font-weight:600; margin-top:2px; }
  .sent-info { background:#0d1a0d; border:1px solid #1a3a1a; border-radius:8px; padding:8px 12px; margin-bottom:12px; font-size:12px; color:#44aa66; }
  .sent-info span { color:#44ff88; font-weight:700; }
  .card-actions { display:flex; gap:8px; }
  .card-actions + .card-actions { margin-top:8px; }
  .btn { flex:1; border:none; border-radius:10px; padding:11px; font-size:13px; font-weight:700; cursor:pointer; font-family:'Manrope',sans-serif; transition:opacity 0.15s; }
  .btn:active { opacity:0.7; }
  .btn-pay { background:#44ff88; color:#000; }
  .btn-remind { background:#1e1e1e; color:#fff; border:1px solid #333; padding:9px 4px; font-size:12px; }
  .btn-link { background:#13243a; color:#7ab8ff; border:1px solid #1e3a5f; padding:9px 4px; font-size:12px; }
  .btn-dismiss { background:transparent; color:#666; border:1px solid #2a2a2a; padding:6px 10px; font-size:11px; border-radius:8px; font-weight:600; cursor:pointer; font-family:'Manrope',sans-serif; }
  .btn-dismiss:hover { color:#fff; border-color:#444; }
  .empty { text-align:center; padding:60px 20px; color:#444; font-size:14px; }
  .toast { position:fixed; bottom:20px; left:50%; transform:translateX(-50%); background:#44ff88; color:#000; padding:12px 24px; border-radius:30px; font-weight:700; font-size:14px; display:none; z-index:100; white-space:nowrap; }
  .toast.show { display:block; animation:fadeup 0.3s ease; }
  .section-title { font-size:14px; font-weight:700; color:#fff; }
  .section-head { display:flex; justify-content:space-between; align-items:center; margin:20px 0 12px; }
  .all-link { color:#7ab8ff; text-decoration:none; font-size:13px; font-weight:600; }
  .all-link:hover { color:#aad4ff; }
  .resolved-badge { display:inline-block; padding:3px 8px; border-radius:12px; font-size:10px; font-weight:700; background:#0d1a0d; color:#44aa66; border:1px solid #1a3a1a; margin-left:8px; }
  .msg-thumb { display:inline-flex; align-items:center; gap:8px; margin-top:8px; text-decoration:none; }
  .msg-thumb img { width:46px; height:46px; border-radius:6px; border:1px solid #222; object-fit:cover; display:block; }
  .msg-thumb-hint { font-size:11px; color:#44aa66; }
  .msg-link { color:#44ff88; font-size:13px; text-decoration:none; }
  .divider { border:none; border-top:1px solid #222; margin:20px 0; }
  @keyframes fadeup { from{opacity:0;transform:translateX(-50%) translateY(10px)} to{opacity:1;transform:translateX(-50%) translateY(0)} }
</style>
</head>
<body>
<div class="header">
  <div><h1>Оплаты</h1><div class="sub" id="updated">Загрузка...</div></div>
  <div class="header-btns">
    <a class="refresh-btn" href="/chat" style="text-decoration:none; color:#7ab8ff; border-color:#1e3a5f;">💬 Чат</a>
    <button class="refresh-btn" onclick="load()">↻</button>
    <button class="logout-btn" onclick="location='/logout'">Выйти</button>
  </div>
</div>

<div class="stats">
  <div class="stat red"><div class="stat-num" id="cnt-late">—</div><div class="stat-label">Просрочено</div></div>
  <div class="stat yellow"><div class="stat-num" id="cnt-today">—</div><div class="stat-label">Сегодня</div></div>
  <div class="stat green"><div class="stat-num" id="cnt-all">—</div><div class="stat-label">Всего</div></div>
</div>

<div class="filter-tabs">
  <button class="tab active" onclick="setFilter('urgent',this)">Срочные</button>
  <button class="tab" onclick="setFilter('today',this)">Сегодня</button>
  <button class="tab" onclick="setFilter('late',this)">Просрочено</button>
  <button class="tab" onclick="setFilter('future',this)">Будущие</button>
  <button class="tab" onclick="setFilter('all',this)">Все</button>
</div>

<div class="cards" id="cards"><div class="empty">Загрузка...</div></div>

<hr class="divider">

<div class="section-head">
  <div class="section-title">Сообщения от должников</div>
  <a class="all-link" href="/messages">Все сообщения →</a>
</div>
<div class="cards" id="messages"><div class="empty">Пока нет сообщений</div></div>

<div class="toast" id="toast"></div>

<script>
const today = new Date().toISOString().split('T')[0];
let allClients = [];
let currentFilter = 'urgent';
// Локальный список скрытых сообщений — на случай если сервер ещё не успел распространить запись
const dismissedRows = new Set();

function setFilter(f,el) {
  currentFilter = f;
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  el.classList.add('active');
  render();
}

function getStatus(c) {
  if (c.date < today) return 'late';
  if (c.date === today) return 'today';
  return 'future';
}

function render() {
  const filtered = allClients.filter(c => {
    const s = getStatus(c);
    if (currentFilter === 'urgent') return s === 'today' || s === 'late';
    if (currentFilter === 'today') return s === 'today';
    if (currentFilter === 'late') return s === 'late';
    if (currentFilter === 'future') return s === 'future';
    return true;
  });

  const cards = document.getElementById('cards');
  if (!filtered.length) {
    cards.innerHTML = '<div class="empty">Нет клиентов в этой категории ✓</div>';
    return;
  }

  cards.innerHTML = filtered.map(c => {
    const s = getStatus(c);
    const badgeText = s === 'late' ? '⚠ Просрочено' : s === 'today' ? '● Сегодня' : c.date;
    const sentHtml = c.last_sent ? '<div class="sent-info">📤 Отправлено: <span>' + c.last_sent + '</span></div>' : '';
    return '<div class="card" id="card-'+c.row+'">' +
      '<div class="card-top">' +
        '<div><div class="card-name">'+escapeHtml(c.name||c.phone)+'</div><div class="card-phone">'+escapeHtml(c.phone)+'</div></div>' +
        '<span class="badge '+s+'">'+escapeHtml(badgeText)+'</span>' +
      '</div>' +
      '<div class="card-info">' +
        '<div><div class="info-label">Дата</div><div class="info-value">'+escapeHtml(c.date)+'</div></div>' +
        (c.amount ? '<div><div class="info-label">Сумма</div><div class="info-value">'+escapeHtml(c.amount)+' ₽</div></div>' : '') +
      '</div>' +
      sentHtml +
      '<div class="card-actions">' +
        '<button class="btn btn-pay" onclick="markPaid('+c.row+')">✓ Оплатил</button>' +
      '</div>' +
      '<div class="card-actions">' +
        '<button class="btn btn-remind" onclick="sendRemind(event,'+c.row+',1)" title="1-е напоминание">📤 1-е</button>' +
        '<button class="btn btn-remind" onclick="sendRemind(event,'+c.row+',2)" title="2-е напоминание">📤 2-е</button>' +
        '<button class="btn btn-remind" onclick="sendRemind(event,'+c.row+',3)" title="3-е напоминание">📤 3-е</button>' +
        '<button class="btn btn-link" onclick="sendRemind(event,'+c.row+',4)" title="Отправить ссылку на оплату">💳 Ссылка</button>' +
      '</div></div>';
  }).join('');
}

function escapeHtml(s) {
  return String(s || '')
    .replaceAll('&','&amp;')
    .replaceAll('<','&lt;')
    .replaceAll('>','&gt;')
    .replaceAll('"','&quot;')
    .replaceAll("'",'&#039;');
}

async function loadMessages() {
  const r = await fetch('/api/messages');
  let items = await r.json();
  // Дополнительный клиентский фильтр: убираем то, что уже скрыли в этой сессии
  items = items.filter(m => !dismissedRows.has(m._row));
  const box = document.getElementById('messages');

  if (!items.length) {
    box.innerHTML = '<div class="empty">Пока нет сообщений</div>';
    return;
  }

  box.innerHTML = items.map((m, idx) => {
    let body = '';

    if ((m.mime_type || '').startsWith('image/') && m.file_url) {
      const cap = m.message_text ? '📷 ' + escapeHtml(m.message_text) : '📷 Фото / чек';
      body += '<div class="info-label">' + cap + '</div>';
      body += '<a class="msg-thumb" href="' + escapeHtml(m.file_url) + '" target="_blank" rel="noopener">';
      body += '<img src="' + escapeHtml(m.file_url) + '" alt="чек">';
      body += '<div class="msg-thumb-hint">↗ открыть фото</div>';
      body += '</a>';
    } else if (m.file_url) {
      body += '<div class="info-label">📎 ' + escapeHtml(m.file_name || 'Файл') + '</div>';
      body += '<div style="margin-top:8px;"><a class="msg-link" href="' + escapeHtml(m.file_url) + '" target="_blank" rel="noopener">Открыть файл</a></div>';
      if (m.message_text) {
        body += '<div class="info-label" style="margin-top:8px;">' + escapeHtml(m.message_text) + '</div>';
      }
    } else {
      body += '<div class="info-label">' + escapeHtml(m.message_text || '') + '</div>';
    }

    const msgRow = m._row || '';
    const dismissBtn = msgRow ? '<button class="btn-dismiss" onclick="dismissMessage(this,'+msgRow+')">✕ скрыть</button>' : '';

    return '<div class="card" data-msg-row="'+msgRow+'">' +
      '<div class="card-top">' +
        '<div>' +
          '<div class="card-name">' + escapeHtml(m.sender_name || 'Клиент') + '</div>' +
          '<div class="card-phone">' + escapeHtml(m.phone || '') + '</div>' +
        '</div>' +
        '<span class="badge future">' + escapeHtml(m.created_at || '') + '</span>' +
      '</div>' +
      body +
      (dismissBtn ? '<div style="margin-top:12px; text-align:right;">' + dismissBtn + '</div>' : '') +
    '</div>';
  }).join('');
}

async function dismissMessage(btn, msgRow) {
  // Запоминаем сразу — чтобы при любом следующем рендере карточка не вернулась
  dismissedRows.add(msgRow);
  const card = btn.closest('.card');
  if (card) card.classList.add('removing');
  try {
    await fetch('/api/messages/dismiss/' + msgRow, {method:'POST'});
  } catch (e) {
    // Если запись на сервер не прошла — всё равно держим скрытым в этой сессии
    console.warn('dismiss failed', e);
  }
  setTimeout(loadMessages, 300);
}

async function load() {
  document.getElementById('updated').textContent = 'Обновление...';

  const clientsRes = await fetch('/api/clients');
  allClients = await clientsRes.json();

  let late=0, tod=0;
  allClients.forEach(c => {
    const s = getStatus(c);
    if (s==='late') late++;
    else if (s==='today') tod++;
  });

  document.getElementById('cnt-late').textContent = late;
  document.getElementById('cnt-today').textContent = tod;
  document.getElementById('cnt-all').textContent = allClients.length;
  document.getElementById('updated').textContent = 'Обновлено: ' + new Date().toLocaleTimeString('ru');

  render();
  loadMessages();
}

async function markPaid(row) {
  const card = document.getElementById('card-'+row);
  if (card) card.classList.add('removing');
  setTimeout(async () => {
    await fetch('/api/paid/'+row, {method:'POST'});
    showToast('✓ Оплата отмечена. Дата перенесена на следующий месяц.');
    load();
  }, 400);
}

async function sendRemind(event, row, level) {
  const btn = event.target;
  const orig = btn.textContent;
  btn.textContent = '...';
  btn.disabled = true;
  const r = await fetch('/api/remind/'+row+'?level='+level, {method:'POST'});
  if (r.ok) {
    showToast('📤 Напоминание #'+level+' отправлено!');
  } else {
    showToast('❌ Ошибка отправки');
    btn.textContent = orig;
    btn.disabled = false;
  }
  setTimeout(load, 1000);
}

function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(()=>t.classList.remove('show'), 3000);
}

load();
setInterval(load, 60000);
</script>
</body>
</html>
"""

HTML_MESSAGES = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<title>Все сообщения</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700&display=swap');
  * { margin:0; padding:0; box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
  body { font-family:'Manrope',sans-serif; background:#0a0a0a; color:#fff; min-height:100vh; padding:16px; padding-bottom:80px; }
  .header { display:flex; justify-content:space-between; align-items:center; margin-bottom:20px; gap:10px; }
  h1 { font-size:22px; font-weight:700; }
  .sub { color:#666; font-size:12px; margin-top:2px; }
  .header-btns { display:flex; gap:8px; }
  .refresh-btn { background:#1a1a1a; border:1px solid #2a2a2a; color:#fff; border-radius:10px; padding:8px 14px; font-size:13px; font-weight:600; cursor:pointer; font-family:'Manrope',sans-serif; }
  .back-btn { background:#1a1a1a; border:1px solid #2a2a2a; color:#7ab8ff; border-radius:10px; padding:8px 14px; font-size:13px; font-weight:600; cursor:pointer; text-decoration:none; display:inline-block; }
  .filter-tabs { display:flex; gap:8px; margin-bottom:16px; overflow-x:auto; padding-bottom:4px; }
  .filter-tabs::-webkit-scrollbar { display:none; }
  .tab { border:1px solid #2a2a2a; background:#141414; color:#888; border-radius:20px; padding:6px 14px; font-size:12px; font-weight:600; cursor:pointer; white-space:nowrap; font-family:'Manrope',sans-serif; }
  .tab.active { background:#fff; color:#000; border-color:#fff; }
  .cards { display:flex; flex-direction:column; gap:10px; }
  .card { background:#141414; border:1px solid #222; border-radius:14px; padding:16px; transition:all 0.4s ease; overflow:hidden; max-height:1000px; }
  .card.resolved { opacity:0.55; }
  .card.removing { opacity:0; transform:translateX(100px); max-height:0; padding:0; margin:0; }
  .card-top { display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:12px; gap:10px; }
  .card-name { font-size:16px; font-weight:700; word-break:break-word; }
  .card-phone { color:#666; font-size:12px; margin-top:2px; word-break:break-word; }
  .badge { display:inline-block; padding:4px 10px; border-radius:20px; font-size:11px; font-weight:700; white-space:nowrap; background:#0a0a1a; color:#4488ff; }
  .resolved-badge { display:inline-block; padding:3px 8px; border-radius:12px; font-size:10px; font-weight:700; background:#0d1a0d; color:#44aa66; border:1px solid #1a3a1a; margin-left:8px; }
  .info-label { color:#aaa; font-size:13px; line-height:1.45; word-break:break-word; }
  .msg-thumb { display:inline-flex; align-items:center; gap:8px; margin-top:8px; text-decoration:none; }
  .msg-thumb img { width:46px; height:46px; border-radius:6px; border:1px solid #222; object-fit:cover; display:block; }
  .msg-thumb-hint { font-size:11px; color:#44aa66; }
  .msg-link { color:#44ff88; font-size:13px; text-decoration:none; }
  .btn-dismiss { background:transparent; color:#666; border:1px solid #2a2a2a; padding:6px 10px; font-size:11px; border-radius:8px; font-weight:600; cursor:pointer; font-family:'Manrope',sans-serif; }
  .btn-dismiss:hover { color:#fff; border-color:#444; }
  .empty { text-align:center; padding:60px 20px; color:#444; font-size:14px; }
  .count { color:#666; font-size:12px; margin-bottom:12px; }
</style>
</head>
<body>
<div class="header">
  <div><h1>Все сообщения</h1><div class="sub" id="updated">Загрузка...</div></div>
  <div class="header-btns">
    <button class="refresh-btn" onclick="load()">↻</button>
    <a class="back-btn" href="/">← На главную</a>
  </div>
</div>

<div class="filter-tabs">
  <button class="tab active" onclick="setFilter('all',this)">Все</button>
  <button class="tab" onclick="setFilter('unresolved',this)">Активные</button>
  <button class="tab" onclick="setFilter('resolved',this)">Обработанные</button>
</div>

<div class="count" id="count"></div>
<div class="cards" id="messages"><div class="empty">Загрузка...</div></div>

<script>
const dismissedRows = new Set();
let allMessages = [];
let currentFilter = 'all';

function escapeHtml(s) {
  return String(s || '')
    .replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;')
    .replaceAll('"','&quot;').replaceAll("'",'&#039;');
}

function setFilter(f, el) {
  currentFilter = f;
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  el.classList.add('active');
  render();
}

function render() {
  let items = allMessages.filter(m => !dismissedRows.has(m._row));
  if (currentFilter === 'unresolved') items = items.filter(m => !m.resolved_at);
  else if (currentFilter === 'resolved') items = items.filter(m => m.resolved_at);

  document.getElementById('count').textContent = 'Найдено: ' + items.length;

  const box = document.getElementById('messages');
  if (!items.length) { box.innerHTML = '<div class="empty">Нет сообщений</div>'; return; }

  box.innerHTML = items.map(m => {
    let body = '';
    if ((m.mime_type || '').startsWith('image/') && m.file_url) {
      const cap = m.message_text ? '📷 ' + escapeHtml(m.message_text) : '📷 Фото / чек';
      body += '<div class="info-label">' + cap + '</div>';
      body += '<a class="msg-thumb" href="' + escapeHtml(m.file_url) + '" target="_blank" rel="noopener">';
      body += '<img src="' + escapeHtml(m.file_url) + '" alt="чек">';
      body += '<div class="msg-thumb-hint">↗ открыть фото</div></a>';
    } else if (m.file_url) {
      body += '<div class="info-label">📎 ' + escapeHtml(m.file_name || 'Файл') + '</div>';
      body += '<div style="margin-top:8px;"><a class="msg-link" href="' + escapeHtml(m.file_url) + '" target="_blank" rel="noopener">Открыть файл</a></div>';
      if (m.message_text) body += '<div class="info-label" style="margin-top:8px;">' + escapeHtml(m.message_text) + '</div>';
    } else {
      body += '<div class="info-label">' + escapeHtml(m.message_text || '') + '</div>';
    }

    const resolvedMark = m.resolved_at ? '<span class="resolved-badge">✓ обработано</span>' : '';
    const dismissBtn = (!m.resolved_at && m._row)
      ? '<div style="margin-top:12px; text-align:right;"><button class="btn-dismiss" onclick="dismissMessage(this,'+m._row+')">✕ скрыть</button></div>'
      : '';

    return '<div class="card '+(m.resolved_at?'resolved':'')+'" data-msg-row="'+(m._row||'')+'">' +
      '<div class="card-top">' +
        '<div>' +
          '<div class="card-name">' + escapeHtml(m.sender_name || 'Клиент') + resolvedMark + '</div>' +
          '<div class="card-phone">' + escapeHtml(m.phone || '') + '</div>' +
        '</div>' +
        '<span class="badge">' + escapeHtml(m.created_at || '') + '</span>' +
      '</div>' +
      body +
      dismissBtn +
    '</div>';
  }).join('');
}

async function load() {
  document.getElementById('updated').textContent = 'Обновление...';
  const r = await fetch('/api/messages/all');
  allMessages = await r.json();
  document.getElementById('updated').textContent = 'Обновлено: ' + new Date().toLocaleTimeString('ru');
  render();
}

async function dismissMessage(btn, msgRow) {
  dismissedRows.add(msgRow);
  const card = btn.closest('.card');
  if (card) card.classList.add('removing');
  try { await fetch('/api/messages/dismiss/' + msgRow, {method:'POST'}); }
  catch (e) { console.warn('dismiss failed', e); }
  setTimeout(load, 300);
}

load();
setInterval(load, 60000);
</script>
</body>
</html>
"""

HTML_CHAT = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<title>Чат с клиентами</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700&display=swap');
  * { margin:0; padding:0; box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
  body { font-family:'Manrope',sans-serif; background:#0a0a0a; color:#fff; min-height:100vh; padding:16px; padding-bottom:90px; }
  .header { display:flex; justify-content:space-between; align-items:center; margin-bottom:16px; gap:10px; }
  h1 { font-size:22px; font-weight:700; }
  .sub { color:#666; font-size:12px; margin-top:2px; }
  .header-btns { display:flex; gap:8px; }
  .refresh-btn { background:#1a1a1a; border:1px solid #2a2a2a; color:#fff; border-radius:10px; padding:8px 14px; font-size:13px; font-weight:600; cursor:pointer; font-family:'Manrope',sans-serif; }
  .back-btn { background:#1a1a1a; border:1px solid #2a2a2a; color:#7ab8ff; border-radius:10px; padding:8px 14px; font-size:13px; font-weight:600; cursor:pointer; text-decoration:none; display:inline-block; }
  .search { width:100%; background:#141414; border:1px solid #222; border-radius:10px; padding:10px 14px; color:#fff; font-size:14px; font-family:'Manrope',sans-serif; margin-bottom:14px; }
  .empty { text-align:center; padding:60px 20px; color:#444; font-size:14px; }
  .contacts { display:flex; flex-direction:column; gap:8px; }
  .contact { background:#141414; border:1px solid #222; border-radius:14px; padding:14px 16px; cursor:pointer; transition:background 0.15s; }
  .contact:hover { background:#1a1a1a; }
  .contact-top { display:flex; justify-content:space-between; align-items:baseline; margin-bottom:4px; }
  .contact-name { font-size:15px; font-weight:700; }
  .contact-time { font-size:11px; color:#666; }
  .contact-preview { color:#888; font-size:13px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:100%; }
  .contact-preview.out::before { content:"↗ "; color:#44aa66; }

  /* Conversation view */
  .chat-view { display:flex; flex-direction:column; height:calc(100vh - 80px); }
  .chat-head { display:flex; align-items:center; gap:10px; background:#141414; border:1px solid #222; border-radius:14px; padding:12px 14px; margin-bottom:12px; }
  .chat-back { background:transparent; border:none; color:#7ab8ff; font-size:18px; font-weight:700; cursor:pointer; padding:4px 8px; }
  .chat-name { font-size:15px; font-weight:700; }
  .chat-phone { font-size:12px; color:#666; }
  .chat-msgs { flex:1; overflow-y:auto; display:flex; flex-direction:column; gap:10px; padding:6px 2px; }
  .bubble { max-width:85%; padding:10px 14px; border-radius:14px; font-size:14px; line-height:1.4; word-break:break-word; }
  .bubble.in { background:#141414; border:1px solid #222; align-self:flex-start; border-top-left-radius:4px; }
  .bubble.out { background:#13243a; border:1px solid #1e3a5f; color:#cfe1ff; align-self:flex-end; border-top-right-radius:4px; }
  .bubble-time { display:block; font-size:10px; color:#666; margin-top:4px; }
  .bubble-img { max-width:200px; max-height:200px; border-radius:8px; border:1px solid #222; object-fit:cover; display:block; margin-top:6px; }
  .reply-bar { position:fixed; bottom:0; left:0; right:0; background:#0a0a0a; border-top:1px solid #1a1a1a; padding:10px 14px; display:flex; gap:8px; }
  .reply-bar textarea { flex:1; background:#141414; border:1px solid #2a2a2a; border-radius:12px; padding:10px 12px; color:#fff; font-size:14px; font-family:'Manrope',sans-serif; resize:none; max-height:120px; }
  .send-btn { background:#44ff88; color:#000; border:none; border-radius:12px; padding:10px 18px; font-size:14px; font-weight:700; cursor:pointer; font-family:'Manrope',sans-serif; }
  .send-btn:disabled { opacity:0.5; cursor:not-allowed; }
  .toast { position:fixed; bottom:80px; left:50%; transform:translateX(-50%); background:#44ff88; color:#000; padding:12px 24px; border-radius:30px; font-weight:700; font-size:14px; display:none; z-index:100; }
  .toast.show { display:block; }
  .toast.error { background:#ff4444; color:#fff; }
</style>
</head>
<body>

<div id="list-view">
  <div class="header">
    <div><h1>Чат</h1><div class="sub" id="updated">Загрузка...</div></div>
    <div class="header-btns">
      <button class="refresh-btn" onclick="loadContacts()">↻</button>
      <a class="back-btn" href="/">← На главную</a>
    </div>
  </div>
  <input class="search" id="search" placeholder="Поиск по имени или номеру" oninput="renderContacts()">
  <div class="contacts" id="contacts"><div class="empty">Загрузка...</div></div>
</div>

<div id="chat-view" class="chat-view" style="display:none;">
  <div class="chat-head">
    <button class="chat-back" onclick="backToList()">←</button>
    <div>
      <div class="chat-name" id="chat-name">—</div>
      <div class="chat-phone" id="chat-phone">—</div>
    </div>
  </div>
  <div class="chat-msgs" id="chat-msgs"><div class="empty">Загрузка...</div></div>
  <div class="reply-bar">
    <textarea id="reply-text" rows="1" placeholder="Сообщение..." oninput="autoResize(this)"></textarea>
    <button class="send-btn" id="send-btn" onclick="sendReply()">Отправить</button>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
let allContacts = [];
let currentPhone = null;

function escapeHtml(s) {
  return String(s || '')
    .replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;')
    .replaceAll('"','&quot;').replaceAll("'",'&#039;');
}

function showToast(msg, isError) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.toggle('error', !!isError);
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2500);
}

function autoResize(ta) {
  ta.style.height = 'auto';
  ta.style.height = Math.min(ta.scrollHeight, 120) + 'px';
}

async function loadContacts() {
  document.getElementById('updated').textContent = 'Обновление...';
  const r = await fetch('/api/chat/contacts');
  allContacts = await r.json();
  document.getElementById('updated').textContent = 'Контактов: ' + allContacts.length;
  renderContacts();
}

function renderContacts() {
  const q = (document.getElementById('search').value || '').toLowerCase().trim();
  const box = document.getElementById('contacts');
  let items = allContacts;
  if (q) {
    items = items.filter(c =>
      (c.name||'').toLowerCase().includes(q) ||
      (c.client_name||'').toLowerCase().includes(q) ||
      (c.phone||'').includes(q)
    );
  }
  if (!items.length) { box.innerHTML = '<div class="empty">Нет контактов</div>'; return; }
  box.innerHTML = items.map(c => {
    const display = c.client_name || c.name || c.phone;
    const previewClass = c.last_direction === 'out' ? 'contact-preview out' : 'contact-preview';
    return '<div class="contact" onclick="openChat(\\''+c.phone+'\\')">' +
      '<div class="contact-top">' +
        '<div class="contact-name">' + escapeHtml(display) + '</div>' +
        '<div class="contact-time">' + escapeHtml((c.last_at||'').slice(11,16)) + '</div>' +
      '</div>' +
      '<div class="contact-phone" style="font-size:11px;color:#666;margin-bottom:4px;">' + escapeHtml(c.phone) + '</div>' +
      '<div class="'+previewClass+'">' + escapeHtml((c.last_text||'').slice(0,80)) + '</div>' +
    '</div>';
  }).join('');
}

async function openChat(phone) {
  currentPhone = phone;
  document.getElementById('list-view').style.display = 'none';
  document.getElementById('chat-view').style.display = 'flex';
  await loadHistory();
  document.getElementById('reply-text').focus();
}

function backToList() {
  currentPhone = null;
  document.getElementById('chat-view').style.display = 'none';
  document.getElementById('list-view').style.display = 'block';
  loadContacts();
}

async function loadHistory() {
  if (!currentPhone) return;
  const r = await fetch('/api/chat/' + encodeURIComponent(currentPhone));
  const data = await r.json();
  document.getElementById('chat-name').textContent = data.client_name || 'Клиент';
  document.getElementById('chat-phone').textContent = data.phone;
  const box = document.getElementById('chat-msgs');
  if (!data.messages.length) {
    box.innerHTML = '<div class="empty">Нет входящих от клиента</div>';
    return;
  }
  box.innerHTML = data.messages.map(m => {
    const cls = (m.direction === 'out') ? 'bubble out' : 'bubble in';
    let body = '';
    if ((m.mime_type || '').startsWith('image/') && m.file_url) {
      if (m.message_text) body += escapeHtml(m.message_text);
      body += '<a href="'+escapeHtml(m.file_url)+'" target="_blank" rel="noopener"><img class="bubble-img" src="'+escapeHtml(m.file_url)+'" alt="фото"></a>';
    } else if (m.file_url) {
      body += '📎 <a href="'+escapeHtml(m.file_url)+'" target="_blank" rel="noopener" style="color:inherit;">' + escapeHtml(m.file_name||'файл') + '</a>';
      if (m.message_text) body += '<div style="margin-top:6px;">' + escapeHtml(m.message_text) + '</div>';
    } else {
      body += escapeHtml(m.message_text || '');
    }
    return '<div class="'+cls+'">' + body + '<span class="bubble-time">' + escapeHtml(m.created_at||'') + '</span></div>';
  }).join('');
  box.scrollTop = box.scrollHeight;
}

async function sendReply() {
  const ta = document.getElementById('reply-text');
  const btn = document.getElementById('send-btn');
  const text = ta.value.trim();
  if (!text || !currentPhone) return;
  btn.disabled = true;
  btn.textContent = '...';
  try {
    const r = await fetch('/api/chat/' + encodeURIComponent(currentPhone) + '/send', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text})
    });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const data = await r.json();
    if (data.status === 'ok' || data.status === 'sent') {
      ta.value = '';
      autoResize(ta);
      showToast('✓ Отправлено');
      // Подгружаем историю чтобы увидеть наше сообщение
      setTimeout(loadHistory, 800);
    } else {
      showToast('Ошибка: ' + (data.error || 'unknown'), true);
    }
  } catch (e) {
    showToast('Ошибка отправки: ' + e.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Отправить';
  }
}

// Enter — отправить, Shift+Enter — перенос строки
document.getElementById('reply-text').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendReply();
  }
});

loadContacts();
// Авто-обновление списка контактов и активного чата
setInterval(() => { if (currentPhone) loadHistory(); else loadContacts(); }, 60000);
</script>
</body>
</html>
"""

# ============================================================
# УТИЛИТЫ
# ============================================================

def login_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated

# Кэш клиента, книги и листа messages — чтобы не открывать gspread на каждый запрос
_GS_CACHE = {"client": None, "book": None, "messages": None}

# Колонки листа messages (1-based)
MSG_COL = {
    "created_at": 1,
    "phone": 2,
    "sender_name": 3,
    "message_type": 4,
    "message_text": 5,
    "file_url": 6,
    "file_name": 7,
    "mime_type": 8,
    "chat_id": 9,
    "auto_reply_sent_at": 10,
    "resolved_at": 11,
}

def get_client():
    if _GS_CACHE["client"] is None:
        scope = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=scope)
        _GS_CACHE["client"] = gspread.authorize(creds)
    return _GS_CACHE["client"]

def get_book():
    if _GS_CACHE["book"] is None:
        _GS_CACHE["book"] = get_client().open_by_key(SPREADSHEET_ID)
    return _GS_CACHE["book"]

def get_sheet():
    return get_book().sheet1

def get_messages_sheet():
    if _GS_CACHE["messages"] is not None:
        return _GS_CACHE["messages"]
    book = get_book()
    try:
        ws = book.worksheet("messages")
    except gspread.WorksheetNotFound:
        log.info("Лист 'messages' не найден, создаю...")
        ws = book.add_worksheet(title="messages", rows=1000, cols=12)
        ws.append_row([
            "created_at", "phone", "sender_name", "message_type",
            "message_text", "file_url", "file_name", "mime_type",
            "chat_id", "auto_reply_sent_at", "resolved_at", "direction"
        ])
        _GS_CACHE["messages"] = ws
        return ws
    # Ленивая миграция: добавляем столбцы resolved_at и direction если их ещё нет.
    try:
        headers = ws.row_values(1)
        needed = []
        if "resolved_at" not in headers:
            needed.append("resolved_at")
        if "direction" not in headers:
            needed.append("direction")
        if needed:
            target_cols = len(headers) + len(needed)
            try:
                if ws.col_count < target_cols:
                    ws.resize(rows=ws.row_count, cols=target_cols)
            except Exception as e:
                log.warning(f"resize не сработал: {e}")
            for i, name in enumerate(needed):
                log.info(f"Добавляю столбец '{name}' в messages...")
                ws.update_cell(1, len(headers) + 1 + i, name)
    except Exception as e:
        log.warning(f"Не удалось проверить заголовки messages: {e}")
    _GS_CACHE["messages"] = ws
    return ws

def normalize_phone(chat_id):
    return str(chat_id).replace('@c.us', '').replace('@s.whatsapp.net', '')

def store_incoming_message(
    phone,
    sender_name,
    message_type,
    message_text,
    file_url,
    file_name,
    mime_type,
    chat_id,
    auto_reply_sent_at=""
):
    ws = get_messages_sheet()
    ws.append_row([
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        phone,
        sender_name,
        message_type,
        message_text,
        file_url,
        file_name,
        mime_type,
        chat_id,
        auto_reply_sent_at,
        "",      # resolved_at
        "in"     # direction
    ])

def store_outgoing_message(phone, text):
    """Логируем исходящее сообщение в тот же лист messages, чтобы видеть в чате полную переписку."""
    ws = get_messages_sheet()
    ws.append_row([
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        phone,
        "Я",                # sender_name — наш менеджер
        "textMessage",
        text,
        "", "", "",         # file_url, file_name, mime_type
        f"{phone}@c.us",
        "",                 # auto_reply_sent_at
        "",                 # resolved_at
        "out"               # direction
    ])

def send_whatsapp(phone, message):
    url = f"https://api.green-api.com/waInstance{GREEN_API_INSTANCE}/sendMessage/{GREEN_API_TOKEN}"
    data = {"chatId": f"{phone}@c.us", "message": message}
    try:
        requests.post(url, json=data, timeout=10)
        print(f"WhatsApp sent → {phone}")
    except Exception as e:
        print(f"WhatsApp error: {e}")

def reschedule(row_index):
    sheet = get_sheet()
    row = sheet.row_values(row_index)
    date_str = row[3]
    try:
        next_date = (datetime.strptime(date_str, "%Y-%m-%d") + relativedelta(months=1)).strftime("%Y-%m-%d")
    except Exception:
        next_date = date_str
    sheet.update_cell(row_index, 4, next_date)
    sheet.update_cell(row_index, 6, "")
    print(f"Rescheduled row {row_index}: {date_str} → {next_date}")

PAYMENT_LINK = "https://pay.alfabank.ru/sc/pQtIqtQXJkuoauSF"

REMINDER_MESSAGES = {
    1: (
        "Добрый день! Сегодня у вас оплата.\n\n"
        "По номеру карты\n"
        "2200 1520 4571 8817\n"
        "Альфа-банк\n\n"
        "Либо по платежной ссылке\n"
        f"{PAYMENT_LINK}\n\n"
        "После оплаты скиньте чек"
    ),
    2: "Сегодня ждать оплату?",
    3: "Добрый день! подскажите когда ждать оплату?",
    # level=4 — короткий вариант, только ссылка
    4: f"Ссылка для оплаты:\n{PAYMENT_LINK}",
}

def resolve_messages_for_phone(phone):
    """Помечает все непомеченные входящие от данного телефона как resolved_at = now"""
    if not phone:
        return
    ws = get_messages_sheet()
    all_rows = ws.get_all_values()
    if len(all_rows) < 2:
        return
    headers = all_rows[0]
    try:
        phone_idx = headers.index("phone")
    except ValueError:
        return
    try:
        resolved_idx = headers.index("resolved_at")
    except ValueError:
        # Столбца нет — добавим и обновим кэш
        ws.update_cell(1, len(headers) + 1, "resolved_at")
        resolved_idx = len(headers)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    updated = 0
    for i, row_data in enumerate(all_rows[1:], start=2):
        if len(row_data) <= phone_idx:
            continue
        if row_data[phone_idx] != phone:
            continue
        current = row_data[resolved_idx] if len(row_data) > resolved_idx else ""
        if current:
            continue
        ws.update_cell(i, resolved_idx + 1, now)
        updated += 1
    if updated:
        log.info(f"resolve_messages_for_phone({phone}): помечено {updated} сообщений")

# ============================================================
# РОУТЫ
# ============================================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = False
    if request.method == 'POST':
        if request.form.get('password') == PANEL_PASSWORD:
            session['logged_in'] = True
            return redirect('/')
        error = True
    return render_template_string(HTML_LOGIN, error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

@app.route('/')
@login_required
def index():
    return render_template_string(HTML)

@app.route('/messages')
@login_required
def messages_page():
    return render_template_string(HTML_MESSAGES)

@app.route('/chat')
@login_required
def chat_page():
    return render_template_string(HTML_CHAT)

@app.route('/api/clients')
@login_required
def get_clients():
    sheet = get_sheet()
    rows = sheet.get_all_values()
    clients = []
    for i, row in enumerate(rows[1:], start=2):
        if len(row) < 4 or not row[1]:
            continue
        clients.append({
            "row": i,
            "name": row[0],
            "phone": row[1],
            "amount": row[2],
            "date": row[3],
            "status": row[4] if len(row) > 4 else "ojidanie",
            "last_sent": row[5] if len(row) > 5 else ""
        })
    return jsonify(clients)

def _get_debtor_phones():
    """Множество телефонов клиентов, у кого срок оплаты сегодня или раньше (т.е. должников)."""
    sheet = get_sheet()
    today = datetime.today().strftime("%Y-%m-%d")
    phones = set()
    for row in sheet.get_all_values()[1:]:
        if len(row) < 4 or not row[1]:
            continue
        try:
            if row[3] and row[3] <= today:
                phones.add(row[1].strip())
        except Exception:
            continue
    return phones

def _read_messages(only_unresolved=True, debtor_phones=None, limit=50):
    ws = get_messages_sheet()
    all_rows = ws.get_all_values()
    if len(all_rows) < 2:
        return []
    headers = all_rows[0]
    items = []
    for i, row_data in enumerate(all_rows[1:], start=2):
        rec = {h: (row_data[j] if j < len(row_data) else "") for j, h in enumerate(headers)}
        if only_unresolved and rec.get("resolved_at"):
            continue
        if debtor_phones is not None and (rec.get("phone") or "").strip() not in debtor_phones:
            continue
        rec["_row"] = i
        items.append(rec)
    return list(reversed(items))[:limit]

@app.route('/api/messages')
@login_required
def get_messages():
    """Главная страница: только сообщения от должников, не помеченные resolved."""
    debtors = _get_debtor_phones()
    return jsonify(_read_messages(only_unresolved=True, debtor_phones=debtors, limit=50))

@app.route('/api/messages/all')
@login_required
def get_all_messages():
    """Страница 'Все сообщения': весь архив, включая resolved."""
    return jsonify(_read_messages(only_unresolved=False, debtor_phones=None, limit=300))

# ---------- ЧАТ ----------

def _all_chat_rows():
    """Полный сырой список строк из messages, с _row и нормализованной direction."""
    ws = get_messages_sheet()
    all_rows = ws.get_all_values()
    if len(all_rows) < 2:
        return [], []
    headers = all_rows[0]
    items = []
    for i, row_data in enumerate(all_rows[1:], start=2):
        rec = {h: (row_data[j] if j < len(row_data) else "") for j, h in enumerate(headers)}
        # Backward-compat: в старых строках direction пустой → считаем что это входящее
        if not rec.get("direction"):
            rec["direction"] = "in"
        rec["_row"] = i
        items.append(rec)
    return items, headers

def _client_names_by_phone():
    """{ '79161234567': 'Имя клиента' } из основного листа клиентов."""
    sheet = get_sheet()
    out = {}
    for row in sheet.get_all_values()[1:]:
        if len(row) >= 2 and row[1]:
            out[row[1].strip()] = row[0]
    return out

@app.route('/api/chat/contacts')
@login_required
def chat_contacts():
    """Список телефонов с превью последнего сообщения, отсортирован по времени по убыванию."""
    rows, _ = _all_chat_rows()
    by_phone = {}
    for r in rows:
        phone = (r.get("phone") or "").strip()
        if not phone:
            continue
        ts = r.get("created_at") or ""
        prev = by_phone.get(phone)
        if prev is None or ts > prev["last_at"]:
            by_phone[phone] = {
                "phone": phone,
                "name": r.get("sender_name") or phone,
                "last_at": ts,
                "last_text": r.get("message_text") or ("📎 файл" if r.get("file_url") else ""),
                "last_direction": r.get("direction") or "in",
            }
    names = _client_names_by_phone()
    items = []
    for phone, c in by_phone.items():
        c["client_name"] = names.get(phone, "")
        items.append(c)
    items.sort(key=lambda c: c["last_at"], reverse=True)
    return jsonify(items)

@app.route('/api/chat/<phone>')
@login_required
def chat_history(phone):
    """Последние 3 ВХОДЯЩИХ сообщения от клиента — этого достаточно чтобы понять, что отвечать."""
    rows, _ = _all_chat_rows()
    items = [r for r in rows if (r.get("phone") or "").strip() == phone.strip()]
    incoming = [r for r in items if r.get("direction") == "in"]
    incoming.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    last3 = incoming[:3]
    last3.sort(key=lambda r: r.get("created_at") or "")
    return jsonify({
        "phone": phone,
        "client_name": _client_names_by_phone().get(phone.strip(), ""),
        "messages": last3,
    })

@app.route('/api/chat/<phone>/send', methods=['POST'])
@login_required
def chat_send(phone):
    """Отправить произвольный текст клиенту через Green API + залогировать в messages."""
    data = request.get_json(silent=True) or {}
    text = (data.get('text') or '').strip()
    if not text:
        return jsonify({"status": "error", "error": "empty text"}), 400
    send_whatsapp(phone, text)
    try:
        store_outgoing_message(phone, text)
    except Exception as e:
        log.error(f"store_outgoing_message failed: {e}")
        return jsonify({"status": "sent", "logged": False, "error": str(e)})
    return jsonify({"status": "ok"})

@app.route('/api/messages/dismiss/<int:msg_row>', methods=['POST'])
@login_required
def dismiss_message(msg_row):
    """Скрыть одно конкретное сообщение из ленты (без отметки оплаты)"""
    ws = get_messages_sheet()
    headers = ws.row_values(1)
    try:
        resolved_idx = headers.index("resolved_at") + 1
    except ValueError:
        ws.update_cell(1, len(headers) + 1, "resolved_at")
        resolved_idx = len(headers) + 1
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ws.update_cell(msg_row, resolved_idx, now)
    return jsonify({"status": "ok"})

@app.route('/api/paid/<int:row>', methods=['POST'])
@login_required
def mark_paid(row):
    sheet = get_sheet()
    r = sheet.row_values(row)
    phone = r[1] if len(r) > 1 else ""
    reschedule(row)
    if phone:
        try:
            resolve_messages_for_phone(phone)
        except Exception as e:
            log.error(f"resolve_messages_for_phone failed: {e}")
    return jsonify({"status": "ok"})

@app.route('/api/remind/<int:row>', methods=['POST'])
@login_required
def send_remind(row):
    try:
        level = int(request.args.get('level', 1))
    except (TypeError, ValueError):
        level = 1
    if level not in REMINDER_MESSAGES:
        level = 1
    sheet = get_sheet()
    r = sheet.row_values(row)
    if len(r) < 2 or not r[1]:
        return jsonify({"status": "error", "error": "phone not found"}), 400
    phone = r[1]
    send_whatsapp(phone, REMINDER_MESSAGES[level])
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    sheet.update_cell(row, 6, now)
    log.info(f"Manual remind level={level} → {phone} (row {row})")
    return jsonify({"status": "ok", "level": level})

@app.route('/webhook', methods=['GET'])
def webhook_check():
    # Чтобы можно было открыть в браузере и убедиться, что endpoint живой
    return jsonify({"status": "ok", "hint": "POST here from Green API"})

@app.route('/webhook', methods=['POST'])
def webhook():
    # Главное правило: webhook ВСЕГДА возвращает 200, даже при внутренней ошибке.
    # Иначе Green API считает webhook битым и со временем выключает доставку.
    try:
        data = request.get_json(silent=True) or {}
        type_webhook = data.get('typeWebhook', '')
        log.info(f"Webhook ← typeWebhook={type_webhook}")

        if type_webhook != 'incomingMessageReceived':
            return jsonify({"status": "ignored", "type": type_webhook})

        sender = data.get('senderData', {}) or {}
        message_data = data.get('messageData', {}) or {}

        chat_id = sender.get('chatId', '')
        sender_name = sender.get('senderName') or sender.get('chatName') or 'Клиент'
        phone = normalize_phone(chat_id)

        type_message = message_data.get('typeMessage', '')
        message_text = ''
        file_url = ''
        file_name = ''
        mime_type = ''

        if type_message == 'textMessage':
            message_text = (message_data.get('textMessageData', {}) or {}).get('textMessage', '')
        elif type_message == 'extendedTextMessage':
            message_text = (message_data.get('extendedTextMessageData', {}) or {}).get('text', '')
        elif type_message in ('imageMessage', 'documentMessage', 'videoMessage', 'audioMessage'):
            file_data = message_data.get('fileMessageData', {}) or {}
            file_url = file_data.get('downloadUrl', '')
            file_name = file_data.get('fileName', '')
            mime_type = file_data.get('mimeType', '')
            message_text = file_data.get('caption', '')
        else:
            message_text = f"[{type_message or 'message'}]"

        log.info(f"  от {phone} ({sender_name}) тип={type_message} текст={message_text[:80]!r} файл={file_name!r}")

        try:
            store_incoming_message(
                phone=phone,
                sender_name=sender_name,
                message_type=type_message,
                message_text=message_text,
                file_url=file_url,
                file_name=file_name,
                mime_type=mime_type,
                chat_id=chat_id,
                auto_reply_sent_at=""
            )
        except Exception as e:
            # Не валим webhook, если Sheets временно недоступен — просто логируем
            log.error(f"  store_incoming_message FAILED: {e}")
            log.error(traceback.format_exc())
            return jsonify({"status": "error", "saved": False, "error": str(e)})

        return jsonify({"status": "ok"})

    except Exception as e:
        log.error(f"Webhook ОШИБКА: {e}")
        log.error(traceback.format_exc())
        # Всё равно 200, чтобы Green API не отключил webhook
        return jsonify({"status": "error", "error": str(e)})

if __name__ == "__main__":
    print("🚀 Панель запущена!")
    print("   Открой: http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
