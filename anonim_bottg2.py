import telebot
import logging
import json
import os
import time
from collections import deque

# ========== НАСТРОЙКИ ==========
TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID'))
DATA_FILE = "bot_data.json"
ANTI_FLOOD_SECONDS = 1  # Секунд между сообщениями
# ================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
bot = telebot.TeleBot(TOKEN)

waiting_users = deque()
active_chats = {}
moderator_watching = {}
blocked_users = set()
last_message_time = {}


# ========== ЗАГРУЗКА / СОХРАНЕНИЕ ==========
def load_data():
    global blocked_users, waiting_users, active_chats, moderator_watching
    if not os.path.exists(DATA_FILE):
        return
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        blocked_users = set(data.get("blocked_users", []))
        waiting_users = deque(data.get("waiting_users", []))
        active_chats = {int(k): int(v) for k, v in data.get("active_chats", {}).items()}
        moderator_watching = {int(k): int(v) for k, v in data.get("moderator_watching", {}).items()}
        logging.info("Данные загружены")
    except Exception as e:
        logging.error(f"Ошибка загрузки данных: {e}")


def save_data():
    try:
        data = {
            "blocked_users": list(blocked_users),
            "waiting_users": list(waiting_users),
            "active_chats": {str(k): str(v) for k, v in active_chats.items()},
            "moderator_watching": {str(k): str(v) for k, v in moderator_watching.items()},
        }
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Ошибка сохранения данных: {e}")


# ========== АНТИ-ФЛУД ==========
def is_flooding(user_id):
    now = time.time()
    last = last_message_time.get(user_id, 0)
    if now - last < ANTI_FLOOD_SECONDS:
        return True
    last_message_time[user_id] = now
    return False


# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def stop_chat_for_user(user_id):
    if user_id in active_chats:
        partner_id = active_chats[user_id]
        del active_chats[user_id]
        if partner_id in active_chats:
            del active_chats[partner_id]
    if user_id in moderator_watching:
        del moderator_watching[user_id]
    save_data()


def send_safe(chat_id, text, **kwargs):
    try:
        bot.send_message(chat_id, text, **kwargs)
    except Exception as e:
        logging.error(f"Ошибка отправки сообщения {chat_id}: {e}")


# ========== КОМАНДЫ ДЛЯ ВСЕХ ==========
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.chat.id
    if user_id in blocked_users:
        bot.send_message(user_id, "Вы заблокированы.")
        return
    bot.send_message(user_id,
        "Анонимный чат бот\n\n"
        "/find - найти собеседника\n"
        "/stop - завершить диалог\n"
        "/report - пожаловаться на собеседника\n"
        "Просто отправляйте сообщения, и они будут доставлены анонимно.")


@bot.message_handler(commands=['find'])
def find_partner(message):
    user_id = message.chat.id
    if user_id in blocked_users:
        bot.send_message(user_id, "Вы заблокированы.")
        return
    if user_id in active_chats:
        bot.send_message(user_id, "Вы уже в чате. Используйте /stop.")
        return
    if user_id in waiting_users:
        bot.send_message(user_id, "Вы уже в поиске.")
        return

    if waiting_users:
        partner_id = waiting_users.popleft()
        active_chats[user_id] = partner_id
        active_chats[partner_id] = user_id
        bot.send_message(user_id, "Собеседник найден! Для выхода /stop.")
        bot.send_message(partner_id, "Собеседник найден! Для выхода /stop.")
        save_data()
        logging.info(f"Чат создан между {user_id} и {partner_id}")
    else:
        waiting_users.append(user_id)
        save_data()
        bot.send_message(user_id, "Ищем собеседника...")


@bot.message_handler(commands=['stop'])
def stop_chat(message):
    user_id = message.chat.id
    if user_id in waiting_users:
        waiting_users.remove(user_id)
        save_data()
        bot.send_message(user_id, "Поиск отменён.")
        return

    if user_id in active_chats:
        partner_id = active_chats[user_id]
        stop_chat_for_user(user_id)
        bot.send_message(user_id, "Вы вышли из чата.")
        send_safe(partner_id, "Собеседник покинул чат. Используйте /find.")
        logging.info(f"Чат завершён между {user_id} и {partner_id}")
        return

    bot.send_message(user_id, "Вы не в чате. Используйте /find.")


@bot.message_handler(commands=['report'])
def report_user(message):
    user_id = message.chat.id
    if user_id not in active_chats:
        bot.send_message(user_id, "Вы не в чате.")
        return
    partner_id = active_chats[user_id]
    send_safe(ADMIN_ID, f"Жалоба: пользователь {user_id} пожаловался на {partner_id}")
    bot.send_message(user_id, "Жалоба отправлена администратору.")


