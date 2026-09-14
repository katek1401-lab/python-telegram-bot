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
    ("help", "Что умеет бот"),
    ("status", "Проверить подключения"),
    ("myid", "Показать мой Telegram ID"),
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


HELP_TEXT = """
Я — VK AI Manager.

Я работаю как контент-менеджер твоей личной страницы ВКонтакте.

Главная концепция страницы:
авторский блог живой мамы между Мурманском и Нижним Новгородом.

В центре страницы — ты сама.
Дети, два города, поездки, быт, эмоции и семья — естественная часть жизни,
но не единственная тема блога.

Я умею:

• говорить, что лучше сделать сегодня;
• придумывать стратегию роста;
• составлять контент-планы;
• создавать готовые посты;
• анализировать одну фотографию или альбом;
• выбирать сильные фотографии;
• предлагать следующий материал;
• придумывать идеи клипов, фото и историй;
• корректировать контент по статистике.

Команды:

/today — что сегодня снять, прислать и подготовить
/post тема — готовый пост
/plan — план на 7 дней
/strategy — стратегия роста
/next — что публиковать следующим
/status — проверка ИИ
/myid — твой Telegram ID

Можно просто писать мне обычным сообщением или присылать фотографии.

Я не должен выдумывать факты твоей жизни.
Я ничего не публикую автоматически без твоего подтверждения.
""".strip()


SYSTEM_PROMPT = """
Ты — VK AI Manager, личный AI-контент-менеджер пользователя.

ТЫ УЖЕ ЗНАЕШЬ ПОЗИЦИОНИРОВАНИЕ СТРАНИЦЫ.

Это личный авторский блог женщины и мамы,
жизнь которой связана с Мурманском и Нижним Новгородом.

Главная идея:

«Живая жизнь между двумя городами».

Это НЕ типичный мамский блог.
Это личная страница самой женщины.

Она — главный герой страницы.

Дети, семья, поездки, быт и материнство —
естественная часть её жизни и контента,
но дети не должны становиться единственными героями страницы.

Сильные направления:

— жизнь между Мурманском и Нижним Новгородом;
— контраст двух городов, климата, ритма и быта;
— настоящая повседневность без постановочной идеальности;
— материнство как часть жизни, а не единственная тема;
— сама автор: мысли, настроение, характер, выборы, привычки;
— семейные и тёплые моменты;
— юмор из реальной жизни;
— поездки, сборы, дороги и перемещения между городами;
— красивые обычные моменты;
— полезные материалы только на основе реального опыта;
— фотографии и видео из реальной жизни.

Твоя главная цель —
помогать органически развивать личную страницу ВКонтакте:
увеличивать охваты, вовлечённость, узнаваемость
и число заинтересованных подписчиков.

Ты не просто генератор текста.
Ты работаешь как инициативный контент-менеджер.

ВАЖНО:

Никогда не выдумывай факты из жизни пользователя.

Нельзя самостоятельно придумывать:

— цены;
— суммы;
— профессии;
— возраст детей;
— имена;
— покупки;
— конкретные события;
— места, где человек якобы был;
— длительность поездок;
— даты;
— цитаты детей;
— проблемы в семье;
— медицинские факты;
— рабочие ситуации;
— истории, которые пользователь не рассказывал.

Например, нельзя утверждать:
«мы купили игрушку за 3000 рублей»
или
«ребёнок сказал такую-то фразу»,
если пользователь этого не сообщал.

Если тебе нужна конкретная деталь,
либо обойди её,
либо обозначь как идею,
либо задай один короткий вопрос.

Если анализируешь фотографию —
используй только то, что действительно видно на фотографии
и то, что пользователь написал сам.

Не устанавливай личности людей на фотографии
и не делай чувствительных выводов о них.

ТЫ ДОЛЖЕН ПРОЯВЛЯТЬ ИНИЦИАТИВУ.

Не жди, пока пользователь сам придумает тему.

Предлагай:

— что снять сегодня;
— что сфотографировать;
— какой момент сохранить на видео;
— какие фотографии из галереи поискать;
— какой формат выбрать;
— что опубликовать следующим;
— зачем именно этот материал нужен странице.

Чередуй контент.

Не превращай страницу в бесконечные одинаковые фото детей.

Используй баланс:

1. сама автор;
2. жизнь двух городов;
3. семья и дети;
4. бытовой юмор;
5. личные мысли;
6. красивые повседневные моменты;
7. полезный реальный опыт;
8. вовлекающие публикации;
9. короткие видео и клипы;
10. фотоистории.

Не требуй публиковать каждый день любой ценой.
Иногда пауза лучше слабого поста.

Для готового поста:

1. сильная первая строка;
2. естественный текст;
3. CTA только если уместен;
4. 0–5 уместных хэштегов;
5. коротко укажи:
   «Зачем этот пост: ...»

Для рекомендаций контента думай не только:
«что красиво»,
но и:
«зачем подписчику смотреть это».

Избегай:

— пафоса;
— канцелярита;
— фальшивой мотивации;
— слишком рекламного тона;
— клише про «идеальную маму»;
— выдуманных драм;
— кликбейта без содержания;
— спама;
— накрутки.

Пиши по-русски.
Тон — живой, умный, тёплый, современный.

Не выдавай пользователю десять вариантов,
если можно выбрать один сильный.

Если информации недостаточно,
сначала сделай лучший разумный вариант.

Максимум один короткий уточняющий вопрос за раз.

Не обещай гарантированный рост или вирусность.

Ничего не публикуй автоматически.
Финальное решение всегда принимает пользователь.
""".strip()


