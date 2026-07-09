import telebot
import logging
import json
import os
from collections import deque

# ========== НАСТРОЙКИ ==========
TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID'))
DATA_FILE = "bot_data.json"

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


# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def stop_chat_for_user(user_id):
    if user_id in active_chats:
        partner_id = active_chats[user_id]
        del active_chats[user_id]
        if partner_id in active_chats:
            del active_chats[partner_id]
        notify_admin_chat_stop(user_id, partner_id)
    if user_id in moderator_watching:
        del moderator_watching[user_id]
    save_data()


def send_safe(chat_id, text, **kwargs):
    try:
        bot.send_message(chat_id, text, **kwargs)
    except Exception as e:
        logging.error(f"Ошибка отправки сообщения {chat_id}: {e}")


REPORT_REASONS = ["Оскорбления", "Спам", "Неприличный контент", "Угрозы", "Выдача себя за другого", "Другое"]

BUTTON_FIND = "🔍 Найти собеседника"
BUTTON_NEXT = "⏭ Дальше"
BUTTON_STOP = "🚪 Выйти"
BUTTON_REPORT = "⚠ Пожаловаться"
BUTTON_CANCEL = "❌ Отменить поиск"
BUTTON_TEXTS = {BUTTON_FIND, BUTTON_NEXT, BUTTON_STOP, BUTTON_REPORT, BUTTON_CANCEL}


def user_reply_main():
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(telebot.types.KeyboardButton(BUTTON_FIND))
    return markup


def user_reply_chat():
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(telebot.types.KeyboardButton(BUTTON_NEXT),
               telebot.types.KeyboardButton(BUTTON_STOP))
    markup.row(telebot.types.KeyboardButton(BUTTON_REPORT))
    return markup


def user_reply_queue():
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(telebot.types.KeyboardButton(BUTTON_CANCEL))
    return markup


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
        "Просто отправляйте сообщения, и они будут доставлены анонимно.",
        reply_markup=user_reply_main())


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

    find_partner_logic(user_id)


@bot.message_handler(commands=['stop'])
def stop_chat(message):
    user_id = message.chat.id
    if user_id in waiting_users:
        waiting_users.remove(user_id)
        save_data()
        bot.send_message(user_id, "Поиск отменён.", reply_markup=user_reply_main())
        return

    if user_id in active_chats:
        partner_id = active_chats[user_id]
        stop_chat_for_user(user_id)
        bot.send_message(user_id, "Вы вышли из чата.", reply_markup=user_reply_main())
        send_safe(partner_id, "Собеседник покинул чат. Используйте /find.",
                  reply_markup=user_reply_main())
        logging.info(f"Чат завершён между {user_id} и {partner_id}")
        return

    bot.send_message(user_id, "Вы не в чате. Используйте /find.")


@bot.message_handler(commands=['next'])
def next_partner(message):
    user_id = message.chat.id
    if user_id in blocked_users:
        bot.send_message(user_id, "Вы заблокированы.")
        return
    if user_id in waiting_users:
        bot.send_message(user_id, "Вы уже в поиске.")
        return
    if user_id in active_chats:
        partner_id = active_chats[user_id]
        stop_chat_for_user(user_id)
        send_safe(partner_id, "Собеседник нажал /next. Используйте /find.",
                  reply_markup=user_reply_main())

    find_partner_logic(user_id)


@bot.message_handler(commands=['report'])
def report_user(message):
    user_id = message.chat.id
    if user_id not in active_chats:
        bot.send_message(user_id, "Вы не в чате.")
        return
    partner_id = active_chats[user_id]
    bot.send_message(user_id, "Выберите причину жалобы:",
                     reply_markup=report_reasons_keyboard(partner_id))


def notify_admin_chat_start(user_id, partner_id):
    for watched_user, watched_partner in moderator_watching.items():
        if user_id == watched_user:
            bot.send_message(ADMIN_ID,
                f"🔔 Пользователь {user_id} начал чат с {partner_id}")
        elif partner_id == watched_user:
            bot.send_message(ADMIN_ID,
                f"🔔 Пользователь {partner_id} начал чат с {user_id}")


def notify_admin_chat_stop(user_id, partner_id):
    for watched_user in moderator_watching:
        if user_id == watched_user:
            bot.send_message(ADMIN_ID,
                f"🔔 Пользователь {user_id} завершил чат с {partner_id}")
        elif partner_id == watched_user:
            bot.send_message(ADMIN_ID,
                f"🔔 Пользователь {partner_id} завершил чат с {user_id}")


def find_partner_logic(user_id):
    if waiting_users:
        partner_id = waiting_users.popleft()
        active_chats[user_id] = partner_id
        active_chats[partner_id] = user_id
        bot.send_message(user_id, "Собеседник найден!",
                         reply_markup=user_reply_chat())
        bot.send_message(partner_id, "Собеседник найден!",
                         reply_markup=user_reply_chat())
        notify_admin_chat_start(user_id, partner_id)
        save_data()
        logging.info(f"Чат создан между {user_id} и {partner_id}")
    else:
        waiting_users.append(user_id)
        save_data()
        bot.send_message(user_id, "Ищем собеседника...",
                         reply_markup=user_reply_queue())


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


