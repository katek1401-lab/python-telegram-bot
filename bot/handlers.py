"""Telegram handlers for VK AI Manager."""

import asyncio
import base64
import logging
import os
from typing import Any

import httpx
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

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()

TEXT_MODEL = os.getenv(
    "OPENROUTER_TEXT_MODEL",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
).strip()

VISION_MODEL = os.getenv(
    "OPENROUTER_VISION_MODEL",
    "openrouter/free",
).strip()

VK_ACCESS_TOKEN = os.getenv("VK_ACCESS_TOKEN", "").strip()
VK_GROUP_ID = os.getenv("VK_GROUP_ID", "").strip()
VK_API_VERSION = os.getenv("VK_API_VERSION", "5.199").strip()

ADMIN_TELEGRAM_ID = os.getenv(
    "ADMIN_TELEGRAM_ID",
    "",
).strip()


openai_client = AsyncOpenAI(
    api_key=OPENROUTER_API_KEY or "missing-key",
    base_url="https://openrouter.ai/api/v1",
)


BOT_COMMANDS = (
    ("start", "Главное меню"),
    ("help", "Что умеет бот"),
    ("myid", "Показать мой Telegram ID"),
    ("post", "Создать пост"),
    ("plan", "Контент-план"),
    ("publish", "Опубликовать черновик"),
    ("stats", "Статистика VK"),
    ("status", "Проверить подключения"),
    ("ping", "Проверить бота"),
)


MENU_HELP = "Помощь"
MENU_PLAN = "План на неделю"
MENU_STATUS = "Статус"


MAIN_MENU_KEYBOARD = ReplyKeyboardMarkup(
    [
        [MENU_HELP, MENU_PLAN],
        [MENU_STATUS],
    ],
    resize_keyboard=True,
    is_persistent=True,
    input_field_placeholder="Напиши задачу для VK AI Manager",
)


HELP_TEXT = """
Я — VK AI Manager.

Что я умею:

/post тема
Создать готовый пост.

/plan
Составить контент-план на 7 дней,
по 2 поста в день.

/stats
Проанализировать последние посты VK.

/publish
Опубликовать последний черновик.

/status
Проверить подключения.

/myid
Показать твой Telegram ID.

Можно просто писать мне текстом.

Можно присылать одну фотографию
или несколько фотографий одним альбомом.

Я подготовлю пост по фотографиям.

ВАЖНО:
Я не публикую ничего без твоего
явного подтверждения.
""".strip()


SYSTEM_PROMPT = (
    "Ты — VK AI Manager, русскоязычный "
    "контент-менеджер сообщества ВКонтакте. "
    "Помогай создавать посты, заголовки, CTA, "
    "рубрики, контент-планы и идеи визуалов. "
    "Пиши естественно и без лишней воды. "
    "Не выдумывай факты о пользователе или бизнесе. "
    "Если информации мало, делай нейтральный вариант. "
    "Ничего не публикуй без явного подтверждения пользователя."
)


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


def publish_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Опубликовать в VK",
                    callback_data="publish_draft",
                ),
                InlineKeyboardButton(
                    "❌ Отмена",
                    callback_data="cancel_draft",
                ),
            ]
        ]
    )


def ai_ready() -> bool:
    return bool(OPENROUTER_API_KEY)


def vk_ready() -> bool:
    return bool(
        VK_ACCESS_TOKEN
        and VK_GROUP_ID
    )


async def ai_text(
    prompt: str,
    model: str | None = None,
) -> str:

    if not ai_ready():
        raise RuntimeError(
            "OPENROUTER_API_KEY is not configured"
        )

    response = await openai_client.responses.create(
        model=model or TEXT_MODEL,
        instructions=SYSTEM_PROMPT,
        input=prompt,
    )

    return (
        response.output_text or ""
    ).strip()


async def telegram_photo_data_url(
    context: ContextTypes.DEFAULT_TYPE,
    file_id: str,
) -> str:

    tg_file = await context.bot.get_file(file_id)

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
                "Изучи фотографии и создай "
                "ОДИН готовый пост для ВКонтакте. "
                "Если фотографий несколько, "
                "выбери самые сильные и учти общий сюжет. "
                "Пост должен быть готов к публикации: "
                "сильное начало, основной текст, "
                "мягкий CTA и только уместные хэштеги. "
                "Не пиши служебный анализ. "
                "Комментарий пользователя: "
                + (user_caption or "нет")
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

    return (
        response.output_text or ""
    ).strip()


