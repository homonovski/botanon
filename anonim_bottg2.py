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


# ========== АДМИН-КЛАВИАТУРА ==========
def admin_keyboard():
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)

    chats_btn = telebot.types.InlineKeyboardButton("Чаты", callback_data="admin_chats")
    stats_btn = telebot.types.InlineKeyboardButton("Статистика", callback_data="admin_stats")
    blocked_btn = telebot.types.InlineKeyboardButton("Заблокированные", callback_data="admin_blocked")
    refresh_btn = telebot.types.InlineKeyboardButton("Обновить", callback_data="admin_refresh")

    markup.add(chats_btn, stats_btn)
    markup.add(blocked_btn, refresh_btn)
    return markup


def chat_list_keyboard():
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    seen = set()
    for user1, user2 in list(active_chats.items()):
        if user1 not in seen and user2 not in seen:
            seen.add(user1)
            seen.add(user2)
            btn = telebot.types.InlineKeyboardButton(
                f"Чат {user1} <-> {user2}",
                callback_data=f"chat_{user1}"
            )
            markup.add(btn)
    markup.add(telebot.types.InlineKeyboardButton("Назад", callback_data="admin_menu"))
    return markup


def chat_actions_keyboard(user_id, partner_id):
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    watching = "Слежу" if user_id in moderator_watching else "Следить"
    markup.add(
        telebot.types.InlineKeyboardButton(f"{watching}", callback_data=f"toggle_watch_{user_id}"),
        telebot.types.InlineKeyboardButton("Заблокировать", callback_data=f"block_{user_id}")
    )
    markup.add(
        telebot.types.InlineKeyboardButton("Назад к чатам", callback_data="admin_chats")
    )
    return markup


def blocked_list_keyboard():
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    for uid in list(blocked_users):
        markup.add(telebot.types.InlineKeyboardButton(
            f"Разблокировать {uid}", callback_data=f"unblock_{uid}"
        ))
    if not blocked_users:
        markup.add(telebot.types.InlineKeyboardButton("Нет заблокированных", callback_data="none"))
    markup.add(telebot.types.InlineKeyboardButton("Назад", callback_data="admin_menu"))
    return markup


# ========== АДМИН-КОМАНДЫ ==========
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.chat.id != ADMIN_ID:
        bot.send_message(message.chat.id, "Нет прав.")
        return

    bot.send_message(ADMIN_ID,
        f"Админ-панель\n\n"
        f"Активных чатов: {len(active_chats) // 2}\n"
        f"В очереди: {len(waiting_users)}\n"
        f"Заблокировано: {len(blocked_users)}",
        reply_markup=admin_keyboard())


@bot.callback_query_handler(func=lambda call: call.message.chat.id == ADMIN_ID)
def admin_callback(call):
    data = call.data

    if data == "admin_menu":
        bot.edit_message_text(
            f"Админ-панель\n\n"
            f"Активных чатов: {len(active_chats) // 2}\n"
            f"В очереди: {len(waiting_users)}\n"
            f"Заблокировано: {len(blocked_users)}",
            ADMIN_ID, call.message.id,
            reply_markup=admin_keyboard())

    elif data == "admin_chats":
        if not active_chats:
            bot.answer_callback_query(call.id, "Нет активных чатов", show_alert=True)
            return
        bot.edit_message_text("Выберите чат:", ADMIN_ID, call.message.id,
                              reply_markup=chat_list_keyboard())

    elif data.startswith("chat_"):
        user_id = int(data.split("_")[1])
        if user_id not in active_chats:
            bot.answer_callback_query(call.id, "Чат уже завершён", show_alert=True)
            bot.edit_message_text("Админ-панель", ADMIN_ID, call.message.id,
                                  reply_markup=admin_keyboard())
            return
        partner_id = active_chats[user_id]
        status = "Слежу" if user_id in moderator_watching else "Не слежу"
        bot.edit_message_text(
            f"Чат: {user_id} <-> {partner_id}\nСтатус: {status}",
            ADMIN_ID, call.message.id,
            reply_markup=chat_actions_keyboard(user_id, partner_id))

    elif data.startswith("toggle_watch_"):
        user_id = int(data.split("_")[2])
        if user_id in active_chats:
            if user_id in moderator_watching:
                del moderator_watching[user_id]
                save_data()
                bot.answer_callback_query(call.id, "Слежка отключена")
            else:
                moderator_watching[user_id] = active_chats[user_id]
                save_data()
                bot.answer_callback_query(call.id, "Слежу за чатом")
        else:
            bot.answer_callback_query(call.id, "Чат не найден", show_alert=True)
            bot.edit_message_text("Админ-панель", ADMIN_ID, call.message.id,
                                  reply_markup=admin_keyboard())
            return
        # Обновляем сообщение
        if user_id in active_chats:
            partner_id = active_chats[user_id]
            status = "Слежу" if user_id in moderator_watching else "Не слежу"
            bot.edit_message_text(
                f"Чат: {user_id} <-> {partner_id}\nСтатус: {status}",
                ADMIN_ID, call.message.id,
                reply_markup=chat_actions_keyboard(user_id, partner_id))

    elif data.startswith("block_"):
        user_id = int(data.split("_")[1])
        if user_id not in active_chats:
            bot.answer_callback_query(call.id, "Пользователь уже не в чате", show_alert=True)
            return
        partner_id = active_chats[user_id]
        blocked_users.add(user_id)
        send_safe(partner_id, "Собеседник заблокирован администратором. Нажмите /find.")
        stop_chat_for_user(user_id)
        if user_id in waiting_users:
            waiting_users.remove(user_id)
        save_data()
        bot.answer_callback_query(call.id, f"Пользователь {user_id} заблокирован")
        bot.edit_message_text("Админ-панель", ADMIN_ID, call.message.id,
                              reply_markup=admin_keyboard())

    elif data == "admin_stats":
        total = len({u for pair in active_chats.items() for u in pair}) + len(waiting_users)
        bot.answer_callback_query(call.id, show_alert=True)
        bot.send_message(ADMIN_ID,
            f"Статистика:\n"
            f"Активных чатов: {len(active_chats) // 2}\n"
            f"В очереди: {len(waiting_users)}\n"
            f"Заблокировано: {len(blocked_users)}\n"
            f"Уникальных пользователей сейчас: {total}")

    elif data == "admin_blocked":
        bot.edit_message_text("Заблокированные пользователи:", ADMIN_ID, call.message.id,
                              reply_markup=blocked_list_keyboard())

    elif data.startswith("unblock_"):
        user_id = int(data.split("_")[1])
        if user_id in blocked_users:
            blocked_users.discard(user_id)
            save_data()
            bot.answer_callback_query(call.id, f"Пользователь {user_id} разблокирован")
            bot.edit_message_text("Заблокированные пользователи:", ADMIN_ID, call.message.id,
                                  reply_markup=blocked_list_keyboard())
        else:
            bot.answer_callback_query(call.id, "Уже не заблокирован", show_alert=True)

    elif data == "admin_refresh":
        bot.edit_message_text(
            f"Админ-панель\n\n"
            f"Активных чатов: {len(active_chats) // 2}\n"
            f"В очереди: {len(waiting_users)}\n"
            f"Заблокировано: {len(blocked_users)}",
            ADMIN_ID, call.message.id,
            reply_markup=admin_keyboard())

    bot.answer_callback_query(call.id)


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
