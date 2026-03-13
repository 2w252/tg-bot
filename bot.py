import logging
import sys
import os
import string
import random
import sqlite3
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

print("🤖 Бот запускается...")

# 🔥 УСТАНАВЛИВАЕМ БИБЛИОТЕКИ ПРАВИЛЬНО
try:
    # Для python-telegram-bot 20.x
    from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
    from telegram.ext import (
        Application,
        CommandHandler,
        MessageHandler,
        filters,
        ContextTypes,
        CallbackQueryHandler,
        ConversationHandler
    )
    print("✅ Библиотеки загружены успешно")
except ImportError as e:
    print(f"❌ Ошибка загрузки библиотек: {e}")
    print("📦 Установите библиотеку: pip install python-telegram-bot==20.7")
    sys.exit(1)

# Конфигурация
BOT_TOKEN = ""
ADMIN_ID = 
CHANNEL_USERNAME = ''
CHANNEL_LINK = ''
REVIEWS_CHANNEL = ''
REVIEWS_LINK = ''
SUPPORT_USERNAME = ''

# 🔥 НАСТРОЙКИ
AUTO_DELETE_MESSAGES = True
MESSAGE_LIFETIME = 300

# 🔥 ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ДЛЯ ОТЗЫВОВ
awaiting_reviews = {}
user_reviews = {}
user_sessions = {}

# 🔥 БАЗА ДАННЫХ - SQLite
class Database:
    def __init__(self, db_path='bot_database.db'):
        self.db_path = db_path
        self.init_database()

    def init_database(self):
        """Инициализация базы данных"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Таблица пользователей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                registration_date TEXT,
                balance INTEGER DEFAULT 0,
                total_spent INTEGER DEFAULT 0,
                last_activity TEXT
            )
        ''')
        
        # Таблица заявок
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                game_type TEXT,
                product_type TEXT,
                tariff_type TEXT,
                price INTEGER,
                status TEXT DEFAULT 'pending',
                order_date TEXT,
                key_sent TEXT,
                admin_id INTEGER,
                completed_date TEXT,
                review_sent BOOLEAN DEFAULT FALSE
            )
        ''')
        
        # Таблица отзывов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                order_id INTEGER,
                review_text TEXT,
                rating INTEGER,
                review_date TEXT,
                published BOOLEAN DEFAULT FALSE
            )
        ''')
        
        conn.commit()
        conn.close()
        print("✅ База данных инициализирована")

    def get_user(self, user_id: int) -> Optional[Dict]:
        """Получить данные пользователя"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        user = cursor.fetchone()
        conn.close()
        
        if user:
            return {
                'user_id': user[0],
                'username': user[1],
                'full_name': user[2],
                'registration_date': user[3],
                'balance': user[4],
                'total_spent': user[5],
                'last_activity': user[6]
            }
        return None

    def create_user(self, user_id: int, username: str, full_name: str):
        """Создать нового пользователя"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO users 
                (user_id, username, full_name, registration_date, last_activity)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, username, full_name, datetime.now().isoformat(), datetime.now().isoformat()))
            
            conn.commit()
            logger.info(f"✅ Создан пользователь {user_id}")
        except Exception as e:
            logger.error(f"❌ Ошибка создания пользователя: {e}")
        finally:
            conn.close()

    def update_user_activity(self, user_id: int):
        """Обновить время последней активности"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('UPDATE users SET last_activity = ? WHERE user_id = ?', 
                     (datetime.now().isoformat(), user_id))
        conn.commit()
        conn.close()

    def create_order(self, user_id: int, game_type: str, product_type: str, tariff_type: str, price: int) -> int:
        """Создать заявку на покупку"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO orders (user_id, game_type, product_type, tariff_type, price, order_date)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, game_type, product_type, tariff_type, price, datetime.now().isoformat()))
        
        order_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return order_id

    def get_pending_orders(self) -> List[Dict]:
        """Получить ожидающие заявки"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT o.*, u.full_name, u.username 
            FROM orders o 
            JOIN users u ON o.user_id = u.user_id 
            WHERE o.status = 'pending'
            ORDER BY o.order_date
        ''')
        
        orders = cursor.fetchall()
        columns = ['id', 'user_id', 'game_type', 'product_type', 'tariff_type', 'price', 
                  'status', 'order_date', 'key_sent', 'admin_id', 'completed_date', 'full_name', 'username']
        
        conn.close()
        return [dict(zip(columns, order)) for order in orders]

    def complete_order(self, order_id: int, admin_id: int, key_sent: str):
        """Завершить заявку (выдать ключ)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE orders 
            SET status = 'completed', admin_id = ?, key_sent = ?, completed_date = ?
            WHERE id = ?
        ''', (admin_id, key_sent, datetime.now().isoformat(), order_id))
        
        # Обновляем статистику потраченных средств
        cursor.execute('SELECT user_id, price FROM orders WHERE id = ?', (order_id,))
        order = cursor.fetchone()
        if order:
            user_id, price = order
            cursor.execute('UPDATE users SET total_spent = total_spent + ? WHERE user_id = ?', (price, user_id))
        
        conn.commit()
        conn.close()

    def get_user_orders(self, user_id: int) -> List[Dict]:
        """Получить заказы пользователя"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM orders WHERE user_id = ? ORDER BY order_date DESC', (user_id,))
        orders = cursor.fetchall()
        columns = ['id', 'user_id', 'game_type', 'product_type', 'tariff_type', 'price', 
                  'status', 'order_date', 'key_sent', 'admin_id', 'completed_date']
        
        conn.close()
        return [dict(zip(columns, order)) for order in orders]

    def get_all_users(self) -> List[Dict]:
        """Получить всех пользователей"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM users ORDER BY registration_date DESC')
        users = cursor.fetchall()
        columns = ['user_id', 'username', 'full_name', 'registration_date', 'balance', 'total_spent', 'last_activity']
        
        conn.close()
        return [dict(zip(columns, user)) for user in users]

    def add_review(self, user_id: int, order_id: int, review_text: str, rating: int):
        """Добавить отзыв в базу"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO reviews (user_id, order_id, review_text, rating, review_date)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, order_id, review_text, rating, datetime.now().isoformat()))
        
        cursor.execute('UPDATE orders SET review_sent = TRUE WHERE id = ?', (order_id,))
        
        conn.commit()
        conn.close()

    def update_user_balance(self, user_id: int, amount: int):
        """Обновить баланс пользователя"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
        conn.commit()
        conn.close()