async def vk_api(
    method: str,
    params: dict[str, Any] | None = None,
) -> Any:

    if not vk_ready():
        raise RuntimeError(
            "VK is not configured"
        )

    payload = dict(
        params or {}
    )

    payload["access_token"] = (
        VK_ACCESS_TOKEN
    )

    payload["v"] = VK_API_VERSION

    async with httpx.AsyncClient(
        timeout=30.0
    ) as client:

        response = await client.post(
            "https://api.vk.com/method/"
            + method,
            data=payload,
        )

        response.raise_for_status()

        data = response.json()

    if "error" in data:

        error = data["error"]

        raise RuntimeError(
            "VK API error "
            + str(error.get("error_code"))
            + ": "
            + str(error.get("error_msg"))
        )

    return data.get("response")


async def upload_photo_to_vk(
    context: ContextTypes.DEFAULT_TYPE,
    file_id: str,
) -> str:

    group_id = abs(
        int(VK_GROUP_ID)
    )

    upload = await vk_api(
        "photos.getWallUploadServer",
        {
            "group_id": group_id,
        },
    )

    upload_url = upload[
        "upload_url"
    ]

    tg_file = await context.bot.get_file(
        file_id
    )

    raw = bytes(
        await tg_file.download_as_bytearray()
    )

    async with httpx.AsyncClient(
        timeout=60.0
    ) as client:

        response = await client.post(
            upload_url,
            files={
                "photo": (
                    "telegram.jpg",
                    raw,
                    "image/jpeg",
                )
            },
        )

        response.raise_for_status()

        uploaded = response.json()

    saved = await vk_api(
        "photos.saveWallPhoto",
        {
            "group_id": group_id,
            "server": uploaded["server"],
            "photo": uploaded["photo"],
            "hash": uploaded["hash"],
        },
    )

    photo = saved[0]

    return (
        "photo"
        + str(photo["owner_id"])
        + "_"
        + str(photo["id"])
    )


