# 🔍 Telegram Chat Monitor Bot

Умный бот для мониторинга Telegram чатов с фильтрацией по ключевым словам. Автоматически находит и пересылает сообщения, содержащие заданные ключевые слова, прямо в ваши Saved Messages.


## ✨ Возможности

- **📊 Мониторинг чатов** - Автоматический поиск сообщений по ключевым словам
- **⚡ Двойная система фильтров** - Ключевые слова + бан-слова для точной фильтрации
- **🔔 Мгновенные уведомления** - Пересылка найденных сообщений в Saved Messages
- **🎯 Гибкая настройка** - Динамическое изменение фильтров через команды бота
- **🚫 Защита от спама** - Игнорирование сообщений с запрещенными словами
- **👥 Белый список** - Ограничение доступа к управлению ботом
- **🌐 Поддержка групп и каналов** - Работает в любых типах чатов

## 🏗 Архитектура
telegram-chat-monitor/
├── config/ # Конфигурационные файлы
│ ├── bot_config.py # Основная конфигурация бота
│ ├── keywords.json # Файл с ключевыми и бан-словами
│ └── logger_config.py # Настройки логирования
│
├── handlers/ # Обработчики сообщений и команд
│ ├── commands/ # Обработчики команд бота
│ │ └── base_handlers.py
│ └── custom_handlers/ # Кастомные обработчики
│ ├── custom_commands.py
│ └── join_handlers.py
│
├── states/ # Finite State Machine состояния
│ └── all_states.py
│
├── utils/ # Вспомогательные утилиты
│
│ ├── generate_session.py # Генератор сессии Telethon
│ ├── join_groups.py # Автоприсоединение к группам
│ ├── json_keywords_manager.py # Менеджер ключевых слов
│ ├── llogin.py  # Генератор сессии Telethon (на случай еслим не сработает generate_session.py)
│ ├── logger.py # Логирование
│ └── special_func.py # Специальные функции
│
│
├── Dockerfile # Конфигурация Docker
├── main.py # Главный исполняемый файл
└── requirements.txt # Зависимости Python


## 📦 Установка и запуск

### 1. Клонирование репозитория

git clone https://github.com/ZheglY/multi-chat-keyword-forwarder-.git
cd multi-chat-keyword-forwarder-
2. Создание виртуального окружения
bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# или
.venv\Scripts\activate     # Windows
3. Установка зависимостей
bash
pip install -r requirements.txt
4. Настройка конфигурации
Создайте файл .env или установите переменные окружения:

bash
# Бот
BOT_TOKEN=your_bot_token_here

# Пользовательский аккаунт (для мониторинга)
API_ID=your_api_id
API_HASH=your_api_hash
SESSION_STRING=your_session_string

# Настройки доступа
ADMIN_CHAT_ID=your_chat_id
ALLOWED_USERS=user_id1,user_id2,user_id3
5. Генерация сессии Telethon
bash
python utils/generate_session.py
Если скрипт generate_session.py ломается, запустите llogin.py
bash
python utils/llogin.py
6. Запуск бота
bash
python main.py
🚀 Деплой на Fly.io
1. Установка flyctl
bash
# Linux/Mac
curl -L https://fly.io/install.sh | sh

# Windows
iwr https://fly.io/install.ps1 -useb | iex
2. Инициализация приложения
bash
flyctl auth login
flyctl launch --name your-app-name --region fra --no-deploy
3. Настройка секретов
bash
flyctl secrets set \
  BOT_TOKEN="your_bot_token" \
  API_ID="your_api_id" \
  API_HASH="your_api_hash" \
  SESSION_STRING="your_session_string" \
  ADMIN_CHAT_ID="your_chat_id" \
  ALLOWED_USERS="user_id1,user_id2,user_id3"
4. Деплой
bash
flyctl deploy
📋 Команды бота
Основные команды:
/start - Информация о боте и доступных командах

/filters - Показать и изменить ключевые слова для фильтрации сообщений в чатах

/ban - Показать и изменить бан-слова которые будут скипать ненужные сообщения

Управление фильтрами:
text
/filters слово1 слово2 слово3
/ban запрещенное_слово1 запрещенное_слово2
⚙️ Конфигурация
Формат файла keywords.json:
json
{
  "keywords": ["usdt", "крипта", "обмен", "купить", "продать"],
  "ban_words": ["развод", "скам", "мошенник", "наркотики", "оружие"]
}
Пример добавления фильтров:
bash
# Добавить ключевые слова
/filters фото видео рилс монтаж ютуб

# Добавить бан-слова  
/ban рассылка спам мошенник
🔧 Для разработчиков
Структура проекта:
Telethon Client - Для мониторинга чатов и работы с пользовательским аккаунтом

Aiogram Bot - Для обработки команд и взаимодействия с пользователем

JSON Keywords Manager - Для управления фильтрами через JSON файл

State Management - Для обработки состояний FSM

Добавление новой функциональности:
Создайте обработчик в папке handlers/

Зарегистрируйте его в main.py

Добавьте команду в base_handlers.py

🐛 Поиск и устранение неисправностей

Ошибка авторизации - Проверьте правильность API_ID и API_HASH

Конфликт сессий - Убедитесь что только один инстанс бота запущен. На сервере может работать только одна машина!

Не присылаются сообщения - Бот должен быть участником мониторируемых чатов, проверьте наличие слов фильтров, их можно добавить с помощью команды /filters. После перезапуска бота ключевые и бан слова будут удалены!

Логирование:
Логи сохраняются в папке logs/ и выводятся в консоль с различными уровнями детализации.

📄 Лицензия
Этот проект распространяется под лицензией MIT. Подробнее см. в файле LICENSE.

⚠️ Важно
Используйте только для легальных целей

Соблюдайте правила Telegram ToS

Не нарушайте приватность других пользователей

Храните секретные данные в переменных окружения

📞 Поддержка
Если у вас возникли вопросы или проблемы:

Проверьте документацию выше

Создайте issue в репозитории

Проверьте логи в папке logs/

⭐ Если проект полезен - поставьте звезду на GitHub!

## Contact
- 💬 Telegram: [@progaem_1098](https://t.me/progaem_1098)  
- 📢 Telegram Channel: [IT_Python_ZheglY](https://t.me/IT_Python_ZheglY)  
- 🐙 GitHub: [ZheglY](https://github.com/ZheglY)

text