def report_admin_keyboard(user_id, partner_id):
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        telebot.types.InlineKeyboardButton("🔍 Следить", callback_data=f"watch_report_{partner_id}"),
        telebot.types.InlineKeyboardButton("⛔ Блок", callback_data=f"block_{partner_id}")
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
@bot.message_handler(commands=['shutdown'])
def shutdown(message):
    if message.chat.id != ADMIN_ID:
        return

    bot.send_message(ADMIN_ID, "Оповещаю пользователей о технических работах...")

    notified = set()
    for user1, user2 in list(active_chats.items()):
        if user1 not in notified:
            send_safe(user1, "Бот уходит на технические работы. Чат завершён.")
            notified.add(user1)
        if user2 not in notified:
            send_safe(user2, "Бот уходит на технические работы. Чат завершён.")
            notified.add(user2)

    queue_count = len(waiting_users)
    for uid in list(waiting_users):
        send_safe(uid, "Бот уходит на технические работы. Поиск отменён.")

    waiting_users.clear()
    active_chats.clear()
    moderator_watching.clear()
    save_data()

    bot.send_message(ADMIN_ID,
        f"Уведомлено {len(notified) + queue_count} пользователей. Бот остановлен.")
    bot.stop_polling()


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

    elif data.startswith("watch_report_"):
        user_id = int(data.split("_")[2])
        if user_id not in active_chats:
            bot.answer_callback_query(call.id, "Пользователь уже не в чате", show_alert=True)
            return
        partner_id = active_chats[user_id]
        moderator_watching[user_id] = partner_id
        save_data()
        bot.answer_callback_query(call.id, "Слежу за чатом")
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


# ========== ВЫБОР ПРИЧИНЫ ЖАЛОБЫ ==========
@bot.callback_query_handler(func=lambda call: call.data.startswith("r_") and call.message.chat.id != ADMIN_ID)
def report_reason_callback(call):
    user_id = call.message.chat.id
    parts = call.data.split("_")
    partner_id = int(parts[1])
    reason_idx = int(parts[2])
    reason = REPORT_REASONS[reason_idx]

    bot.send_message(ADMIN_ID,
        f"Жалоба от {user_id} на {partner_id}:\nПричина: {reason}",
        reply_markup=report_admin_keyboard(user_id, partner_id))
    bot.edit_message_text("Жалоба отправлена.", user_id, call.message.id)
    bot.answer_callback_query(call.id, "Жалоба отправлена администратору.")


# ========== ОБРАБОТКА КНОПОК РЕПЛАЙ-КЛАВИАТУРЫ ==========
@bot.message_handler(func=lambda message: message.text in BUTTON_TEXTS)
def handle_reply_button(message):
    user_id = message.chat.id
    text = message.text

    if user_id in blocked_users:
        bot.send_message(user_id, "Вы заблокированы.")
        return

    if text == BUTTON_FIND:
        if user_id in active_chats:
            bot.send_message(user_id, "Вы уже в чате.")
            return
        if user_id in waiting_users:
            bot.send_message(user_id, "Вы уже в поиске.")
            return
        find_partner_logic(user_id)

    elif text == BUTTON_NEXT:
        if user_id not in active_chats:
            bot.send_message(user_id, "Вы не в чате.")
            return
        partner_id = active_chats[user_id]
        stop_chat_for_user(user_id)
        send_safe(partner_id, "Собеседник нажал /next. Используйте /find.",
                  reply_markup=user_reply_main())
        bot.send_message(user_id, "Ищем следующего...",
                         reply_markup=user_reply_main())
        find_partner_logic(user_id)

    elif text in (BUTTON_STOP, BUTTON_CANCEL):
        if user_id in waiting_users:
            waiting_users.remove(user_id)
            save_data()
            bot.send_message(user_id, "Поиск отменён.", reply_markup=user_reply_main())
            return
        if user_id in active_chats:
            partner_id = active_chats[user_id]
            stop_chat_for_user(user_id)
            bot.send_message(user_id, "Вы вышли из чата.", reply_markup=user_reply_main())
            send_safe(partner_id, "Собеседник покинул чат. Используйте /find.",
                      reply_markup=user_reply_main())
            logging.info(f"Чат завершён между {user_id} и {partner_id}")
            return
        bot.send_message(user_id, "Вы не в чате.")

    elif text == BUTTON_REPORT:
        if user_id not in active_chats:
            bot.send_message(user_id, "Вы не в чате.")
            return
        partner_id = active_chats[user_id]
        bot.send_message(user_id, "Выберите причину жалобы:",
                         reply_markup=report_reasons_keyboard(partner_id))


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

    if user_id in active_chats:
        partner_id = active_chats[user_id]
        try:
            bot.send_chat_action(partner_id, "typing")
            bot.copy_message(partner_id, user_id, message.id)

            for watched_user, watched_partner in moderator_watching.items():
                if user_id == watched_user:
                    other_id = watched_partner
                elif user_id == watched_partner:
                    other_id = watched_user
                else:
                    continue

                if message.content_type == 'text':
                    bot.send_message(ADMIN_ID,
                        f"[{user_id} -> {other_id}]: {message.text}")
                else:
                    bot.send_message(ADMIN_ID,
                        f"📎 {message.content_type} от {user_id} для {other_id}")
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