PHOTO_GROUPS: dict[str, dict[str, Any]] = {}


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


async def send_long_text(
    message,
    text: str,
    reply_markup=None,
) -> None:

    text = (text or "").strip()

    if not text:
        await message.reply_text(
            "ИИ вернул пустой ответ. Попробуй ещё раз."
        )
        return

    parts = [
        text[i:i + 3900]
        for i in range(0, len(text), 3900)
    ]

    for index, part in enumerate(parts):

        markup = (
            reply_markup
            if index == len(parts) - 1
            else None
        )

        await message.reply_text(
            part,
            reply_markup=markup,
        )


def extract_chat_text(response) -> str:

    if not response.choices:
        return ""

    message = response.choices[0].message

    if message is None:
        return ""

    content = message.content

    if isinstance(content, str):
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

    return extract_chat_text(response)


async def ai_text(
    prompt: str,
    model: str | None = None,
) -> str:

    if not ai_ready():
        raise RuntimeError(
            "OPENROUTER_API_KEY is not configured"
        )

    primary_model = model or TEXT_MODEL

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

    if primary_model == FALLBACK_TEXT_MODEL:
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
    ).decode("utf-8")

    return (
        "data:image/jpeg;base64,"
        + encoded
    )


async def ai_post_from_photos(
    context: ContextTypes.DEFAULT_TYPE,
    file_ids: list[str],
    user_caption: str = "",
) -> str:

    content: list[dict[str, Any]] = [
        {
            "type": "input_text",
            "text": (
                "Ты получил фотографии пользователя "
                "для её личной страницы ВКонтакте. "
                "Проанализируй их как контент-менеджер. "
                "Не придумывай события, которых не видно "
                "и о которых пользователь не сообщил. "
                "Если фотографий несколько — сравни их, "
                "выбери самые сильные и лучший порядок. "
                "Создай один готовый пост, если материал "
                "действительно подходит для публикации. "
                "Если сейчас лучше не публиковать — "
                "честно скажи это и предложи, что доснять. "
                "После текста добавь коротко:\n"
                "Лучшие фото: ...\n"
                "Почему: ...\n"
                "Что следующим: ...\n"
                "Комментарий пользователя: "
                + (
                    user_caption
                    or "нет"
                )
            ),
        }
    ]

    for file_id in file_ids[:10]:

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
        file_ids or []
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


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not await guard(update):
        return

    message = update.effective_message
    user = update.effective_user

    if message is None or user is None:
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

    await message.reply_text(
        "Привет! Я VK AI Manager.\n\n"
        "Я работаю как менеджер твоей личной страницы VK.\n\n"
        "Я уже знаю основную концепцию: "
        "живой авторский блог между Мурманском "
        "и Нижним Новгородом, где в центре — ты сама, "
        "а семья, дети, поездки и быт — естественная "
        "часть твоей жизни.\n\n"
        "Нажми «Что делать сегодня», "
        "и я сам предложу следующий шаг.",
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

        if cached:

            await message.reply_text(
                "pong (cached)"
            )

        else:

            await message.reply_text(
                "pong (fresh)"
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

    if message is None:
        return

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

    await message.reply_text(
        "ИИ OpenRouter: "
        + ai
        + "\nЗакрытый доступ: "
        + lock
        + "\n\n"
        "Основная концепция страницы: ✅\n"
        "Резервная бесплатная AI-модель: ✅\n"
        "Автоматическая публикация в VK: пока выключена."
    )


async def today_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not await guard(update):
        return

    message = update.effective_message

    if message is None:
        return

    await message.reply_text(
        "Смотрю, что лучше сделать сегодня…"
    )

    last_plan = context.user_data.get(
        "last_plan",
        "",
    )

    last_draft = context.user_data.get(
        "draft_text",
        "",
    )

    prompt = """
Ты начинаешь рабочий день как личный контент-менеджер.

Скажи пользователю, что конкретно сделать сегодня
для развития её личной страницы VK.

Не пиши общий контент-план.

Выбери ОДНУ основную задачу на сегодня.

Ответ должен быть коротким и практичным:

🎯 Сегодня:
одна главная идея.

📸 Что снять:
2–4 конкретных кадра или коротких видео,
которые реально можно снять обычным телефоном.

🖼 Если снимать нечего:
скажи, какие фотографии поискать в галерее.

✍️ Что я потом сделаю:
что пользователь должен прислать тебе,
чтобы ты подготовил материал.

💡 Зачем:
какую задачу роста решает этот контент.

Не выдумывай события сегодняшнего дня.
Не утверждай, где сейчас находится пользователь.
Не придумывай планы семьи.

Если для сильной идеи нужно знать,
в каком из двух городов пользователь сейчас находится,
можешь задать ОДИН короткий вопрос вместо выдумывания.
""".strip()

    if last_plan:

        prompt += (
            "\n\nПоследний сохранённый недельный план:\n"
            + last_plan[:3000]
        )

    if last_draft:

        prompt += (
            "\n\nПоследний подготовленный материал:\n"
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

    if message is None:
        return

    await message.reply_text(
        "Готовлю стратегию роста…"
    )

    try:

        result = await ai_text(
            "Составь практичную стратегию развития "
            "этой конкретной личной страницы ВКонтакте "
            "на ближайшие 30 дней. "
            "Не предлагай абстрактные темы вроде "
            "'если вы врач' или 'если вы работаете в IT'. "
            "Ты уже знаешь позиционирование страницы. "
            "Опирайся на блог женщины между "
            "Мурманском и Нижним Новгородом, "
            "на её личность, семью, бытовую жизнь, "
            "два города и живой авторский формат. "
            "Дай рубрики, форматы, частоту, "
            "гипотезы роста, принципы отбора фото "
            "и план первых 7 дней. "
            "Не выдумывай конкретные события её жизни."
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
            "Бесплатные AI-модели сейчас "
            "не дали нормальный ответ. "
            "Попробуй ещё раз чуть позже."
        )


async def plan_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not await guard(update):
        return

    message = update.effective_message

    if message is None:
        return

    topic = " ".join(
        context.args
    ).strip()

    await message.reply_text(
        "Составляю план на неделю…"
    )

    try:

        result = await ai_text(
            "Составь практичный контент-план "
            "на 7 дней именно для этой личной страницы VK. "
            "Учитывай постоянное позиционирование. "
            "Не придумывай события, которые якобы "
            "обязательно произойдут. "
            "Если идея зависит от ситуации, "
            "формулируй её как вариант: "
            "'если сегодня будет прогулка — сними...' "
            "Чередуй: саму автора, два города, "
            "семью, юмор, личные мысли, "
            "визуальные истории и полезный реальный опыт. "
            "Для каждого материала укажи: "
            "цель, формат, что снять или найти в галерее, "
            "первую строку и зачем это странице. "
            "Можно оставить 1–2 дня без публикации. "
            "Дополнительная тема пользователя: "
            + (
                topic
                or "не указана"
            )
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

    if message is None:
        return

    last_plan = context.user_data.get(
        "last_plan",
        "",
    )

    last_draft = context.user_data.get(
        "draft_text",
        "",
    )

    prompt = (
        "Как контент-менеджер выбери ОДИН лучший "
        "следующий материал для этой личной страницы VK. "
        "Учитывай постоянное позиционирование. "
        "Не выдумывай события. "
        "Дай: цель, формат, что снять или найти в галерее, "
        "пример первой строки и почему сейчас нужен именно "
        "этот материал."
    )

    if last_plan:

        prompt += (
            "\nПоследний недельный план:\n"
            + last_plan[:4000]
        )

    if last_draft:

        prompt += (
            "\nПоследний подготовленный материал:\n"
            + last_draft[:2000]
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

    if message is None:
        return

    topic = " ".join(
        context.args
    ).strip()

    if not topic:

        await message.reply_text(
            "Напиши тему после команды.\n\n"
            "Например:\n"
            "/post дорога с детьми"
        )

        return

    await message.reply_text(
        "Готовлю пост…"
    )

    try:

        text = await ai_text(
            "Создай один готовый пост "
            "для этой личной страницы ВКонтакте. "
            "Тема пользователя: "
            + topic
            + ". Учитывай постоянное позиционирование. "
            "Не придумывай никаких деталей жизни, "
            "которых пользователь не сообщил. "
            "Если тема слишком общая — "
            "пиши так, чтобы текст можно было "
            "адаптировать под реальный момент."
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
            "✅ Оставила как готовый черновик.\n\n"
            "Когда захочешь продолжить — "
            "нажми «Что публиковать дальше»."
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
                "конкретной личной страницы VK. "
                "Сделай его естественнее, живее "
                "и менее шаблонным. "
                "Не добавляй новых фактов, "
                "которых нет в исходном тексте.\n\n"
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

    if (
        message is None
        or not message.text
    ):
        return

    try:

        response = await ai_text(
            message.text
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
            "Не удалось получить ответ "
            "от ИИ. Попробуй ещё раз."
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

        await message.reply_text(
            "Получила фотографий: "
            + str(
                len(file_ids)
            )
            + ". Смотрю их как контент-менеджер…"
        )

        text = await ai_post_from_photos(
            context,
            file_ids,
            caption,
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

    if (
        message is None
        or not message.photo
    ):
        return

    file_id = (
        message.photo[-1].file_id
    )

    caption = (
        message.caption or ""
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
            },
        )

        group["file_ids"].append(
            file_id
        )

        group["message"] = message

        if caption:

            group["caption"] = caption

        old_task = group.get(
            "task"
        )

        if (
            old_task
            and not old_task.done()
        ):

            old_task.cancel()

        group["task"] = (
            context.application.create_task(
                process_album_after_delay(
                    media_group_id,
                    context,
                )
            )
        )

        return

    await message.reply_text(
        "Смотрю фото как контент-менеджер…"
    )

    try:

        text = await ai_post_from_photos(
            context,
            [file_id],
            caption,
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
            "Не знаю такую команду. "
            "Нажми /help."
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