# ========== АДМИН-КОМАНДЫ ==========
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.chat.id != ADMIN_ID:
        bot.send_message(message.chat.id, "Нет прав.")
        return

    text = "Активные чаты:\n"
    if not active_chats:
        text += "Нет активных чатов.\n"
    else:
        seen = set()
        for user1, user2 in active_chats.items():
            if user1 not in seen and user2 not in seen:
                seen.add(user1)
                seen.add(user2)
                text += f"Чат: {user1} <-> {user2}\n"

    text += f"\nОжидают в очереди: {len(waiting_users)}"
    text += f"\nЗаблокировано: {len(blocked_users)}"
    text += "\n\n/watch <id> - следить за чатом"
    text += "\n/unwatch <id> - не следить"
    text += "\n/block <id> [причина] - заблокировать"
    text += "\n/unblock <id> - разблокировать"
    text += "\n/stats - статистика"

    bot.send_message(ADMIN_ID, text)


@bot.message_handler(commands=['watch'])
def watch_chat(message):
    if message.chat.id != ADMIN_ID:
        return
    try:
        user_id = int(message.text.split()[1])
    except Exception:
        bot.send_message(ADMIN_ID, "Использование: /watch <user_id>")
        return

    if user_id not in active_chats:
        bot.send_message(ADMIN_ID, f"Пользователь {user_id} не в чате.")
        return

    partner_id = active_chats[user_id]
    moderator_watching[user_id] = partner_id
    save_data()
    bot.send_message(ADMIN_ID, f"Слежу за чатом {user_id} <-> {partner_id}")


@bot.message_handler(commands=['unwatch'])
def unwatch_chat(message):
    if message.chat.id != ADMIN_ID:
        return
    try:
        user_id = int(message.text.split()[1])
    except Exception:
        bot.send_message(ADMIN_ID, "Использование: /unwatch <user_id>")
        return

    if user_id in moderator_watching:
        del moderator_watching[user_id]
        save_data()
        bot.send_message(ADMIN_ID, f"Больше не слежу за {user_id}.")
    else:
        bot.send_message(ADMIN_ID, f"Вы не следили за {user_id}.")


@bot.message_handler(commands=['block'])
def block_user(message):
    if message.chat.id != ADMIN_ID:
        return
    try:
        args = message.text.split(maxsplit=2)
        user_id = int(args[1])
        reason = args[2] if len(args) > 2 else "Без причины"
    except Exception:
        bot.send_message(ADMIN_ID, "Использование: /block <user_id> [причина]")
        return

    blocked_users.add(user_id)
    if user_id in active_chats:
        partner_id = active_chats[user_id]
        send_safe(partner_id, "Собеседник заблокирован администратором. Нажмите /find.")
        stop_chat_for_user(user_id)
    if user_id in waiting_users:
        waiting_users.remove(user_id)
    save_data()
    bot.send_message(ADMIN_ID, f"Пользователь {user_id} заблокирован. Причина: {reason}")


@bot.message_handler(commands=['unblock'])
def unblock_user(message):
    if message.chat.id != ADMIN_ID:
        return
    try:
        user_id = int(message.text.split()[1])
    except Exception:
        bot.send_message(ADMIN_ID, "Использование: /unblock <user_id>")
        return

    if user_id in blocked_users:
        blocked_users.discard(user_id)
        save_data()
        bot.send_message(ADMIN_ID, f"Пользователь {user_id} разблокирован.")
    else:
        bot.send_message(ADMIN_ID, f"Пользователь {user_id} не был заблокирован.")


@bot.message_handler(commands=['stats'])
def stats(message):
    if message.chat.id != ADMIN_ID:
        return
    total_users = len({u for pair in active_chats.items() for u in pair}) + len(waiting_users)
    bot.send_message(ADMIN_ID,
        f"Статистика:\n"
        f"Активных чатов: {len(active_chats) // 2}\n"
        f"В очереди: {len(waiting_users)}\n"
        f"Заблокировано: {len(blocked_users)}\n"
        f"Уникальных пользователей сейчас: {total_users}")


# ========== ПЕРЕСЫЛКА СООБЩЕНИЙ ==========
@bot.message_handler(func=lambda message: True, content_types=[
    'text', 'photo', 'video', 'document', 'audio', 'voice', 'sticker', 'animation'
])
def handle_message(message):
    user_id = message.chat.id

    if message.content_type == 'text' and message.text.startswith('/'):
        return

    if user_id in blocked_users:
        bot.send_message(user_id, "Вы заблокированы.")
        return

    if is_flooding(user_id):
        return

    if user_id in active_chats:
        partner_id = active_chats[user_id]
        try:
            bot.copy_message(partner_id, user_id, message.id)

            for watched_user, watched_partner in moderator_watching.items():
                if user_id in (watched_user, watched_partner):
                    bot.copy_message(ADMIN_ID, user_id, message.id)
                    break
        except Exception as e:
            bot.send_message(user_id, f"Ошибка при отправке: {e}")
            logging.error(f"Ошибка пересылки от {user_id} к {partner_id}: {e}")
    else:
        bot.send_message(user_id, "Вы не в чате. Нажмите /find.")


# ========== ЗАПУСК ==========
if __name__ == "__main__":
    load_data()
    print("Бот запущен...")
    bot.infinity_polling()
