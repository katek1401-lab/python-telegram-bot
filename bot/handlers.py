"""Telegram handlers for VK AI Manager."""

import asyncio
import base64
import logging
import os
from typing import Any

from openai import AsyncOpenAI
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.error import Conflict, NetworkError, TimedOut
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot import cache, db


logger = logging.getLogger(__name__)

DB_KEY = "db"
REDIS_KEY = "redis"
PROFILE_TABLE_READY_KEY = "profile_state_table_ready"

OPENROUTER_API_KEY = os.getenv(
    "OPENROUTER_API_KEY",
    "",
).strip()

TEXT_MODEL = os.getenv(
    "OPENROUTER_TEXT_MODEL",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
).strip()

FALLBACK_TEXT_MODEL = "openrouter/free"

VISION_MODEL = os.getenv(
    "OPENROUTER_VISION_MODEL",
    "openrouter/free",
).strip()

ADMIN_TELEGRAM_ID = os.getenv(
    "ADMIN_TELEGRAM_ID",
    "",
).strip()


openai_client = AsyncOpenAI(
    api_key=OPENROUTER_API_KEY or "missing-key",
    base_url="https://openrouter.ai/api/v1",
    timeout=60.0,
)


BOT_COMMANDS = (
    ("start", "Главное меню"),
    ("today", "Что делать сегодня"),
    ("post", "Создать пост"),
    ("plan", "План на 7 дней"),
    ("strategy", "Стратегия роста"),
    ("next", "Что публиковать дальше"),
    ("status", "Проверить подключения"),
    ("myid", "Показать мой Telegram ID"),
    ("help", "Что умеет бот"),
    ("ping", "Проверить бота"),
)


MENU_TODAY = "Что делать сегодня"
MENU_PLAN = "План на неделю"
MENU_NEXT = "Что публиковать дальше"
MENU_STRATEGY = "Стратегия роста"


MAIN_MENU_KEYBOARD = ReplyKeyboardMarkup(
    [
        [MENU_TODAY],
        [MENU_PLAN, MENU_NEXT],
        [MENU_STRATEGY],
    ],
    resize_keyboard=True,
    is_persistent=True,
    input_field_placeholder="Напиши задачу для VK AI Manager",
)


CREATE_PROFILE_STATE_TABLE = """
CREATE TABLE IF NOT EXISTS vk_manager_profile_state (
    telegram_id BIGINT PRIMARY KEY,
    current_city TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


SYSTEM_PROMPT = """
Ты — VK AI Manager, личный AI-контент-менеджер пользователя.

ПОЗИЦИОНИРОВАНИЕ СТРАНИЦЫ

Это личный авторский блог женщины и мамы,
жизнь которой связана с Мурманском и Нижним Новгородом.

Главная идея:
«Живая жизнь между двумя городами».

Это НЕ типичный мамский блог.

Главный герой страницы — сама автор.

Дети, семья, поездки, материнство и быт —
естественная часть жизни,
но не единственная тема страницы.

Основные направления:

— сама автор, её взгляд и характер;
— жизнь между Мурманском и Нижним Новгородом;
— контраст двух городов;
— настоящая повседневность;
— семья и дети как естественная часть жизни;
— поездки и дороги;
— бытовой юмор;
— личные мысли;
— красивые обычные моменты;
— полезный личный опыт;
— фотоистории;
— короткие вертикальные видео.

ЦЕЛЬ

Органически развивать личную страницу ВКонтакте:

— увеличивать охваты;
— повышать вовлечённость;
— усиливать узнаваемость автора;
— формировать интерес к самой личности;
— постепенно увеличивать заинтересованную аудиторию.

Ты работаешь как инициативный контент-менеджер,
а не просто как генератор текста.

ЯЗЫК — ОЧЕНЬ ВАЖНО

Всегда отвечай на хорошем естественном русском языке.

Не смешивай русский и английский языки.

Не используй английские слова,
если существует обычный русский вариант.

Например:

не пиши «authentic» — пиши «естественный»;
не пиши «vertical» — пиши «вертикальный»;
не пиши «ordinary» — пиши «обычный»;
не пиши «view» — пиши «вид»;
не пиши «ground» — пиши «земля», «дорога» или «кадр снизу»;
не пиши «content» — пиши «контент» или «материал»;
не пиши «engagement» — пиши «вовлечённость».

Не создавай гибридные слова,
в которых смешаны русские и английские части.

Запрещены конструкции вроде:

«заconstruction»,
«сGround»,
«реелс-подобный»,
«ordinary-момент».

Если можно сказать проще по-русски —
говори проще.

Перед отправкой каждого ответа мысленно проверь:

1. Нет ли случайных английских слов.
2. Нет ли сломанных или смешанных слов.
3. Звучит ли текст естественно для русскоязычного человека.
4. Не слишком ли много профессионального жаргона.

Термины ВКонтакте используй по-русски:

— пост;
— клип;
— история;
— фотография;
— видео;
— карусель;
— охват;
— вовлечённость;
— подписчики;
— публикация.

ВАЖНО: НЕ ВЫДУМЫВАЙ ФАКТЫ

Нельзя самостоятельно придумывать:

— цены;
— суммы;
— покупки;
— даты;
— возраст детей;
— имена;
— профессии;
— медицинские факты;
— семейные проблемы;
— места посещения;
— конкретные события;
— цитаты детей;
— планы семьи;
— длительность поездок;
— погоду;
— то, где пользователь сейчас находится.

Если текущий город прямо передан тебе
как сохранённый город пользователя,
считай этот город подтверждённым фактом.

Не спрашивай город повторно,
если он уже указан в контексте задачи.

Если пользователь сообщает:

«Я сейчас в Нижнем Новгороде»,
«Я в Нижнем»,
«Я теперь в Мурманске»

или другую однозначную формулировку,
используй эту информацию как факт.

УПРАВЛЕНИЕ КОНТЕНТОМ

Не заставляй пользователя самой каждый раз придумывать тему.

Ты должен сам выбирать:

— что лучше снять;
— какие кадры нужны;
— какой формат использовать;
— какой материал искать в галерее;
— что публиковать следующим;
— зачем этот материал нужен странице.

Особенно важно:

НЕ выдавай меню из множества вариантов,
когда тебя попросили решить, что делать.

Если команда означает:
«Что делать сегодня?»,
ты должен выбрать ОДНУ лучшую задачу.

Не пиши:
«можно сделать первое, второе или третье».

Прими решение как менеджер.

После выбора объясни его коротко и практично.

Не публикуй что-либо только ради ежедневной активности.
Иногда отсутствие публикации лучше слабого материала.

Чередуй:

1. саму автора;
2. жизнь двух городов;
3. семью;
4. юмор;
5. личные мысли;
6. городские детали;
7. красивые бытовые моменты;
8. полезный реальный опыт;
9. вовлекающий контент;
10. короткие видео.

Не превращай страницу в бесконечную ленту фотографий детей.

ФОТОГРАФИИ

Если пользователь прислал фото:

— анализируй только то, что действительно видно;
— не устанавливай личности людей;
— не придумывай обстоятельства съёмки;
— выбирай сильные кадры;
— объясняй выбор;
— предлагай, нужен ли вообще пост;
— если материала недостаточно, скажи, что доснять.

ГОТОВЫЙ ПОСТ

По умолчанию:

1. сильная первая строка;
2. естественный основной текст;
3. призыв к действию только если он действительно нужен;
4. от 0 до 5 уместных хэштегов;
5. строка:
   «Зачем этот пост: ...»

Пиши по-русски.

Тон:
живой, умный, современный, тёплый,
без пафоса и шаблонной мотивации.

Не используй спам и накрутку.
Не обещай гарантированный рост или вирусность.

Не задавай длинные анкеты.

Если можно принять разумное решение самостоятельно —
принимай его.

Если вопрос действительно необходим —
максимум один короткий вопрос.

Ничего не публикуй автоматически.
Финальное решение всегда принимает пользователь.
""".strip()


HELP_TEXT = """
Я — VK AI Manager.

Я веду твою личную страницу как контент-менеджер.

Я уже знаю концепцию:
живой авторский блог между Мурманском
и Нижним Новгородом.

Главный герой страницы — ты сама.

Команды:

/today — выбрать одну задачу на сегодня
/post тема — написать готовый пост
/plan — сделать план на неделю
/strategy — стратегия развития
/next — выбрать следующий материал
/status — проверить работу
/myid — показать Telegram ID

Чтобы сменить город, просто напиши:

«Я теперь в Мурманске»

или

«Я сейчас в Нижнем Новгороде»

Я запомню город и буду учитывать его дальше.

Можно присылать фотографии и альбомы.
Я выберу материал и подготовлю публикацию.

