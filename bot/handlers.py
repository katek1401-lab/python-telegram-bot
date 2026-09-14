"""Telegram handlers for VK AI Manager."""

import asyncio
import base64
import logging
import os
import re
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
TASK_HISTORY_TABLE_READY_KEY = "task_history_table_ready"

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

VIDEO_MODEL = os.getenv(
    "OPENROUTER_VIDEO_MODEL",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
).strip()

ADMIN_TELEGRAM_ID = os.getenv(
    "ADMIN_TELEGRAM_ID",
    "",
).strip()

MAX_VIDEO_BYTES = 18 * 1024 * 1024


openai_client = AsyncOpenAI(
    api_key=OPENROUTER_API_KEY or "missing-key",
    base_url="https://openrouter.ai/api/v1",
    timeout=90.0,
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


CREATE_TASK_HISTORY_TABLE = """
CREATE TABLE IF NOT EXISTS vk_manager_task_history (
    id BIGSERIAL PRIMARY KEY,
    telegram_id BIGINT NOT NULL,
    task_text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


SYSTEM_PROMPT = """
Ты — VK AI Manager, личный AI-контент-менеджер пользователя.

Это личный авторский блог женщины и мамы,
жизнь которой связана с Мурманском и Нижним Новгородом.

Главная идея:
«Живая жизнь между двумя городами».

Это НЕ типичный мамский блог.

Главный герой страницы — сама автор.

Дети, семья, поездки, материнство и быт —
естественная часть жизни,
но не единственная тема.

ЦЕЛЬ

Органически развивать личную страницу ВКонтакте:

— увеличивать охваты;
— повышать вовлечённость;
— усиливать узнаваемость;
— формировать интерес к личности автора;
— постепенно увеличивать заинтересованную аудиторию.

Ты работаешь как инициативный контент-менеджер,
а не просто как генератор текста.

ЯЗЫК

Всегда отвечай на хорошем естественном русском языке.

Не смешивай русский и английский.

Не создавай гибридные или сломанные слова.

Перед отправкой ответа проверь:

1. Нет ли случайных иностранных слов.
2. Нет ли сломанных слов.
3. Звучит ли ответ естественно.
4. Нет ли лишнего профессионального жаргона.

НЕ ВЫДУМЫВАЙ ФАКТЫ

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
— конкретные события;
— места посещения;
— цитаты детей;
— планы семьи;
— длительность поездок;
— погоду;
— то, где пользователь находится.

Если текущий город передан как сохранённый,
считай его подтверждённым фактом.

Не спрашивай город повторно.

КОНТЕНТ

Если пользователь спрашивает:
«Что делать сегодня?»,
выбери ОДНУ лучшую задачу.

Не выдавай меню вариантов.

Не предлагай несколько идей на выбор.

РАЗНООБРАЗИЕ

Если тебе переданы предыдущие задания,
не повторяй их центральную механику.

Особенно не повторяй слишком часто:

— кофе;
— чашку;
— вид из окна;
— ноги;
— шаги;
— обычный маршрут;
— прогулку;
— селфи;
— отражение;
— тень;
— дверь;
— подъезд;
— туристическую достопримечательность просто как фон.

Ищи новый угол.

Чередуй:

— саму автора;
— её мнение;
— городской контекст;
— два города;
— семью;
— бытовой юмор;
— личные мысли;
— детали с историей;
— полезный реальный опыт;
— фотоистории;
— короткие видео;
— вовлекающие темы.

ФОТО И ВИДЕО

Анализируй только то,
что действительно видно или слышно.

Учитывай подпись пользователя.

Не устанавливай личности людей.

Не делай чувствительных выводов.

Не придумывай обстоятельства съёмки.

Если речь в видео слышна плохо —
скажи об этом прямо.

Не придумывай расшифровку речи.

Для видео оцени:

— есть ли сильный материал;
— что происходит;
— какой фрагмент лучше;
— что убрать;
— что сократить;
— подходит ли материал для клипа;
— подходит ли материал для обычного поста;
— нужен ли текст;
— нужен ли голос;
— нужны ли титры;
— зачем этот материал странице.

ТОН

Пиши живо, умно, современно и тепло.

Без пафоса.
Без рекламного канцелярита.
Без пустого кликбейта.
Без спама.
Без накрутки.

Не обещай гарантированный рост.

Ничего не публикуй автоматически.

Финальное решение всегда принимает пользователь.
""".strip()


HELP_TEXT = """
Я — VK AI Manager.

Я умею:

— помнить текущий город;
— помнить последние задания;
— выбирать одну задачу на сегодня;
— составлять планы;
— писать посты;
— анализировать фотографии;
— анализировать короткие видео;
— советовать, что оставить и что убрать.

Команды:

/today — одна задача на сегодня
/post тема — готовый пост
/plan — план на неделю
/strategy — стратегия развития
/next — следующий материал
/status — состояние бота
/myid — Telegram ID

Чтобы сменить город, напиши:

«Я теперь в Мурманске»

или

«Я сейчас в Нижнем Новгороде».

Можно присылать фото и короткие видео.

Ничего не публикуется без твоего решения.
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

    return bool(
        OPENROUTER_API_KEY
    )


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


async def ensure_task_history_table(
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:

    if context.bot_data.get(
        TASK_HISTORY_TABLE_READY_KEY
    ):
        return True

    pool = context.bot_data.get(
        DB_KEY
    )

    if pool is None:
        return False

    try:

        await pool.execute(
            CREATE_TASK_HISTORY_TABLE
        )

        context.bot_data[
            TASK_HISTORY_TABLE_READY_KEY
        ] = True

        return True

    except Exception:

        logger.exception(
            "Could not create task history table"
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

    if not await ensure_profile_table(
        context
    ):
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

    if not await ensure_profile_table(
        context
    ):
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


async def save_today_task(
    context: ContextTypes.DEFAULT_TYPE,
    telegram_id: int,
    task_text: str,
) -> None:

    if not await ensure_task_history_table(
        context
    ):
        return

    pool = context.bot_data.get(
        DB_KEY
    )

    if pool is None:
        return

    try:

        await pool.execute(
            """
            INSERT INTO vk_manager_task_history (
                telegram_id,
                task_text
            )
            VALUES ($1, $2);
            """,
            telegram_id,
            task_text,
        )

        await pool.execute(
            """
            DELETE FROM vk_manager_task_history
            WHERE telegram_id = $1
            AND id NOT IN (
                SELECT id
                FROM vk_manager_task_history
                WHERE telegram_id = $1
                ORDER BY created_at DESC, id DESC
                LIMIT 10
            );
            """,
            telegram_id,
        )

    except Exception:

        logger.exception(
            "Could not save today task"
        )


async def get_recent_tasks(
    context: ContextTypes.DEFAULT_TYPE,
    telegram_id: int,
) -> list[str]:

    if not await ensure_task_history_table(
        context
    ):
        return []

    pool = context.bot_data.get(
        DB_KEY
    )

    if pool is None:
        return []

    try:

        rows = await pool.fetch(
            """
            SELECT task_text
            FROM vk_manager_task_history
            WHERE telegram_id = $1
            ORDER BY created_at DESC, id DESC
            LIMIT 10;
            """,
            telegram_id,
        )

        return [
            str(row["task_text"])
            for row in rows
        ]

    except Exception:

        logger.exception(
            "Could not load recent tasks"
        )

        return []


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

    if normalized in {
        "нижний",
        "в нижнем",
        "я в нижнем",
        "сейчас в нижнем",
        "я сейчас в нижнем",
    }:
        return "Нижний Новгород"

    return None


def is_location_statement(
    text: str,
) -> bool:

    normalized = (
        text
        .lower()
        .replace("ё", "е")
        .strip(" .,!?:;")
    )

    if normalized in {
        "мурманск",
        "в мурманске",
        "нижний",
        "в нижнем",
        "нижний новгород",
        "в нижнем новгороде",
    }:
        return True

    phrases = (
        "я сейчас в ",
        "сейчас я в ",
        "я в ",
        "нахожусь в ",
        "я теперь в ",
        "теперь я в ",
        "сегодня я в ",
        "приехала в ",
        "вернулась в ",
    )

    return any(
        phrase in normalized
        for phrase in phrases
    )


def recent_repeat_signals(
    tasks: list[str],
) -> list[str]:

    if not tasks:
        return []

    joined = (
        " ".join(tasks)
        .lower()
        .replace("ё", "е")
    )

    groups = {
        "кофе или чашка": (
            "кофе",
            "чашк",
        ),
        "вид из окна": (
            "окн",
        ),
        "селфи": (
            "селфи",
        ),
        "ноги или шаги": (
            "ног",
            "шаг",
        ),
        "маршрут или прогулка": (
            "маршрут",
            "прогул",
        ),
        "отражение или тень": (
            "отражен",
            "тень",
        ),
        "дверь или подъезд": (
            "двер",
            "подъезд",
        ),
        "туристическая точка как фон": (
            "кремл",
            "чкалов",
            "набережн",
            "достопримеч",
        ),
    }

    signals = []

    for label, stems in groups.items():

        if any(
            stem in joined
            for stem in stems
        ):
            signals.append(
                label
            )

    return signals


def has_suspicious_latin(
    text: str,
) -> bool:

    cleaned = re.sub(
        r"https?://\S+",
        "",
        text,
    )

    cleaned = re.sub(
        r"\bVK\b",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    return bool(
        re.search(
            r"[A-Za-z]",
            cleaned,
        )
    )


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

    response = await openai_client.chat.completions.create(
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


async def rewrite_to_clean_russian(
    text: str,
) -> str:

    if not has_suspicious_latin(
        text
    ):
        return text

    try:

        cleaned = await ai_text(
            "Перепиши следующий ответ без изменения смысла.\n"
            "Оставь ту же структуру и эмодзи.\n"
            "Удали случайные английские и смешанные слова.\n"
            "Используй только грамотный русский язык.\n"
            "Не добавляй новых фактов.\n"
            "Слово VK можно оставить.\n\n"
            + text,
            model=FALLBACK_TEXT_MODEL,
        )

        return (
            cleaned
            or text
        )

    except Exception:

        logger.exception(
            "Russian cleanup failed"
        )

        return text


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
                "Ты получил фотографии "
                "для личной страницы ВКонтакте.\n\n"
                "Сохранённый текущий город пользователя: "
                + city_context
                + ".\n\n"
                "Не утверждай, что фотография сделана "
                "в этом городе, если это не видно "
                "и пользователь этого не написал.\n\n"
                "Проанализируй фотографии "
                "как контент-менеджер.\n"
                "Если фотографий несколько — "
                "выбери сильные кадры "
                "и лучший порядок.\n"
                "Не придумывай обстоятельства съёмки.\n"
                "Если материал подходит — "
                "создай один готовый пост.\n"
                "Если материал слабый — "
                "скажи, что лучше доснять.\n\n"
                "Пиши только на естественном русском языке.\n\n"
                "После текста напиши:\n"
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

        image_url = await telegram_photo_data_url(
            context,
            file_id,
        )

        content.append(
            {
                "type": "input_image",
                "image_url": image_url,
            }
        )

    response = await openai_client.responses.create(
        model=VISION_MODEL,
        instructions=SYSTEM_PROMPT,
        input=[
            {
                "role": "user",
                "content": content,
            }
        ],
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


async def telegram_video_data_url(
    context: ContextTypes.DEFAULT_TYPE,
    file_id: str,
    mime_type: str | None,
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

    mime = (
        mime_type
        or "video/mp4"
    ).lower()

    if mime not in {
        "video/mp4",
        "video/quicktime",
        "video/webm",
        "video/mpeg",
    }:

        mime = "video/mp4"

    return (
        f"data:{mime};base64,"
        f"{encoded}"
    )


async def ai_analyze_video(
    context: ContextTypes.DEFAULT_TYPE,
    file_id: str,
    mime_type: str | None,
    caption: str,
    current_city: str,
) -> str:

    video_url = await telegram_video_data_url(
        context,
        file_id,
        mime_type,
    )

    city_context = (
        current_city
        if current_city
        else "не указан"
    )

    prompt = (
        "Проанализируй присланное видео "
        "как личный контент-менеджер "
        "страницы ВКонтакте.\n\n"
        "Сохранённый текущий город пользователя: "
        + city_context
        + ".\n"
        "Не утверждай место съёмки "
        "только на основании сохранённого города.\n"
        "Опирайся только на то, "
        "что реально видно или слышно в видео, "
        "и на подпись пользователя.\n\n"
        "Не придумывай речь, события, людей, "
        "место или обстоятельства.\n"
        "Если речь слышна плохо — так и скажи.\n\n"
        "Ответ строго по-русски в формате:\n\n"
        "🎬 Вердикт\n"
        "Стоит использовать / лучше не использовать "
        "+ коротко почему.\n\n"
        "👀 Что в видео работает\n"
        "2–4 конкретных наблюдения.\n\n"
        "✂️ Что изменить\n"
        "Что обрезать, сократить или переставить.\n\n"
        "⭐ Лучший момент\n"
        "Опиши сильнейший фрагмент. "
        "Если можешь уверенно определить время — "
        "укажи его. Иначе не выдумывай секунды.\n\n"
        "📱 Как использовать в VK\n"
        "Клип, пост с видео или не публиковать — "
        "выбери один вариант.\n\n"
        "✍️ Текст\n"
        "Дай короткую готовую подпись "
        "только из известных фактов.\n\n"
        "💡 Зачем\n"
        "Одно предложение о роли материала "
        "в развитии страницы.\n\n"
        "Подпись пользователя к видео: "
        + (
            caption
            or "нет"
        )
    )

    response = await openai_client.chat.completions.create(
        model=VIDEO_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            SYSTEM_PROMPT
                            + "\n\n"
                            + prompt
                        ),
                    },
                    {
                        "type": "video_url",
                        "video_url": {
                            "url": video_url,
                        },
                    },
                ],
            }
        ],
    )

    text = extract_chat_text(
        response
    )

    if not text:

        raise RuntimeError(
            "Video model returned an empty response"
        )

    return await rewrite_to_clean_russian(
        text
    )


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

    recent_tasks = await get_recent_tasks(
        context,
        telegram_id,
    )

    repeat_signals = recent_repeat_signals(
        recent_tasks
    )

    history_text = ""

    if recent_tasks:

        history_text = (
            "\n\nПРЕДЫДУЩИЕ ЗАДАНИЯ.\n"
            "Новое задание не должно повторять "
            "их центральный сюжет или механику:\n\n"
        )

        for index, task in enumerate(
            recent_tasks,
            start=1,
        ):

            history_text += (
                f"{index}. "
                f"{task[:750]}\n\n"
            )

    blocked_text = ""

    if repeat_signals:

        blocked_text = (
            "\n\nВ ПОСЛЕДНИХ ЗАДАНИЯХ УЖЕ ВСТРЕЧАЛИСЬ:\n— "
            + "\n— ".join(
                repeat_signals
            )
            + "\nНе используй эти элементы "
            "в новом задании, "
            "если без них можно обойтись."
        )

    prompt = (
        "Ты личный контент-менеджер "
        "и сам принимаешь решение.\n\n"
        "Подтверждённый текущий город пользователя: "
        + city
        + ".\n"
        "Не спрашивай город снова.\n\n"
        "Выбери ОДНУ конкретную задачу на сегодня "
        "для развития личной страницы VK.\n\n"
        "Не предлагай несколько вариантов.\n"
        "Не заканчивай вопросом.\n"
        "Не придумывай события, погоду, "
        "планы семьи или посещённые места.\n"
        "Не отправляй пользователя специально "
        "к достопримечательности только ради фона.\n"
        "Задача должна быть выполнима телефоном.\n\n"
        "Не используй по умолчанию кофе, окно, ноги, "
        "маршрут, селфи, отражение, тень, дверь "
        "или подъезд.\n\n"
        "Ответ строго в формате:\n\n"
        "🎯 Сегодня\n"
        "Одна конкретная идея.\n\n"
        "📸 Сними\n"
        "3–4 конкретных кадра или видео.\n\n"
        "🖼 Если момент уже прошёл\n"
        "Что поискать в галерее.\n\n"
        "📤 Потом пришли мне\n"
        "Что именно отправить боту.\n\n"
        "💡 Зачем\n"
        "Одна короткая причина.\n"
        + blocked_text
        + history_text
    )

    result = await ai_text(
        prompt
    )

    result = await rewrite_to_clean_russian(
        result
    )

    await save_today_task(
        context,
        telegram_id,
        result,
    )

    return result


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

    recent_tasks = await get_recent_tasks(
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
            "\n\nТекущий город пока не сохранён."
        )

    memory_line = (
        "\nПамять заданий: "
        + str(len(recent_tasks))
        + "/10."
    )

    await message.reply_text(
        "Привет! Я VK AI Manager.\n\n"
        "Я работаю как менеджер твоей личной страницы VK.\n"
        "Теперь я умею анализировать "
        "фотографии и короткие видео."
        + city_line
        + memory_line,
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

    recent_tasks = await get_recent_tasks(
        context,
        user.id,
    )

    await message.reply_text(
        "ИИ OpenRouter: "
        + (
            "✅"
            if ai_ready()
            else "❌"
        )
        + "\nЗакрытый доступ: "
        + (
            "✅"
            if ADMIN_TELEGRAM_ID
            else "⚠️"
        )
        + "\nТекущий город: "
        + (
            city
            or "не указан"
        )
        + "\nПамять заданий: "
        + str(len(recent_tasks))
        + "/10"
        + "\nАнализ фото: ✅"
        + "\nАнализ коротких видео: ✅"
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
        "Проверяю предыдущие задания "
        "и выбираю новое…"
    )

    try:

        result = await build_today_task(
            context,
            user.id,
        )

        if not result:

            await message.reply_text(
                "Сначала скажи, "
                "в каком городе ты сейчас."
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
            "этой личной страницы VK на 30 дней.\n"
            "Не выдумывай события жизни.\n"
            "Дай рубрики, форматы, частоту, "
            "гипотезы роста, принципы отбора "
            "фото и видео и план первых 7 дней.\n"
            "Пиши естественным русским языком."
        )

        if city:

            prompt += (
                "\nТекущий город пользователя: "
                + city
                + ". Не спрашивай его снова."
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
            "Не получилось составить стратегию."
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

    city = await get_current_city(
        context,
        user.id,
    )

    recent_tasks = await get_recent_tasks(
        context,
        user.id,
    )

    await message.reply_text(
        "Составляю план на неделю…"
    )

    try:

        prompt = (
            "Составь контент-план на 7 дней "
            "для этой личной страницы VK.\n"
            "Не выдумывай события будущей недели.\n"
            "Чередуй разные типы контента.\n"
            "Не повторяй одинаковые механики.\n"
            "Можно оставить дни без публикации.\n"
            "Учитывай фото и короткие видео.\n"
            "Пиши естественным русским языком."
        )

        if city:

            prompt += (
                "\nТекущий город: "
                + city
                + "."
            )

        if recent_tasks:

            prompt += (
                "\n\nПоследние задания. "
                "Не повторяй их буквально:\n"
            )

            for task in recent_tasks[
                :7
            ]:

                prompt += (
                    "\n— "
                    + task[:500]
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

    recent_tasks = await get_recent_tasks(
        context,
        user.id,
    )

    prompt = (
        "Выбери ОДИН лучший следующий материал "
        "для личной страницы VK.\n"
        "Не давай меню вариантов.\n"
        "Не выдумывай события.\n"
        "Не повторяй последние задания.\n"
        "Дай цель, формат, что снять "
        "или найти в галерее и зачем это нужно.\n"
        "Пиши естественным русским языком."
    )

    if city:

        prompt += (
            "\nТекущий город: "
            + city
            + "."
        )

    if recent_tasks:

        prompt += (
            "\n\nПоследние задания:\n"
        )

        for task in recent_tasks[
            :5
        ]:

            prompt += (
                "\n— "
                + task[:500]
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
            "Next recommendation failed"
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
            "Создай один готовый пост "
            "для личной страницы ВКонтакте.\n"
            "Тема пользователя: "
            + topic
            + ".\n"
            "Не придумывай факты.\n"
            "Пиши естественным русским языком."
        )

        if city:

            prompt += (
                "\nТекущий город: "
                + city
                + ". Используй только если уместно."
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
            "✅ Оставила как готовый черновик."
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
                "Переделай этот текст.\n"
                "Сделай естественнее.\n"
                "Не добавляй новых фактов.\n"
                "Пиши только по-русски.\n\n"
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
                "Не получилось переделать."
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

    if (
        detected_city
        and is_location_statement(text)
    ):

        await set_current_city(
            context,
            user.id,
            detected_city,
        )

        await message.reply_text(
            "Запомнила: сейчас ты в "
            + city_in_phrase(
                detected_city
            )
            + ".\n\n"
            "Проверяю предыдущие задания "
            "и выбираю новое…"
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
                "Город сохранила, "
                "но не получилось подготовить задачу."
            )

        return

    current_city = await get_current_city(
        context,
        user.id,
    )

    prompt = (
        text
        + "\n\nОтвечай только "
        "естественным русским языком."
    )

    if current_city:

        prompt += (
            "\nТекущий подтверждённый город пользователя: "
            + current_city
            + ". Не спрашивай его снова."
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
            "Не удалось получить ответ от ИИ."
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

    file_id = message.photo[
        -1
    ].file_id

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


async def video_message(
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
        or message.video is None
    ):
        return

    video = message.video

    caption = (
        message.caption
        or ""
    )

    if (
        video.file_size
        and video.file_size
        > MAX_VIDEO_BYTES
    ):

        await message.reply_text(
            "Видео слишком большое "
            "для первого варианта анализа.\n\n"
            "Пришли более короткий фрагмент — "
            "лучше до 18 МБ."
        )

        return

    current_city = await get_current_city(
        context,
        user.id,
    )

    await message.reply_text(
        "Смотрю видео: кадры, движение и звук. "
        "Это может занять чуть дольше, "
        "чем анализ фото…"
    )

    try:

        result = await ai_analyze_video(
            context,
            video.file_id,
            video.mime_type,
            caption,
            current_city,
        )

        save_draft(
            context,
            result,
        )

        await send_long_text(
            message,
            result,
            reply_markup=draft_keyboard(),
        )

    except Exception:

        logger.exception(
            "Video processing failed"
        )

        await message.reply_text(
            "Не получилось разобрать это видео.\n\n"
            "Для первого теста попробуй "
            "короткий ролик MP4 из галереи, "
            "лучше до 18 МБ."
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
            filters.VIDEO,
            video_message,
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