# Инициализация базы данных
db = Database()

# 🔥 СИСТЕМА ПРОДУКТОВ
PRODUCTS = {
    'standoff2': {
        'plutonium': {
            'name': 'Plutonium no root',
            'description': "🌟 **PLUTONIUM NO ROOT ДЛЯ STANDOFF 2**\n\nМощный чит без root прав",
            'tariffs': {
                '1_month': {'name': '1 месяц', 'price': 500, 'days': 30},
                '3_months': {'name': '3 месяца', 'price': 1000, 'days': 90},
            }
        }
    },
    'pubgmobile': {
        'pulsex': {
            'name': 'Pulsex 4.0', 
            'description': "🎯 **Pulsex 4.0 для PUBG Mobile**\n\nИнновационный чит",
            'tariffs': {
                '1_week': {'name': '1 неделя', 'price': 400, 'days': 7},
                '1_month': {'name': '1 месяц', 'price': 800, 'days': 30},
            }
        }
    },
    'freecheats': {
        'free': {
            'name': '🆓 БЕСПЛАТНЫЕ ЧИТЫ',
            'description': "🎁 **БЕСПЛАТНЫЕ ЧИТЫ ДЛЯ ВСЕХ ИГР**\n\nБесплатные варианты для тестирования",
            'tariffs': {
                'free': {'name': '🆓 Бесплатные читы', 'price': 0, 'days': 9999}
            }
        }
    }
}

# 🔥 СИСТЕМА ПЛАТЕЖЕЙ
PAYMENT_SYSTEMS = {
    'sberbank': {
        'name': 'Сбербанк',
        'details': '2202 2084 2967 0459',
        'instructions': 'Оплата через Сбербанк Онлайн'
    },
    'tinkoff': {
        'name': 'Тинькофф', 
        'details': '5536 9138 3947 4532',
        'instructions': 'Оплата через Тинькофф приложение'
    }
}

def generate_license_key(product_type: str) -> str:
    """Генерация лицензионного ключа"""
    prefix = product_type.upper()[:3]
    random_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))
    return f"GRAPE-{prefix}-{random_part}"

async def is_user_subscribed(user_id: int, bot) -> bool:
    """Проверка подписки пользователя на канал"""
    try:
        member = await bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Ошибка проверки подписки: {e}")
        return True

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