Я не выдумываю факты твоей жизни
и ничего не публикую без твоего решения.
""".strip()


PHOTO_GROUPS: dict[str, dict[str, Any]] = {}


def city_in_phrase(city: str) -> str:

    if city == "Нижний Новгород":
        return "Нижнем Новгороде"

    if city == "Мурманск":
        return "Мурманске"

    return city


def is_allowed(update: Update) -> bool:

    if not ADMIN_TELEGRAM_ID:
        return True

    user = update.effective_user

    return bool(
        user
        and str(user.id) == ADMIN_TELEGRAM_ID
    )


async def guard(update: Update) -> bool:

    if is_allowed(update):
        return True

    if update.effective_message:
        await update.effective_message.reply_text(
            "У этого бота закрытое управление."
        )

    return False


def ai_ready() -> bool:
    return bool(OPENROUTER_API_KEY)


async def ensure_profile_table(
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:

    if context.bot_data.get(
        PROFILE_TABLE_READY_KEY
    ):
        return True

    pool = context.bot_data.get(
        DB_KEY
    )

    if pool is None:
        return False

    try:

        await pool.execute(
            CREATE_PROFILE_STATE_TABLE
        )

        context.bot_data[
            PROFILE_TABLE_READY_KEY
        ] = True

        return True

    except Exception:

        logger.exception(
            "Could not create profile state table"
        )

        return False


async def set_current_city(
    context: ContextTypes.DEFAULT_TYPE,
    telegram_id: int,
    city: str,
) -> None:

    context.user_data[
        "current_city"
    ] = city

    ready = await ensure_profile_table(
        context
    )

    if not ready:
        return

    pool = context.bot_data.get(
        DB_KEY
    )

    if pool is None:
        return

    try:

        await pool.execute(
            """
            INSERT INTO vk_manager_profile_state (
                telegram_id,
                current_city,
                updated_at
            )
            VALUES ($1, $2, now())
            ON CONFLICT (telegram_id)
            DO UPDATE SET
                current_city = EXCLUDED.current_city,
                updated_at = now();
            """,
            telegram_id,
            city,
        )

    except Exception:

        logger.exception(
            "Could not save current city"
        )


async def get_current_city(
    context: ContextTypes.DEFAULT_TYPE,
    telegram_id: int,
) -> str:

    cached = context.user_data.get(
        "current_city",
        "",
    )

    if cached:
        return str(cached)

    ready = await ensure_profile_table(
        context
    )

    if not ready:
        return ""

    pool = context.bot_data.get(
        DB_KEY
    )

    if pool is None:
        return ""

    try:

        city = await pool.fetchval(
            """
            SELECT current_city
            FROM vk_manager_profile_state
            WHERE telegram_id = $1;
            """,
            telegram_id,
        )

        if city:

            context.user_data[
                "current_city"
            ] = city

            return str(city)

    except Exception:

        logger.exception(
            "Could not load current city"
        )

    return ""


def detect_city(
    text: str,
) -> str | None:

    normalized = (
        text
        .lower()
        .replace("ё", "е")
        .strip()
    )

    if "мурманск" in normalized:
        return "Мурманск"

    if (
        "нижн" in normalized
        and "новгород" in normalized
    ):
        return "Нижний Новгород"

    short_nizhny = {
        "нижний",
        "в нижнем",
        "я в нижнем",
        "сейчас в нижнем",
        "я сейчас в нижнем",
    }

    if normalized in short_nizhny:
        return "Нижний Новгород"

    return None


async def send_long_text(
    message,
    text: str,
    reply_markup=None,
) -> None:

    text = (
        text
        or ""
    ).strip()

    if not text:

        await message.reply_text(
            "ИИ вернул пустой ответ. Попробуй ещё раз."
        )

        return

    parts = [
        text[i:i + 3900]
        for i in range(
            0,
            len(text),
            3900,
        )
    ]

    for index, part in enumerate(
        parts
    ):

        markup = (
            reply_markup
            if index == len(parts) - 1
            else None
        )

        await message.reply_text(
            part,
            reply_markup=markup,
        )


def extract_chat_text(
    response,
) -> str:

    if not response.choices:
        return ""

    message = response.choices[
        0
    ].message

    if message is None:
        return ""

    content = message.content

    if isinstance(
        content,
        str,
    ):
        return content.strip()

    return ""


async def request_text_model(
    model: str,
    prompt: str,
) -> str:

    response = (
        await openai_client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
        )
    )

    return extract_chat_text(
        response
    )


async def ai_text(
    prompt: str,
    model: str | None = None,
) -> str:

    if not ai_ready():

        raise RuntimeError(
            "OPENROUTER_API_KEY is not configured"
        )

    primary_model = (
        model
        or TEXT_MODEL
    )

    try:

        text = await request_text_model(
            primary_model,
            prompt,
        )

        if text:
            return text

        logger.warning(
            "Primary model returned empty response: %s",
            primary_model,
        )

    except Exception as error:

        logger.warning(
            "Primary model failed: %s",
            error,
        )

    if (
        primary_model
        == FALLBACK_TEXT_MODEL
    ):

        raise RuntimeError(
            "OpenRouter returned an empty response"
        )

    try:

        logger.info(
            "Trying fallback model: %s",
            FALLBACK_TEXT_MODEL,
        )

        text = await request_text_model(
            FALLBACK_TEXT_MODEL,
            prompt,
        )

        if text:
            return text

    except Exception as error:

        logger.warning(
            "Fallback model failed: %s",
            error,
        )

    raise RuntimeError(
        "OpenRouter primary and fallback models failed"
    )


async def telegram_photo_data_url(
    context: ContextTypes.DEFAULT_TYPE,
    file_id: str,
) -> str:

    tg_file = await context.bot.get_file(
        file_id
    )

    raw = await tg_file.download_as_bytearray()

    encoded = base64.b64encode(
        raw
    ).decode(
        "utf-8"
    )

    return (
        "data:image/jpeg;base64,"
        + encoded
    )


async def ai_post_from_photos(
    context: ContextTypes.DEFAULT_TYPE,
    file_ids: list[str],
    user_caption: str = "",
    current_city: str = "",
) -> str:

    city_context = (
        current_city
        if current_city
        else "не указан"
    )

    content: list[
        dict[str, Any]
    ] = [
        {
            "type": "input_text",
            "text": (
                "Ты получил фотографии для личной "
                "страницы пользователя ВКонтакте.\n\n"
                "Сохранённый текущий город пользователя: "
                + city_context
                + ".\n\n"
                "Не утверждай, что фотография сделана "
                "именно в этом городе, если это не видно "
                "и пользователь этого не написал.\n\n"
                "Проанализируй фотографии как "
                "контент-менеджер.\n"
                "Если фотографий несколько — выбери "
                "самые сильные и лучший порядок.\n"
                "Не придумывай обстоятельства съёмки.\n"
                "Если материал подходит — создай один "
                "готовый пост.\n"
                "Если материал слабый — честно скажи, "
                "что лучше доснять.\n\n"
                "Пиши только на естественном русском языке. "
                "Не вставляй английские слова и "
                "не смешивай два языка.\n\n"
                "После текста напиши коротко:\n"
                "Лучшие фото: ...\n"
                "Почему: ...\n"
                "Что следующим: ...\n\n"
                "Комментарий пользователя: "
                + (
                    user_caption
                    or "нет"
                )
            ),
        }
    ]

    for file_id in file_ids[
        :10
    ]:

        image_url = (
            await telegram_photo_data_url(
                context,
                file_id,
            )
        )

        content.append(
            {
                "type": "input_image",
                "image_url": image_url,
            }
        )

    response = (
        await openai_client.responses.create(
            model=VISION_MODEL,
            instructions=SYSTEM_PROMPT,
            input=[
                {
                    "role": "user",
                    "content": content,
                }
            ],
        )
    )

    text = (
        response.output_text
        or ""
    ).strip()

    if not text:

        raise RuntimeError(
            "Vision model returned an empty response"
        )

    return text


def save_draft(
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    file_ids: list[str] | None = None,
) -> None:

    context.user_data[
        "draft_text"
    ] = text

    context.user_data[
        "draft_photo_ids"
    ] = list(
        file_ids
        or []
    )


def draft_keyboard() -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Оставить как готовый",
                    callback_data="keep_draft",
                ),
                InlineKeyboardButton(
                    "🔄 Переделать",
                    callback_data="rewrite_draft",
                ),
            ]
        ]
    )


async def build_today_task(
    context: ContextTypes.DEFAULT_TYPE,
    telegram_id: int,
) -> str | None:

    city = await get_current_city(
        context,
        telegram_id,
    )

    if not city:
        return None

    last_plan = context.user_data.get(
        "last_plan",
        "",
    )

    last_draft = context.user_data.get(
        "draft_text",
        "",
    )

    prompt = (
        "Рабочий режим: ты сейчас личный "
        "контент-менеджер и сам принимаешь решение.\n\n"
        "Подтверждённый текущий город пользователя: "
        + city
        + ".\n"
        "Не спрашивай, где она сейчас.\n"
        "Не спрашивай, действительно ли она там.\n\n"
        "Выбери ОДНУ конкретную задачу на сегодня "
        "для развития её личной страницы VK.\n\n"
        "Не предлагай три идеи.\n"
        "Не предлагай выбор из нескольких вариантов.\n"
        "Не заканчивай ответ вопросом.\n"
        "Не придумывай погоду, события или планы семьи.\n"
        "Не отправляй её обязательно в туристические места.\n"
        "Задача должна быть выполнима обычным телефоном.\n\n"
        "ОЧЕНЬ ВАЖНО:\n"
        "Пиши только на нормальном русском языке.\n"
        "Не используй английские слова.\n"
        "Не создавай смешанные русско-английские слова.\n"
        "Не используй профессиональный жаргон без необходимости.\n"
        "Перед ответом проверь каждую фразу на естественность.\n\n"
        "Ответ строго в таком формате:\n\n"
        "🎯 Сегодня\n"
        "Одна конкретная идея в 1–2 предложениях.\n\n"
        "📸 Сними\n"
        "3–4 конкретных кадра или коротких видео.\n\n"
        "🖼 Если момент уже прошёл\n"
        "Что конкретно поискать в галерее.\n\n"
        "📤 Потом пришли мне\n"
        "Что именно пользователь должен отправить боту.\n\n"
        "💡 Зачем\n"
        "Одна короткая причина, какую задачу развития "
        "решает этот материал.\n\n"
        "После этого остановись."
    )

    if last_plan:

        prompt += (
            "\n\nПоследний план, чтобы не повторяться:\n"
            + last_plan[:2500]
        )

    if last_draft:

        prompt += (
            "\n\nПоследний подготовленный материал, "
            "чтобы не повторяться:\n"
            + last_draft[:1200]
        )

    return await ai_text(
        prompt
    )


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not await guard(update):
        return

    message = update.effective_message
    user = update.effective_user

    if (
        message is None
        or user is None
    ):
        return

    pool = context.bot_data.get(
        DB_KEY
    )

    if pool is not None:

        try:

            await db.upsert_user(
                pool,
                user.id,
                user.username,
                user.first_name,
            )

        except Exception:

            logger.exception(
                "Could not save Telegram user"
            )

    city = await get_current_city(
        context,
        user.id,
    )

    if city:

        city_line = (
            "\n\nСейчас я помню: ты в "
            + city_in_phrase(city)
            + "."
        )

    else:

        city_line = (
            "\n\nТекущий город пока не сохранён. "
            "Можно написать: "
            "«Я сейчас в Нижнем Новгороде»."
        )

    await message.reply_text(
        "Привет! Я VK AI Manager.\n\n"
        "Я работаю как менеджер твоей личной страницы VK.\n"
        "Я сам предлагаю следующий контент, "
        "анализирую фотографии и готовлю публикации."
        + city_line,
        reply_markup=MAIN_MENU_KEYBOARD,
    )


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not await guard(update):
        return

    if update.effective_message:

        await send_long_text(
            update.effective_message,
            HELP_TEXT,
        )


async def myid(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    del context

    user = update.effective_user

    if (
        update.effective_message
        and user
    ):

        await update.effective_message.reply_text(
            "Твой Telegram ID: "
            + str(user.id)
        )


async def ping(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not await guard(update):
        return

    message = update.effective_message

    if message is None:
        return

    client = context.bot_data.get(
        REDIS_KEY
    )

    if client is None:

        await message.reply_text(
            "pong"
        )

        return

    try:

        cached = await cache.get_or_set_ping(
            client
        )

        await message.reply_text(
            "pong (cached)"
            if cached
            else "pong (fresh)"
        )

    except Exception:

        await message.reply_text(
            "pong"
        )


async def status_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not await guard(update):
        return

    message = update.effective_message
    user = update.effective_user

    if (
        message is None
        or user is None
    ):
        return

    city = await get_current_city(
        context,
        user.id,
    )

    ai = (
        "✅"
        if ai_ready()
        else "❌"
    )

    lock = (
        "✅"
        if ADMIN_TELEGRAM_ID
        else "⚠️"
    )

    city_status = (
        city
        if city
        else "не указан"
    )

    await message.reply_text(
        "ИИ OpenRouter: "
        + ai
        + "\nЗакрытый доступ: "
        + lock
        + "\nТекущий город: "
        + city_status
        + "\nКонцепция страницы: ✅"
        + "\nРусский язык ответов: ✅"
        + "\nРезервная AI-модель: ✅"
        + "\nАвтопубликация в VK: выключена"
    )


async def today_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not await guard(update):
        return

    message = update.effective_message
    user = update.effective_user

    if (
        message is None
        or user is None
    ):
        return

    city = await get_current_city(
        context,
        user.id,
    )

    if not city:

        await message.reply_text(
            "В каком городе ты сейчас — "
            "Мурманск или Нижний Новгород?"
        )

        return

    await message.reply_text(
        "Выбираю одну задачу на сегодня…"
    )

    try:

        result = await build_today_task(
            context,
            user.id,
        )

        if not result:

            await message.reply_text(
                "Сначала скажи, в каком городе ты сейчас."
            )

            return

        await send_long_text(
            message,
            result,
        )

    except Exception:

        logger.exception(
            "Today recommendation failed"
        )

        await message.reply_text(
            "Не получилось выбрать задачу на сегодня. "
            "Попробуй ещё раз."
        )


async def strategy_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not await guard(update):
        return

    message = update.effective_message
    user = update.effective_user

    if (
        message is None
        or user is None
    ):
        return

    city = await get_current_city(
        context,
        user.id,
    )

    await message.reply_text(
        "Готовлю стратегию роста…"
    )

    try:

        prompt = (
            "Составь практичную стратегию развития "
            "этой конкретной личной страницы VK "
            "на ближайшие 30 дней.\n"
            "Ты уже знаешь позиционирование страницы.\n"
            "Не давай абстрактных примеров профессий.\n"
            "Не выдумывай события жизни.\n"
            "Дай рубрики, форматы, частоту, "
            "гипотезы роста, принципы отбора фото "
            "и план первых 7 дней.\n"
            "Пиши только на естественном русском языке. "
            "Не смешивай русский и английский."
        )

        if city:

            prompt += (
                "\nСохранённый текущий город пользователя: "
                + city
                + ". Не нужно спрашивать его снова."
            )

        result = await ai_text(
            prompt
        )

        await send_long_text(
            message,
            result,
        )

    except Exception:

        logger.exception(
            "Strategy generation failed"
        )

        await message.reply_text(
            "Не получилось составить стратегию. "
            "Попробуй ещё раз чуть позже."
        )


async def plan_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not await guard(update):
        return

    message = update.effective_message
    user = update.effective_user

    if (
        message is None
        or user is None
    ):
        return

    topic = " ".join(
        context.args
    ).strip()

    city = await get_current_city(
        context,
        user.id,
    )

    await message.reply_text(
        "Составляю план на неделю…"
    )

    try:

        prompt = (
            "Составь практичный контент-план "
            "на 7 дней для этой личной страницы VK.\n"
            "Чередуй саму автора, город, семью, юмор, "
            "личные мысли, визуальные истории "
            "и полезный реальный опыт.\n"
            "Не выдумывай события будущей недели.\n"
            "Формулируй идеи так, чтобы их можно было "
            "адаптировать к реальному дню.\n"
            "Для каждого материала укажи цель, формат, "
            "что снять или найти в галерее "
            "и зачем это странице.\n"
            "Можно оставить дни без публикации.\n"
            "Пиши только на хорошем русском языке. "
            "Не вставляй английские слова.\n"
        )

        if city:

            prompt += (
                "\nПодтверждённый текущий город: "
                + city
                + ". Не спрашивай город."
            )

        if topic:

            prompt += (
                "\nДополнительная тема пользователя: "
                + topic
            )

        result = await ai_text(
            prompt
        )

        context.user_data[
            "last_plan"
        ] = result

        await send_long_text(
            message,
            result,
        )

    except Exception:

        logger.exception(
            "Content plan generation failed"
        )

        await message.reply_text(
            "Не получилось составить план."
        )


async def next_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not await guard(update):
        return

    message = update.effective_message
    user = update.effective_user

    if (
        message is None
        or user is None
    ):
        return

    city = await get_current_city(
        context,
        user.id,
    )

    last_plan = context.user_data.get(
        "last_plan",
        "",
    )

    last_draft = context.user_data.get(
        "draft_text",
        "",
    )

    prompt = (
        "Как личный контент-менеджер выбери "
        "ОДИН лучший следующий материал для страницы.\n"
        "Не давай меню вариантов.\n"
        "Не выдумывай события.\n"
        "Дай цель, формат, что снять или найти "
        "в галерее и зачем это нужно сейчас.\n"
        "Пиши только на естественном русском языке. "
        "Не смешивай русский и английский."
    )

    if city:

        prompt += (
            "\nПодтверждённый текущий город: "
            + city
            + ". Не спрашивай его снова."
        )

    if last_plan:

        prompt += (
            "\nПоследний план:\n"
            + last_plan[:3000]
        )

    if last_draft:

        prompt += (
            "\nПоследний материал:\n"
            + last_draft[:1500]
        )

    try:

        result = await ai_text(
            prompt
        )

        await send_long_text(
            message,
            result,
        )

    except Exception:

        logger.exception(
            "Next post recommendation failed"
        )

        await message.reply_text(
            "Не получилось выбрать следующий материал."
        )


async def post_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not await guard(update):
        return

    message = update.effective_message
    user = update.effective_user

    if (
        message is None
        or user is None
    ):
        return

    topic = " ".join(
        context.args
    ).strip()

    if not topic:

        await message.reply_text(
            "Напиши тему после команды.\n\n"
            "Например:\n"
            "/post прогулка по городу"
        )

        return

    city = await get_current_city(
        context,
        user.id,
    )

    await message.reply_text(
        "Готовлю пост…"
    )

    try:

        prompt = (
            "Создай один готовый пост для этой "
            "личной страницы ВКонтакте.\n"
            "Тема пользователя: "
            + topic
            + ".\n"
            "Не придумывай факты, которых пользователь "
            "не сообщил.\n"
            "Пиши живым естественным русским языком. "
            "Не используй английские слова, если есть "
            "обычный русский вариант."
        )

        if city:

            prompt += (
                "\nТекущий сохранённый город: "
                + city
                + ". Используй это только там, "
                "где это уместно."
            )

        text = await ai_text(
            prompt
        )

        save_draft(
            context,
            text,
        )

        await send_long_text(
            message,
            text,
            reply_markup=draft_keyboard(),
        )

    except Exception:

        logger.exception(
            "Post generation failed"
        )

        await message.reply_text(
            "Не получилось создать пост."
        )


async def draft_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not await guard(update):
        return

    query = update.callback_query

    if query is None:
        return

    await query.answer()

    if query.data == "keep_draft":

        await query.edit_message_reply_markup(
            reply_markup=None
        )

        await query.message.reply_text(
            "✅ Оставила как готовый черновик.\n"
            "Теперь можно нажать "
            "«Что публиковать дальше»."
        )

        return

    if query.data == "rewrite_draft":

        old_text = context.user_data.get(
            "draft_text",
            "",
        )

        await query.edit_message_reply_markup(
            reply_markup=None
        )

        await query.message.reply_text(
            "Переделываю…"
        )

        try:

            new_text = await ai_text(
                "Переделай этот пост для нашей "
                "личной страницы VK.\n"
                "Сделай естественнее и живее.\n"
                "Не добавляй новых фактов.\n"
                "Пиши только на хорошем русском языке. "
                "Не смешивай русский и английский.\n\n"
                + old_text
            )

            save_draft(
                context,
                new_text,
                context.user_data.get(
                    "draft_photo_ids",
                    [],
                ),
            )

            await send_long_text(
                query.message,
                new_text,
                reply_markup=draft_keyboard(),
            )

        except Exception:

            logger.exception(
                "Draft rewrite failed"
            )

            await query.message.reply_text(
                "Не получилось переделать пост."
            )


async def text_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not await guard(update):
        return

    message = update.effective_message
    user = update.effective_user

    if (
        message is None
        or user is None
        or not message.text
    ):
        return

    text = message.text.strip()

    detected_city = detect_city(
        text
    )

    if detected_city:

        await set_current_city(
            context,
            user.id,
            detected_city,
        )

        short_city_messages = {
            "нижний",
            "в нижнем",
            "я в нижнем",
            "сейчас в нижнем",
            "я сейчас в нижнем",
            "нижний новгород",
            "в нижнем новгороде",
            "я в нижнем новгороде",
            "я сейчас в нижнем новгороде",
            "мурманск",
            "в мурманске",
            "я в мурманске",
            "я сейчас в мурманске",
        }

        normalized = (
            text
            .lower()
            .replace("ё", "е")
            .strip()
        )

        if (
            normalized in short_city_messages
            or len(text) < 60
        ):

            await message.reply_text(
                "Запомнила: сейчас ты в "
                + city_in_phrase(detected_city)
                + ".\n\n"
                "Сразу выбираю одну задачу на сегодня…"
            )

            try:

                result = await build_today_task(
                    context,
                    user.id,
                )

                if result:

                    await send_long_text(
                        message,
                        result,
                    )

            except Exception:

                logger.exception(
                    "City update today task failed"
                )

                await message.reply_text(
                    "Город сохранила, но сейчас "
                    "не получилось подготовить задачу."
                )

            return

    current_city = await get_current_city(
        context,
        user.id,
    )

    prompt = (
        text
        + "\n\nОтвечай только на естественном русском языке. "
        "Не вставляй английские слова и не создавай "
        "смешанные русско-английские слова."
    )

    if current_city:

        prompt += (
            "\n\nСлужебный контекст менеджера: "
            "подтверждённый текущий город пользователя — "
            + current_city
            + ". Не спрашивай город повторно."
        )

    try:

        response = await ai_text(
            prompt
        )

        await send_long_text(
            message,
            response,
        )

    except Exception:

        logger.exception(
            "AI text request failed"
        )

        await message.reply_text(
            "Не удалось получить ответ от ИИ. "
            "Попробуй ещё раз."
        )


async def process_album_after_delay(
    media_group_id: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    message = None

    try:

        await asyncio.sleep(
            2.5
        )

        group = PHOTO_GROUPS.pop(
            media_group_id,
            None,
        )

        if not group:
            return

        file_ids = group[
            "file_ids"
        ]

        message = group[
            "message"
        ]

        caption = group.get(
            "caption",
            "",
        )

        user_id = group.get(
            "user_id"
        )

        current_city = ""

        if user_id:

            current_city = await get_current_city(
                context,
                user_id,
            )

        await message.reply_text(
            "Получила фотографий: "
            + str(len(file_ids))
            + ". Выбираю сильные кадры…"
        )

        text = await ai_post_from_photos(
            context,
            file_ids,
            caption,
            current_city,
        )

        save_draft(
            context,
            text,
            file_ids,
        )

        await send_long_text(
            message,
            text,
            reply_markup=draft_keyboard(),
        )

    except asyncio.CancelledError:

        return

    except Exception:

        logger.exception(
            "Album processing failed"
        )

        if message is not None:

            try:

                await message.reply_text(
                    "Не удалось обработать альбом."
                )

            except Exception:

                pass


async def photo_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not await guard(update):
        return

    message = update.effective_message
    user = update.effective_user

    if (
        message is None
        or user is None
        or not message.photo
    ):
        return

    file_id = (
        message.photo[-1].file_id
    )

    caption = (
        message.caption
        or ""
    )

    media_group_id = (
        message.media_group_id
    )

    if media_group_id:

        group = PHOTO_GROUPS.setdefault(
            media_group_id,
            {
                "file_ids": [],
                "task": None,
                "message": message,
                "caption": caption,
                "user_id": user.id,
            },
        )

        group[
            "file_ids"
        ].append(
            file_id
        )

        group[
            "message"
        ] = message

        group[
            "user_id"
        ] = user.id

        if caption:

            group[
                "caption"
            ] = caption

        old_task = group.get(
            "task"
        )

        if (
            old_task
            and not old_task.done()
        ):

            old_task.cancel()

        group[
            "task"
        ] = context.application.create_task(
            process_album_after_delay(
                media_group_id,
                context,
            )
        )

        return

    current_city = await get_current_city(
        context,
        user.id,
    )

    await message.reply_text(
        "Смотрю фото как контент-менеджер…"
    )

    try:

        text = await ai_post_from_photos(
            context,
            [file_id],
            caption,
            current_city,
        )

        save_draft(
            context,
            text,
            [file_id],
        )

        await send_long_text(
            message,
            text,
            reply_markup=draft_keyboard(),
        )

    except Exception:

        logger.exception(
            "Photo processing failed"
        )

        await message.reply_text(
            "Не удалось обработать фото."
        )


async def menu_button(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not await guard(update):
        return

    message = update.effective_message

    if (
        message is None
        or not message.text
    ):
        return

    text = message.text.strip()

    if text == MENU_TODAY:

        await today_command(
            update,
            context,
        )

    elif text == MENU_PLAN:

        await plan_command(
            update,
            context,
        )

    elif text == MENU_NEXT:

        await next_command(
            update,
            context,
        )

    elif text == MENU_STRATEGY:

        await strategy_command(
            update,
            context,
        )


async def unknown_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not await guard(update):
        return

    if update.effective_message:

        await update.effective_message.reply_text(
            "Не знаю такую команду. Нажми /help."
        )


async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    error = context.error

    if isinstance(
        error,
        (
            Conflict,
            NetworkError,
            TimedOut,
        ),
    ):

        logger.warning(
            "Transient Telegram error: %s",
            error,
        )

        return

    logger.error(
        "Error while processing update: %s",
        update,
        exc_info=error,
    )


async def set_bot_commands(
    application: Application,
) -> None:

    await application.bot.set_my_commands(
        BOT_COMMANDS
    )


def register_handlers(
    application: Application,
) -> None:

    application.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    application.add_handler(
        CommandHandler(
            "today",
            today_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "help",
            help_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "myid",
            myid,
        )
    )

    application.add_handler(
        CommandHandler(
            "ping",
            ping,
        )
    )

    application.add_handler(
        CommandHandler(
            "status",
            status_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "strategy",
            strategy_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "plan",
            plan_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "next",
            next_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "post",
            post_command,
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            draft_callback,
            pattern="^(keep_draft|rewrite_draft)$",
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Regex(
                "^("
                + MENU_TODAY
                + "|"
                + MENU_PLAN
                + "|"
                + MENU_NEXT
                + "|"
                + MENU_STRATEGY
                + ")$"
            ),
            menu_button,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.PHOTO,
            photo_message,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.COMMAND,
            unknown_command,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            text_message,
        )
    )