async def publish_to_vk(
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    file_ids: list[str] | None = None,
) -> Any:

    attachments: list[str] = []

    for file_id in (
        file_ids or []
    )[:10]:

        attachment = (
            await upload_photo_to_vk(
                context,
                file_id,
            )
        )

        attachments.append(
            attachment
        )

    params: dict[str, Any] = {
        "owner_id": -abs(
            int(VK_GROUP_ID)
        ),
        "from_group": 1,
        "message": text,
    }

    if attachments:
        params["attachments"] = (
            ",".join(attachments)
        )

    return await vk_api(
        "wall.post",
        params,
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
        file_ids or []
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
        "Я могу готовить посты, "
        "контент-планы, анализировать "
        "фотографии и публиковать "
        "одобренные тобой материалы в VK.",
        reply_markup=MAIN_MENU_KEYBOARD,
    )


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not await guard(update):
        return

    if update.effective_message:

        await update.effective_message.reply_text(
            HELP_TEXT
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

    vk = (
        "✅"
        if vk_ready()
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
        + "\nVK: "
        + vk
        + "\nЗакрытый доступ: "
        + lock
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

    prompt = (
        "Составь контент-план "
        "для сообщества ВКонтакте "
        "на 7 дней: по 2 поста в день. "
        "Для каждого поста укажи тему, "
        "цель, короткий хук, "
        "идею визуала и CTA. "
        "Сбалансируй вовлечение, "
        "пользу, доверие и продажи. "
        "Тематика пользователя: "
        + (
            topic
            or "не указана"
        )
    )

    await message.reply_text(
        "Составляю план…"
    )

    try:

        result = await ai_text(
            prompt
        )

        await message.reply_text(
            result
        )

    except Exception:

        logger.exception(
            "Content plan generation failed"
        )

        await message.reply_text(
            "Не получилось составить план."
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
            "/post осенняя прогулка с ребёнком"
        )

        return

    await message.reply_text(
        "Готовлю пост…"
    )

    try:

        text = await ai_text(
            "Создай один полностью готовый "
            "пост для ВКонтакте. "
            "Нужны сильное начало, "
            "основной текст, CTA "
            "и только уместные хэштеги. "
            "Тема: "
            + topic
        )

        save_draft(
            context,
            text,
        )

        await message.reply_text(
            text,
            reply_markup=publish_keyboard(),
        )

    except Exception:

        logger.exception(
            "Post generation failed"
        )

        await message.reply_text(
            "Не получилось создать пост."
        )


async def publish_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not await guard(update):
        return

    message = update.effective_message

    if message is None:
        return

    text = context.user_data.get(
        "draft_text"
    )

    if not text:

        await message.reply_text(
            "Сначала создай черновик "
            "через /post или отправь фото."
        )

        return

    await message.reply_text(
        "Опубликовать последний "
        "черновик в VK?",
        reply_markup=publish_keyboard(),
    )


async def publish_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not await guard(update):
        return

    query = update.callback_query

    if query is None:
        return

    await query.answer()

    if query.data == "cancel_draft":

        await query.edit_message_reply_markup(
            reply_markup=None
        )

        await query.message.reply_text(
            "Публикация отменена."
        )

        return

    if query.data != "publish_draft":
        return

    if not vk_ready():

        await query.message.reply_text(
            "VK ещё не подключён.\n\n"
            "Нужно добавить в Railway:\n"
            "VK_ACCESS_TOKEN\n"
            "VK_GROUP_ID"
        )

        return

    text = context.user_data.get(
        "draft_text"
    )

    file_ids = context.user_data.get(
        "draft_photo_ids",
        [],
    )

    if not text:

        await query.message.reply_text(
            "Черновик не найден."
        )

        return

    await query.edit_message_reply_markup(
        reply_markup=None
    )

    await query.message.reply_text(
        "Публикую в VK…"
    )

    try:

        result = await publish_to_vk(
            context,
            text,
            file_ids,
        )

        if isinstance(
            result,
            dict,
        ):
            post_id = result.get(
                "post_id"
            )
        else:
            post_id = result

        await query.message.reply_text(
            "✅ Опубликовано в VK.\n"
            "Post ID: "
            + str(post_id)
        )

    except Exception as exc:

        logger.exception(
            "VK publish failed"
        )

        await query.message.reply_text(
            "Не удалось опубликовать в VK:\n"
            + str(exc)
        )


async def stats_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if not await guard(update):
        return

    message = update.effective_message

    if message is None:
        return

    if not vk_ready():

        await message.reply_text(
            "Сначала подключим VK."
        )

        return

    await message.reply_text(
        "Смотрю статистику "
        "последних постов…"
    )

    try:

        data = await vk_api(
            "wall.get",
            {
                "owner_id": -abs(
                    int(VK_GROUP_ID)
                ),
                "count": 20,
            },
        )

        rows = []

        for item in data.get(
            "items",
            [],
        ):

            rows.append(
                {
                    "id": item.get("id"),
                    "text": (
                        item.get("text")
                        or ""
                    )[:500],
                    "likes": item.get(
                        "likes",
                        {},
                    ).get(
                        "count",
                        0,
                    ),
                    "comments": item.get(
                        "comments",
                        {},
                    ).get(
                        "count",
                        0,
                    ),
                    "reposts": item.get(
                        "reposts",
                        {},
                    ).get(
                        "count",
                        0,
                    ),
                    "views": item.get(
                        "views",
                        {},
                    ).get(
                        "count",
                        0,
                    ),
                }
            )

        analysis = await ai_text(
            "Проанализируй статистику "
            "последних постов VK. "
            "Назови 3 сильные стороны, "
            "3 точки роста и предложи "
            "темы следующих 6 постов. "
            "Не придумывай отсутствующие "
            "метрики.\n\n"
            "Данные: "
            + str(rows)
        )

        await message.reply_text(
            analysis
        )

    except Exception as exc:

        logger.exception(
            "VK stats failed"
        )

        await message.reply_text(
            "Не получилось получить "
            "статистику VK:\n"
            + str(exc)
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

        await message.reply_text(
            response
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
            + str(len(file_ids))
            + ". Готовлю пост…"
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

        await message.reply_text(
            text,
            reply_markup=publish_keyboard(),
        )

    except asyncio.CancelledError:
        return

    except Exception:

        logger.exception(
            "Album processing failed"
        )


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
        "Анализирую фото "
        "и готовлю пост…"
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

        await message.reply_text(
            text,
            reply_markup=publish_keyboard(),
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

    if text == MENU_HELP:

        await help_command(
            update,
            context,
        )

    elif text == MENU_PLAN:

        await plan_command(
            update,
            context,
        )

    elif text == MENU_STATUS:

        await status_command(
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
            "plan",
            plan_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "post",
            post_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "publish",
            publish_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "stats",
            stats_command,
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            publish_callback,
            pattern=(
                "^(publish_draft|cancel_draft)$"
            ),
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Regex(
                "^("
                + MENU_HELP
                + "|"
                + MENU_PLAN
                + "|"
                + MENU_STATUS
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