# 🔥 ГЛАВНАЯ КЛАВИАТУРА
def get_main_keyboard():
    """Главная клавиатура"""
    buttons = [
        [KeyboardButton("🛒 Купить ключ"), KeyboardButton("📦 Мои покупки")],
        [KeyboardButton("👨‍💻 Поддержка"), KeyboardButton("🔗 Наш канал")],
        [KeyboardButton("📝 ОТЗЫВЫ"), KeyboardButton("🆓 Бесплатные читы")]
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

def get_games_keyboard():
    """Клавиатура выбора игр"""
    keyboard = [
        [InlineKeyboardButton("🎯 Standoff 2", callback_data="game_standoff2")],
        [InlineKeyboardButton("🎖️ PUBG Mobile", callback_data="game_pubgmobile")],
        [InlineKeyboardButton("🆓 Бесплатные читы", callback_data="game_freecheats")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_products_keyboard(game_type: str):
    """Клавиатура выбора продуктов"""
    keyboard = []
    products = PRODUCTS.get(game_type, {})
    
    for product_id, product_info in products.items():
        keyboard.append([InlineKeyboardButton(
            product_info['name'], 
            callback_data=f"product_{game_type}_{product_id}"
        )])
    
    keyboard.append([InlineKeyboardButton("⬅️ Назад к играм", callback_data="back_to_games")])
    return InlineKeyboardMarkup(keyboard)

def get_tariffs_keyboard(game_type: str, product_type: str):
    """Клавиатура выбора тарифов"""
    keyboard = []
    products = PRODUCTS.get(game_type, {})
    product_info = products.get(product_type, {})
    tariffs = product_info.get('tariffs', {})
    
    for tariff_id, tariff in tariffs.items():
        keyboard.append([InlineKeyboardButton(
            f"{tariff['name']} - {tariff['price']} руб.", 
            callback_data=f"buy_{game_type}_{product_type}_{tariff_id}"
        )])
    
    keyboard.append([InlineKeyboardButton("⬅️ Назад к продуктам", callback_data=f"back_to_products_{game_type}")])
    return InlineKeyboardMarkup(keyboard)

def get_payment_keyboard():
    """Клавиатура выбора способа оплаты"""
    keyboard = []
    for system_id, system in PAYMENT_SYSTEMS.items():
        keyboard.append([InlineKeyboardButton(
            f"💳 {system['name']}", 
            callback_data=f"payment_{system_id}"
        )])
    
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel_payment")])
    return InlineKeyboardMarkup(keyboard)

def get_review_keyboard():
    """Клавиатура для оценки отзыва"""
    keyboard = [
        [
            InlineKeyboardButton("⭐", callback_data="review_1"),
            InlineKeyboardButton("⭐⭐", callback_data="review_2"),
            InlineKeyboardButton("⭐⭐⭐", callback_data="review_3"),
            InlineKeyboardButton("⭐⭐⭐⭐", callback_data="review_4"),
            InlineKeyboardButton("⭐⭐⭐⭐⭐", callback_data="review_5")
        ],
        [InlineKeyboardButton("❌ Пропустить отзыв", callback_data="review_skip")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_admin_keyboard():
    """Админ клавиатура"""
    return ReplyKeyboardMarkup([
        [KeyboardButton("📊 Статистика"), KeyboardButton("⏳ Ожидающие заявки")],
        [KeyboardButton("👥 Все пользователи")],
        [KeyboardButton("🏠 Главное меню")]
    ], resize_keyboard=True)

# 🔥 СИСТЕМА ОТЗЫВОВ
async def request_review(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, order_id: int, product_name: str):
    """Запросить отзыв у пользователя после получения ключа"""
    review_request_text = f"""
🎉 **Спасибо за покупку!** 

Вы получили доступ к **{product_name}**

📝 **Пожалуйста, оставьте отзыв о нашем продукте!**

Ваш отзыв поможет другим пользователям и даст вам +50 руб. на баланс!

👇 **Оцените наш продукт:**
    """
    
    awaiting_reviews[user_id] = {
        'order_id': order_id,
        'product_name': product_name
    }
    
    await context.bot.send_message(
        chat_id=user_id,
        text=review_request_text,
        reply_markup=get_review_keyboard(),
        parse_mode='Markdown'
    )

async def handle_review_rating(update: Update, context: ContextTypes.DEFAULT_TYPE, rating: int):
    """Обработка выбора рейтинга для отзыва"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id not in awaiting_reviews:
        await query.answer("❌ Время для отзыва истекло", show_alert=True)
        return
    
    if user_id not in user_reviews:
        user_reviews[user_id] = {}
    
    user_reviews[user_id]['rating'] = rating
    
    review_text_request = f"""
⭐ **Спасибо за оценку {rating}/5!**

📝 **Теперь напишите текстовый отзыв:**
Расскажите о вашем опыте использования, что понравилось, что можно улучшить.

💬 **Просто напишите ваш отзыв в чат**

💰 **За полный отзыв (оценка + текст) вы получите +50 руб. на баланс!**

❌ _Если не хотите писать текст, нажмите "Пропустить отзыв"_
    """
    
    await query.edit_message_text(
        review_text_request,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Пропустить отзыв", callback_data="review_skip")]
        ])
    )

async def handle_text_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстового отзыва от пользователя"""
    user_id = update.effective_user.id
    review_text = update.message.text
    
    if user_id not in awaiting_reviews:
        return
    
    if user_id not in user_reviews or 'rating' not in user_reviews[user_id]:
        await update.message.reply_text("❌ Пожалуйста, сначала выберите оценку для отзыва")
        return
    
    user_reviews[user_id]['text'] = review_text
    user_reviews[user_id]['full_name'] = update.effective_user.full_name
    
    await publish_review_to_channel(update, context, user_id)
    
    if user_id in awaiting_reviews:
        del awaiting_reviews[user_id]

async def publish_review_to_channel(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Опубликовать отзыв в канал"""
    if user_id not in user_reviews:
        return
    
    review_data = user_reviews[user_id]
    order_data = awaiting_reviews.get(user_id, {})
    
    stars = "⭐" * review_data['rating']
    review_message = f"""
📝 **НОВЫЙ ОТЗЫВ** {stars}

🎮 **Продукт:** {order_data.get('product_name', 'Неизвестно')}
👤 **Пользователь:** {review_data.get('full_name', 'Аноним')}
⭐ **Оценка:** {review_data['rating']}/5

💬 **Отзыв:**
{review_data.get('text', 'Без текста')}

🕒 _{datetime.now().strftime('%d.%m.%Y %H:%M')}_
    """
    
    try:
        await context.bot.send_message(
            chat_id=REVIEWS_CHANNEL,
            text=review_message
        )
        
        db.add_review(
            user_id=user_id,
            order_id=order_data.get('order_id'),
            review_text=review_data.get('text', ''),
            rating=review_data['rating']
        )
        
        # Начисляем бонус пользователю
        db.update_user_balance(user_id, 50)
        
        user_data = db.get_user(user_id)
        new_balance = user_data.get('balance', 0) + 50 if user_data else 50
        
        success_message = f"""
✅ **Спасибо за ваш отзыв!**

💰 **Вам начислено +50 руб. на баланс!**

📢 **Ваш отзыв опубликован в нашем канале:**
{REVIEWS_LINK}

💎 **Теперь ваш баланс:** {new_balance} руб.
        """
        
        await context.bot.send_message(
            chat_id=user_id,
            text=success_message
        )
        
        if user_id in user_reviews:
            del user_reviews[user_id]
        
    except Exception as e:
        logger.error(f"Ошибка публикации отзыва: {e}")
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ Произошла ошибка при публикации отзыва. Попробуйте позже."
        )

async def handle_review_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка пропуска отзыва"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id in awaiting_reviews:
        del awaiting_reviews[user_id]
    
    if user_id in user_reviews:
        del user_reviews[user_id]
    
    await query.edit_message_text(
        "✅ **Спасибо за покупку!**\n\n"
        "Если у вас возникнут вопросы, обращайтесь в поддержку."
    )

# 🔥 ОСНОВНЫЕ ФУНКЦИИ БОТА
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user = update.effective_user
    logger.info(f"👤 Новый пользователь: {user.id} - {user.full_name}")
    
    # Создание/обновление пользователя
    user_data = db.get_user(user.id)
    if not user_data:
        db.create_user(user.id, user.username, user.full_name)
    
    welcome_text = f"""
🎮 **Добро пожаловать в GrapeCheat!** 🚀

💼 **Ваш профиль:**
• 🆔 ID: `{user.id}`
• 💰 Баланс: {user_data.get('balance', 0) if user_data else 0} руб.

🌐 **Полезные ссылки:**
• 📢 Канал: {CHANNEL_LINK}
• 📝 Отзывы: {REVIEWS_LINK}
• 👨‍💻 Поддержка: {SUPPORT_USERNAME}

🎁 **Получите +50 руб. за каждый отзыв после покупки!**
    """
    
    await update.message.reply_text(welcome_text, reply_markup=get_main_keyboard())

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    user = update.effective_user
    text = update.message.text
    
    logger.info(f"📨 Сообщение от {user.id}: {text}")
    
    # Обновление активности
    db.update_user_activity(user.id)
    
    # 🔥 ПРОВЕРКА: ЕСЛИ ПОЛЬЗОВАТЕЛЬ ОЖИДАЕТСЯ ОТЗЫВ
    if user.id in awaiting_reviews:
        await handle_text_review(update, context)
        return
    
    # Обработка команд
    if text == "🛒 Купить ключ":
        await show_games(update)
    
    elif text == "📦 Мои покупки":
        await show_user_orders(update, user.id)
    
    elif text == "👨‍💻 Поддержка":
        await update.message.reply_text(f"👨‍💻 **Поддержка:** {SUPPORT_USERNAME}")
    
    elif text == "🔗 Наш канал":
        await update.message.reply_text(f"📢 **Наш канал:** {CHANNEL_LINK}")
    
    elif text == "📝 ОТЗЫВЫ":
        await show_reviews_info(update)
    
    elif text == "🆓 Бесплатные читы":
        await show_free_cheats(update)
    
    # Команды администратора
    elif is_admin(user.id):
        if text == "👑 АДМИН ПАНЕЛЬ":
            await show_admin_panel(update)
        elif text == "📊 Статистика":
            await show_admin_stats(update)
        elif text == "⏳ Ожидающие заявки":
            await show_pending_orders(update)
        elif text == "👥 Все пользователи":
            await show_all_users(update)
        elif text == "🏠 Главное меню":
            await update.message.reply_text("Главное меню", reply_markup=get_main_keyboard())

async def show_reviews_info(update: Update):
    """Показать информацию об отзывах"""
    reviews_text = f"""
📝 **СИСТЕМА ОТЗЫВОВ**

💬 **Наши отзывы:** {REVIEWS_LINK}

⭐ **Оставляйте отзывы и получайте бонусы:**
• После каждой покупки - +50 руб. за отзыв

💰 **Как оставить отзыв:**
1. Совершите покупку в нашем магазине
2. После получения ключа бот автоматически запросит отзыв
3. Оцените продукт и напишите текст отзыва
4. Получите +50 руб. на баланс!

📢 **Все отзывы публикуются здесь:**
{REVIEWS_LINK}
    """
    
    if update.message:
        await update.message.reply_text(reviews_text)
    else:
        await update.callback_query.edit_message_text(reviews_text)

async def show_user_orders(update: Update, user_id: int):
    """Показать историю заказов пользователя"""
    orders = db.get_user_orders(user_id)
    
    if not orders:
        text = "📦 **У вас пока нет покупок**\n\nПерейдите в магазин чтобы совершить первую покупку!"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🛒 Магазин", callback_data="go_to_shop")]])
    else:
        text = "📦 **Ваши покупки:**\n\n"
        for order in orders[:10]:
            status_icon = "✅" if order['status'] == 'completed' else "⏳"
            status_text = "Выполнен" if order['status'] == 'completed' else "Ожидает"
            
            game_type = order['game_type']
            product_type = order['product_type']
            products = PRODUCTS.get(game_type, {})
            product_info = products.get(product_type, {})
            product_name = product_info.get('name', 'Продукт')
            
            text += f"{status_icon} **{product_name}**\n"
            text += f"   🎮 {game_type} | 💰 {order['price']} руб.\n"
            text += f"   📅 {order['order_date'][:10]} | {status_text}\n"
            if order['key_sent']:
                text += f"   🔑 Ключ: `{order['key_sent']}`\n"
            text += "━━━━━━━━━━━━━━\n"
    
    if update.message:
        await update.message.reply_text(text)
    else:
        await update.callback_query.edit_message_text(text)

async def show_free_cheats(update: Update):
    """Показать бесплатные читы"""
    text = """
🎁 **БЕСПЛАТНЫЕ ЧИТЫ ДЛЯ ВСЕХ ИГР**

👇 **Доступные варианты:**

• **Clumsy Netwing** - полная версия для Standoff 2
• **КФГ К Clumsy** - оптимизированные конфигурации

⚠️ **Внимание:** Для работы требуется подписка на наш канал!

📢 **Канал:** https://t.me/IMPULSENONROOT

👇 **Выберите нужный вариант:**
    """
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Clumsy Netwing", callback_data="free_clumsy")],
        [InlineKeyboardButton("КФГ К Clumsy", callback_data="free_cfg")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main")]
    ])
    
    if update.message:
        await update.message.reply_text(text, reply_markup=keyboard)
    else:
        await update.callback_query.edit_message_text(text, reply_markup=keyboard)

async def show_games(update: Update):
    """Показать список игр"""
    games_text = """
🎮 **ВЫБЕРИТЕ ИГРУ**

Доступные категории:

• 🎯 **Standoff 2** - лучшие читы для Standoff 2
• 🎖️ **PUBG Mobile** - премиум читы для PUBG
• 🆓 **Бесплатные читы** - бесплатные варианты для всех

👇 **Выберите категорию:**
    """
    
    if update.message:
        await update.message.reply_text(games_text, reply_markup=get_games_keyboard())
    else:
        await update.callback_query.edit_message_text(games_text, reply_markup=get_games_keyboard())

async def show_admin_panel(update: Update):
    """Показать админ панель"""
    admin_text = """
👑 **ПАНЕЛЬ АДМИНИСТРАТОРА**

🛠️ **Доступные функции:**

• 📊 **Статистика** - общая статистика бота
• ⏳ **Ожидающие заявки** - управление заказами
• 👥 **Все пользователи** - список пользователей
    """
    await update.message.reply_text(admin_text, reply_markup=get_admin_keyboard())

async def show_admin_stats(update: Update):
    """Показать статистику админа"""
    users = db.get_all_users()
    total_users = len(users)
    total_revenue = sum(u['total_spent'] for u in users)
    pending_orders = len(db.get_pending_orders())
    
    stats_text = f"""
📊 **СТАТИСТИКА БОТА**

👥 **Пользователи:**
• Всего пользователей: {total_users}
• Новых за сегодня: 0

💰 **Финансы:**
• Общий доход: {total_revenue} руб.
• За сегодня: 0 руб.

🛒 **Заказы:**
• Ожидают обработки: {pending_orders}
• Выполнено: {len([u for u in users if u['total_spent'] > 0])}
    """
    await update.message.reply_text(stats_text)

async def show_pending_orders(update: Update):
    """Показать ожидающие заявки (админ)"""
    orders = db.get_pending_orders()
    
    if not orders:
        await update.message.reply_text("✅ **Нет ожидающих заявок**")
        return
    
    text = "⏳ **ОЖИДАЮЩИЕ ЗАЯВКИ:**\n\n"
    for order in orders:
        game_type = order['game_type']
        product_type = order['product_type']
        products = PRODUCTS.get(game_type, {})
        product_info = products.get(product_type, {})
        product_name = product_info.get('name', 'Продукт')
        
        text += f"**#{order['id']}** - {order['full_name']}\n"
        text += f"🆔 `{order['user_id']}` | 💰 {order['price']} руб.\n"
        text += f"🎮 {game_type} - {product_name}\n"
        text += f"📅 {order['order_date'][:16]}\n"
        text += f"💬 Выдать ключ: `/send {order['user_id']} КЛЮЧ`\n\n"
        text += "━━━━━━━━━━━━━━\n\n"
    
    await update.message.reply_text(text)

async def show_all_users(update: Update):
    """Показать всех пользователей (админ)"""
    users = db.get_all_users()
    
    if not users:
        await update.message.reply_text("📭 **В базе нет пользователей**")
        return
    
    text = "👥 **ВСЕ ПОЛЬЗОВАТЕЛИ:**\n\n"
    for user in users[:15]:
        reg_date = user['registration_date'][:10] if user['registration_date'] else "N/A"
        
        text += f"**{user['full_name']}**\n"
        text += f"🆔 `{user['user_id']}`\n"
        text += f"💰 {user['total_spent']} руб. | 📅 {reg_date}\n"
        text += "━━━━━━━━━━━━━━\n"
    
    text += f"\n📊 **Всего пользователей:** {len(users)}"
    
    await update.message.reply_text(text)

# 🔥 CALLBACK ОБРАБОТЧИКИ
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик callback запросов"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    
    logger.info(f"🔍 Callback data: {data} от пользователя {user_id}")
    
    # Обновление активности
    db.update_user_activity(user_id)
    
    # 🔥 ОБРАБОТКА ОТЗЫВОВ
    if data.startswith('review_'):
        if data == 'review_skip':
            await handle_review_skip(update, context)
            return
        elif data in ['review_1', 'review_2', 'review_3', 'review_4', 'review_5']:
            rating = int(data.split('_')[1])
            await handle_review_rating(update, context, rating)
            return
    
    # 🔥 ОБРАБОТКА БЕСПЛАТНЫХ ЧИТОВ
    if data in ['free_clumsy', 'free_cfg']:
        await handle_free_cheat_request(update, context, data)
        return
    
    # Обработка различных callback данных
    if data == "check_subscription":
        await query.answer("Проверка подписки...")
    
    elif data == "go_to_shop":
        await show_games(update)
    
    elif data == "back_to_main":
        await query.edit_message_text(
            "Главное меню",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛒 Магазин", callback_data="go_to_shop")]])
        )
    
    elif data == "back_to_games":
        await show_games(update)
    
    elif data.startswith('back_to_products_'):
        game_type = data.replace('back_to_products_', '')
        await show_products_for_game(update, game_type)
    
    elif data.startswith('game_'):
        game_type = data.replace('game_', '')
        await show_products_for_game(update, game_type)
    
    elif data.startswith('product_'):
        parts = data.split('_')
        if len(parts) >= 3:
            game_type = parts[1]
            product_type = parts[2]
            await show_product_description(update, game_type, product_type)
    
    elif data.startswith('buy_'):
        parts = data.split('_')
        if len(parts) >= 4:
            game_type = parts[1]
            product_type = parts[2]
            tariff_type = parts[3]
            await process_purchase(update, context, game_type, product_type, tariff_type)
    
    elif data.startswith('payment_'):
        system_id = data.replace('payment_', '')
        await handle_payment_selection(update, context, system_id)
    
    elif data == "send_screenshot":
        await query.edit_message_text(
            "📸 **Отправьте скриншот чека**\n\n"
            "Пожалуйста, отправьте скриншот или фото чека об оплате."
        )
    
    elif data == "cancel_payment":
        await query.edit_message_text(
            "❌ **Оплата отменена**\n\n"
            "Вы можете вернуться в магазин и выбрать другой товар."
        )
        if user_id in user_sessions:
            del user_sessions[user_id]

async def show_products_for_game(update: Update, game_type: str):
    """Показать продукты для выбранной игры"""
    game_names = {
        'standoff2': 'Standoff 2',
        'pubgmobile': 'PUBG Mobile', 
        'freecheats': 'Бесплатные читы'
    }
    game_name = game_names.get(game_type, 'Игра')
    
    text = f"🛍️ **Выберите продукт для {game_name}:**"
    
    await update.callback_query.edit_message_text(text, reply_markup=get_products_keyboard(game_type))

async def show_product_description(update: Update, game_type: str, product_type: str):
    """Показать описание продукта"""
    products = PRODUCTS.get(game_type, {})
    product_info = products.get(product_type, {})
    
    if not product_info:
        await update.callback_query.edit_message_text("❌ Продукт не найден")
        return
    
    description = product_info.get('description', '❌ Описание продукта отсутствует.')
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➡️ Выбрать тариф", callback_data=f"tariffs_{game_type}_{product_type}")],
        [InlineKeyboardButton("⬅️ Назад к продуктам", callback_data=f"back_to_products_{game_type}")]
    ])
    
    await update.callback_query.edit_message_text(description, reply_markup=keyboard)

async def show_tariffs_for_product(update: Update, game_type: str, product_type: str):
    """Показать тарифы для продукта"""
    products = PRODUCTS.get(game_type, {})
    product_info = products.get(product_type, {})
    
    if not product_info:
        await update.callback_query.edit_message_text("❌ Продукт не найден")
        return
    
    product_name = product_info.get('name', 'Продукт')
    tariffs = product_info.get('tariffs', {})
    
    text = f"🎯 **Выберите тариф для {product_name}:**\n\n"
    
    for tariff_id, tariff in tariffs.items():
        text += f"📦 **{tariff['name']}**\n"
        text += f"   💰 {tariff['price']} руб. | ⏱️ {tariff['days']} дней\n"
        text += "   ━━━━━━━━━━━━━━\n"
    
    await update.callback_query.edit_message_text(text, reply_markup=get_tariffs_keyboard(game_type, product_type))

async def process_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE, game_type: str, product_type: str, tariff_type: str):
    """Обработка покупки"""
    products = PRODUCTS.get(game_type, {})
    product_info = products.get(product_type, {})
    tariffs = product_info.get('tariffs', {})
    tariff = tariffs.get(tariff_type)
    
    if not tariff:
        await update.callback_query.edit_message_text("❌ Тариф не найден")
        return
    
    # Сохраняем данные в сессию
    user_id = update.callback_query.from_user.id
    user_sessions[user_id] = {
        'game_type': game_type,
        'product_type': product_type,
        'tariff_type': tariff_type,
        'tariff_name': tariff['name'],
        'price': tariff['price'],
        'days': tariff['days']
    }
    
    text = f"""
💳 **ОФОРМЛЕНИЕ ПОКУПКИ**

🎮 **Игра:** {game_type}
🛍️ **Продукт:** {product_info['name']}
📦 **Тариф:** {tariff['name']}
💰 **Сумма:** {tariff['price']} руб.
⏱️ **Срок:** {tariff['days']} дней

👇 **Выберите способ оплаты:**
    """
    
    await update.callback_query.edit_message_text(text, reply_markup=get_payment_keyboard())

async def handle_payment_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, system_id: str):
    """Обработка выбора способа оплата"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id not in user_sessions:
        await query.edit_message_text("❌ Сессия устарела. Начните покупку заново.")
        return
    
    session = user_sessions[user_id]
    system = PAYMENT_SYSTEMS[system_id]
    
    payment_text = f"""
💳 **ОПЛАТА ЧЕРЕЗ {system['name']}**

📋 **Реквизиты:**
`{system['details']}`

📝 **Инструкция:**
{system['instructions']}

💰 **Сумма к оплате:** {session['price']} руб.

⚠️ **ВАЖНО:**
• Обязательно сохраните скриншот чека
• Указывайте в комментарии ваш ID: `{user_id}`
• После оплаты отправьте скриншот в этот чат

⏰ **Срок обработки:** до 15 минут
    """
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📸 Отправить скриншот", callback_data="send_screenshot")],
        [InlineKeyboardButton("❌ Отменить покупку", callback_data="cancel_payment")]
    ])
    
    await query.edit_message_text(payment_text, reply_markup=keyboard)

async def handle_payment_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка скриншотов оплаты"""
    user_id = update.effective_user.id
    
    # Проверяем, есть ли активная сессия покупки
    if user_id not in user_sessions:
        await update.message.reply_text(
            "❌ **Сначала выберите товар для покупки**\n\n"
            "Перейдите в магазин и выберите нужный продукт."
        )
        return
    
    session = user_sessions[user_id]
    
    # Получаем название продукта
    products = PRODUCTS.get(session['game_type'], {})
    product_info = products.get(session['product_type'], {})
    product_name = product_info.get('name', 'Продукт')
    
    # Создаем заказ
    order_id = db.create_order(
        user_id, 
        session['game_type'], 
        session['product_type'], 
        session['tariff_type'], 
        session['price']
    )
    
    # Уведомление администратору
    admin_text = f"""
🆕 **НОВАЯ ЗАЯВКА НА ОПЛАТУ** #{order_id}

👤 **Пользователь:** {update.effective_user.full_name}
🆔 **ID:** `{user_id}`
📧 **Username:** @{update.effective_user.username or 'N/A'}

🎮 **Детали заказа:**
• Игра: {session['game_type']}
• Продукт: {product_name}
• Тариф: {session['tariff_name']}
• Сумма: {session['price']} руб.
• Срок: {session['days']} дней

⏰ **Время:** {datetime.now().strftime('%H:%M %d.%m.%Y')}

💬 **Для выдачи ключа введите:**
`/send {user_id} ВАШ_КЛЮЧ_ЗДЕСЬ`
    """
    
    try:
        if update.message.photo:
            file_id = update.message.photo[-1].file_id
            await context.bot.send_photo(
                chat_id=ADMIN_ID,
                photo=file_id,
                caption=admin_text
            )
        else:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=admin_text
            )
        
        # Подтверждение пользователю
        await update.message.reply_text(
            "✅ **Скриншот отправлен на проверку!**\n\n"
            "Администратор получил вашу заявку.\n"
            "🔑 **Ключ будет отправлен в течение 1-2 часов.**\n\n"
            "Спасибо за покупку! 🚀"
        )
        
        # Очищаем сессию
        del user_sessions[user_id]
        
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def handle_free_cheat_request(update: Update, context: ContextTypes.DEFAULT_TYPE, cheat_type: str):
    """Обработка запросов бесплатных читов"""
    cheat_data = {
        'free_clumsy': {
            'name': 'Clumsy Netwing',
            'description': 'Полная версия Clumsy Netwing для Standoff 2',
            'download_link': 'https://disk.yandex.ru/d/TnVAVZduzn5c3A',
            'instructions': '1. Скачайте файл по ссылке\n2. Распакуйте архив\n3. Запустите установщик\n4. Следуйте инструкциям'
        },
        'free_cfg': {
            'name': 'КФГ К Clumsy', 
            'description': 'Оптимизированные конфигурации для Clumsy',
            'download_link': 'https://disk.yandex.ru/d/ABXT15gdJMny8A',
            'instructions': '1. Скачайте CFG файл\n2. Поместите в папку с игрой\n3. Запустите игру\n4. Активируйте в настройках'
        }
    }
    
    cheat = cheat_data.get(cheat_type, {})
    if not cheat:
        await update.callback_query.edit_message_text("❌ Чит не найден")
        return
    
    text = f"""
🎁 **{cheat['name']}**

📝 **Описание:** {cheat['description']}

📥 **Скачать:** {cheat['download_link']}

📖 **Инструкция по установке:**
{cheat['instructions']}

⚠️ **ВАЖНО:**
• Для работы требуется подписка на наш канал!
• Используйте на свой страх и риск

📢 **Наш канал:** {CHANNEL_LINK}
👨‍💻 **Поддержка:** {SUPPORT_USERNAME}
    """
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Подписаться на канал", url=CHANNEL_LINK)],
        [InlineKeyboardButton("⬅️ Назад к бесплатным читам", callback_data="game_freecheats")]
    ])
    
    await update.callback_query.edit_message_text(text, reply_markup=keyboard)

# 🔥 АДМИН КОМАНДЫ
async def handle_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик админ команд"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды!")
        return
    
    text = update.message.text
    
    if text.startswith('/send '):
        try:
            parts = text.split(' ', 2)
            if len(parts) >= 3:
                target_user_id = int(parts[1])
                cheat_key = parts[2]
                
                # Ищем последний заказ пользователя
                user_orders = db.get_user_orders(target_user_id)
                last_order = None
                product_name = "Продукт"
                
                for order in user_orders:
                    if order['status'] == 'pending':
                        last_order = order
                        game_type = order['game_type']
                        product_type = order['product_type']
                        products = PRODUCTS.get(game_type, {})
                        product_info = products.get(product_type, {})
                        product_name = product_info.get('name', 'Продукт')
                        break
                
                try:
                    await context.bot.send_message(
                        chat_id=target_user_id,
                        text=f"🎉 **Ваш ключ активирован!**\n\n"
                             f"🔑 **Ключ:** `{cheat_key}`\n\n"
                             f"Спасибо за покупку! 🚀\n"
                             f"По вопросам: {SUPPORT_USERNAME}"
                    )
                    
                    if last_order:
                        db.complete_order(last_order['id'], user_id, cheat_key)
                    
                    await update.message.reply_text(f"✅ Ключ отправлен пользователю {target_user_id}")
                    
                    # 🔥 ЗАПРАШИВАЕМ ОТЗЫВ
                    if last_order:
                        await request_review(update, context, target_user_id, last_order['id'], product_name)
                    
                except Exception as e:
                    error_msg = f"❌ Ошибка отправки пользователю: {e}"
                    logger.error(error_msg)
                    await update.message.reply_text(error_msg)
            else:
                await update.message.reply_text(
                    "❌ Неправильный формат команды!\n\n"
                    "Правильный формат:\n"
                    "`/send USER_ID КЛЮЧ`\n\n"
                    "Пример:\n"
                    "`/send 123456789 GRAPE-KEY-12345`"
                )
        except ValueError:
            await update.message.reply_text("❌ Неверный user_id")

# 🔥 ГЛАВНАЯ ФУНКЦИЯ
def main():
    """Основная функция запуска бота"""
    print("🚀 Запуск бота для python-telegram-bot 20.x...")
    
    try:
        # Создаем Application
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Добавляем обработчики команд
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("send", handle_admin_command))
        
        # Обработчики сообщений
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_handler(MessageHandler(filters.PHOTO, handle_payment_proof))
        
        # Обработчики callback-запросов
        application.add_handler(CallbackQueryHandler(handle_callback))
        
        print("✅ Бот успешно запущен!")
        print(f"👮‍♂️ Администратор: {ADMIN_ID}")
        
        # Запускаем бота
        application.run_polling()
        
    except Exception as e:
        logger.critical(f"❌ Критическая ошибка запуска: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
