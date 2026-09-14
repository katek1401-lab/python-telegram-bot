import asyncio
import base64
import io
import logging
import os
import re
from typing import Optional

import av
from openai import AsyncOpenAI
from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackContext,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Эти имена использует main.py — не удалять
DB_KEY = "db"
REDIS_KEY = "redis"

logger = logging.getLogger(__name__)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
ADMIN_TELEGRAM_ID = os.getenv("ADMIN_TELEGRAM_ID", "").strip()

TEXT_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
TEXT_FALLBACK_MODEL = "openrouter/free"
VISION_MODEL = "openrouter/free"

MAX_VIDEO_BYTES = 18 * 1024 * 1024
MAX_VIDEO_FRAMES = 6

openai_client = AsyncOpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1",
)

PHOTO_GROUPS = {}


SYSTEM_PROMPT = """
Ты — персональный контент-менеджер и AI-редактор страницы пользователя во ВКонтакте.

Концепция блога:
«Живая жизнь между двумя городами».

Это авторский блог женщины, чья жизнь связана с Мурманском и Нижним Новгородом.

ВАЖНО:
Это не типичный «мамский блог».
Главный герой блога — сама женщина: её жизнь, настроение, характер,
мысли, выбор, привычки, поездки, дом, города и настоящие моменты.

Дети, семья, материнство, поездки и бытовые события — естественная часть
жизни, но не единственная тема.

Основные направления:
— жизнь между двумя городами;
— различия городов, климата, ритма и ощущения дома;
— настоящая повседневная жизнь;
— материнство как часть жизни;
— мысли автора;
— настроение и характер;
— тёплые семейные моменты;
— бытовой юмор;
— дорога, сборы и поездки;
— обычные красивые моменты;
— полезный контент только из настоящего опыта;
— реальные фотографии и видео.

Цель:
органический рост страницы ВКонтакте:
охваты, вовлечённость, узнаваемость и заинтересованные подписчики.

НИКОГДА НЕ ВЫДУМЫВАЙ ФАКТЫ.

Нельзя придумывать:
— цены и суммы;
— профессию;
— возраст детей;
— имена детей;
— покупки;
— конкретные события;
— места, которых пользователь не называл;
— длительность поездок;
— даты;
— цитаты детей;
— семейные проблемы;
— медицинские факты;
— рабочие ситуации;
— истории, которых пользователь не рассказывал.

Если какой-то факт неизвестен:
— убери его;
— предложи как идею;
— либо задай один короткий вопрос.

При анализе фото и видео:
описывай только то, что действительно видно.
Не определяй личности людей.
Не делай чувствительных предположений.

Действуй не только как копирайтер, но и как контент-менеджер.

Ты можешь советовать:
— что снять сегодня;
— что сфотографировать;
— какое видео снять;
— какой старый материал поискать в галерее;
— какой формат выбрать;
— что публиковать следующим;
— почему конкретный материал может быть полезен для роста.

Следи за разнообразием.

В контенте должны чередоваться:
— сама автор;
— два города;
— семья и дети;
— бытовой юмор;
— личные мысли;
— визуальные истории;
— настоящий полезный опыт;
— вовлекающие публикации;
— короткие видео;
— фотоподборки.

Не публикуй что-то только ради частоты.
Иногда отсутствие публикации лучше слабого поста.

Если создаёшь готовый пост, структура:
1. Сильное естественное начало.
2. Живой основной текст.
3. Призыв к реакции только если он уместен.
4. От 0 до 5 действительно нужных хэштегов.
5. В конце отдельной строкой:
«Зачем этот пост: ...»

Стиль:
русский язык.
Тёплый, умный, современный, естественный.
Без пафоса.
Без корпоративного стиля.
Без фальшивой мотивации.
Без рекламной интонации.
Без клише «идеальной мамы».
Без выдуманной драмы.
Без пустого кликбейта.

Не давай десять одинаковых вариантов.
Лучше один сильный вариант.

Если вопрос необходим — максимум один короткий вопрос.

Не обещай гарантированного роста.
Не говори, что материал «точно сработает», «даст охваты», «удержит аудиторию» или
«понравится алгоритмам», если у тебя нет реальной статистики этой страницы.
Вместо этого используй осторожные формулировки:
«может сработать», «может помочь», «есть потенциал», «стоит проверить по статистике».

Не утверждай, что публикация уже сделана.
Без подтверждения пользователя ничего не публикуется.

ОЧЕНЬ ВАЖНО:
отвечай только на нормальном русском языке.
Не используй без необходимости английские слова.
Не смешивай русский и английский.
Перед отправкой проверь ответ на случайные английские или поломанные слова.
"""


def main_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("Что делать сегодня")],
            [KeyboardButton("План на неделю")],
            [KeyboardButton("Что публиковать дальше")],
            [KeyboardButton("Стратегия роста")],
        ],
        resize_keyboard=True,
    )


def user_allowed(update: Update) -> bool:
    if not ADMIN_TELEGRAM_ID:
        return True

    user = update.effective_user
    if not user:
        return False

    return str(user.id) == ADMIN_TELEGRAM_ID


async def send_long_text(message, text: str):
    text = text or "Не получилось получить ответ."
    max_len = 3900

    while len(text) > max_len:
        split_at = text.rfind("\n", 0, max_len)
        if split_at < 1000:
            split_at = max_len

        part = text[:split_at].strip()
        text = text[split_at:].strip()
        await message.reply_text(part)

    if text:
        await message.reply_text(text)


def clean_ai_text(text: str) -> str:
    if not text:
        return ""

    text = text.strip()
    text = text.replace("```text", "")
    text = text.replace("```", "")
    return text.strip()


def has_suspicious_latin(text: str) -> bool:
    if not text:
        return False

    cleaned = re.sub(r"\bVK\b", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"https?://\S+", "", cleaned)
    latin_words = re.findall(r"[A-Za-z]{3,}", cleaned)
    return len(latin_words) >= 2


async def ai_text_once(prompt: str, model: str) -> str:
    response = await openai_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.7,
    )

    if not response.choices:
        raise RuntimeError("OpenRouter не вернул choices")

    return clean_ai_text(response.choices[0].message.content or "")


async def ai_text(prompt: str) -> str:
    try:
        text = await ai_text_once(prompt, TEXT_MODEL)
        if text:
            return text
    except Exception:
        logger.exception("Primary text model failed")

    return await ai_text_once(prompt, TEXT_FALLBACK_MODEL)


async def rewrite_to_clean_russian(text: str) -> str:
    if not has_suspicious_latin(text):
        return text

    prompt = f"""
Перепиши этот ответ на чистом естественном русском языке.
Сохрани смысл и структуру.
Не добавляй новых фактов.
Не используй английские слова, кроме названия VK, если оно необходимо.

Текст:
{text}
"""

    try:
        return await ai_text_once(prompt, TEXT_FALLBACK_MODEL)
    except Exception:
        logger.exception("Russian cleanup failed")
        return text


BAD_RUSSIAN_PATTERNS = [
    "уборочная инфраструктура",
    "визуальная единица",
    "контентная сущность",
    "формирование доверительных отношений",
    "теплоёмкий акцент",
    "маленькие чудеса",
    "бытовойжизнь",
    "живоеблог",
    "матьи",
]


def has_bad_russian(text: str) -> bool:
    if not text:
        return False
    t = text.lower().replace("ё", "е")
    return any(pattern.replace("ё", "е") in t for pattern in BAD_RUSSIAN_PATTERNS)


def remove_unconfirmed_city_hashtags(text: str, confirmed_city: Optional[str]) -> str:
    """Не разрешаем модели ставить географический хэштег без подтверждённого города."""
    if not text:
        return text

    allowed = set()
    if confirmed_city == "Мурманск":
        allowed.add("мурманск")
    elif confirmed_city == "Нижний Новгород":
        allowed.update({"нижнийновгород", "нижний_новгород"})

    def replace_tag(match):
        tag = match.group(1)
        normalized = tag.lower().replace("ё", "е")
        city_tags = {"мурманск", "нижнийновгород", "нижний_новгород"}
        if normalized in city_tags and normalized not in allowed:
            return ""
        return match.group(0)

    cleaned = re.sub(r"#([A-Za-zА-Яа-яЁё_]+)", replace_tag, text)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


async def polish_media_result(text: str, confirmed_city: Optional[str]) -> str:
    """Финальная редакторская проверка анализа фото/видео перед показом пользователю."""
    text = remove_unconfirmed_city_hashtags(text, confirmed_city)

    needs_rewrite = has_suspicious_latin(text) or has_bad_russian(text)
    if not needs_rewrite:
        return text

    city_rule = (
        f"Единственный подтверждённый текущий город пользователя — {confirmed_city}. "
        "Не добавляй другой город и не делай вывод, что материал снят в этом городе, если это не видно."
        if confirmed_city
        else "Город съёмки не подтверждён. Не называй Мурманск, Нижний Новгород или другой город и не ставь географические хэштеги."
    )

    prompt = f"""
Ты финальный редактор ответа контент-менеджера.
Исправь ТОЛЬКО качество текста, не меняя решение менеджера и не добавляя фактов.

Обязательно:
— нормальный живой русский язык без грамматических ошибок и поломанных слов;
— никаких канцеляризмов и искусственных выражений;
— никаких выдуманных мыслей, намерений и эмоций людей в кадре;
— не называй ребёнка «помощником» и не приписывай ему желание помогать, если это не подтверждено;
— убери странные, бессмысленные и натянутые хэштеги; лучше 0–3 хэштега или вообще без них;
— {city_rule}
— сохрани исходные заголовки и общую структуру;
— не обещай охваты, вовлечение или реакцию аудитории.

Текст для исправления:
{text}
"""

    try:
        rewritten = await ai_text_once(prompt, TEXT_FALLBACK_MODEL)
        rewritten = remove_unconfirmed_city_hashtags(rewritten, confirmed_city)
        return rewritten or text
    except Exception:
        logger.exception("Media polish failed")
        return text


def media_fact_warnings(text: str):
    """Детерминированная проверка опасных утверждений перед кнопкой «Готово»."""
    t = (text or "").lower().replace("ё", "е")
    warnings = []

    blocked = {
        "неподтвержденное родство": ["сын", "дочь", "мама с", "папа с"],
        "неподтвержденная история публикаций": [
            "второй подобный", "второй семейный", "подряд", "странице не хватает",
            "недавний контент", "последние публикации", "уже публиковали", "уже был",
        ],
        "неподтвержденный прогноз результата": [
            "утонет", "пройдет незамеч", "соберет реакции", "собирает реакции",
            "удержит аудиторию", "удерживает аудиторию", "даст охваты",
            "остановит скролл", "требует зацепа", "понравится алгоритм",
        ],
    }

    for label, phrases in blocked.items():
        if any(phrase in t for phrase in phrases):
            warnings.append(label)

    # Ловим явное противоречие в монтаже: «оставить как есть» и одновременно резать ролик.
    if "оставить как есть" in t and any(x in t for x in ["убрать первые", "укоротить начало", "укоротить конец", "оставить только"]):
        warnings.append("противоречие в совете по монтажу")

    return warnings


async def fact_safe_media_result(text: str, confirmed_city: Optional[str]) -> tuple[str, list]:
    """До двух раз просит модель убрать только найденные риски, затем снова проверяет кодом."""
    result = remove_unconfirmed_city_hashtags(text, confirmed_city)

    for _ in range(2):
        warnings = media_fact_warnings(result)
        if not warnings:
            return result, []

        warning_text = ", ".join(warnings)
        city_rule = (
            f"Подтвержденный текущий город пользователя: {confirmed_city}. Не утверждай, что материал снят там, если это не видно и пользователь этого не сказал."
            if confirmed_city
            else "Город съемки не подтвержден. Не называй город и не добавляй географические хэштеги."
        )

        prompt = f"""
Ты финальный редактор фактов. Исправь текст так, чтобы в нем НЕ осталось следующих рисков:
{warning_text}.

ЖЕСТКИЕ ПРАВИЛА:
— не добавляй новых фактов;
— не называй ребенка сыном или дочерью без прямого сообщения пользователя;
— не утверждай, что это второй похожий пост, что чего-то «не хватает странице» или что такой контент уже публиковался: истории реальных публикаций у тебя нет;
— не предсказывай охваты, реакции, удержание, алгоритмы, «утонет в ленте», «пройдет незамеченным» и подобное;
— если совет по монтажу «оставить как есть», не предлагай в том же ответе что-то вырезать. Выбери одно решение;
— идеи для будущей съемки помечай именно как предложения, а не как существующие факты;
— {city_rule}
— сохрани решение ПУБЛИКОВАТЬ / ДОРАБОТАТЬ / НЕ ПУБЛИКОВАТЬ;
— сохрани структуру и нормальный разговорный русский язык.

Текст:
{result}
"""
        try:
            rewritten = await ai_text_once(prompt, TEXT_FALLBACK_MODEL)
            if rewritten:
                result = remove_unconfirmed_city_hashtags(rewritten, confirmed_city)
        except Exception:
            logger.exception("Fact safety rewrite failed")
            break

    return result, media_fact_warnings(result)


def media_review_keyboard(ready_allowed: bool = True):
    if ready_allowed:
        return InlineKeyboardMarkup(
            [[
                InlineKeyboardButton("✅ Готово к публикации", callback_data="media_ready"),
                InlineKeyboardButton("🔄 Переделать", callback_data="media_redo"),
            ]]
        )

    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔄 Переделать и проверить", callback_data="media_redo")]]
    )


async def send_media_result(message, context: ContextTypes.DEFAULT_TYPE, result: str):
    city = None
    try:
        user = message.chat.id if message and message.chat else None
        if user:
            city = await get_current_city(context, user)
    except Exception:
        logger.exception("Could not load city for media safety check")

    result = await polish_media_result(result, city)
    result, warnings = await fact_safe_media_result(result, city)

    save_draft(context, result)
    context.user_data["media_ready_allowed"] = not warnings
    context.user_data["media_fact_warnings"] = warnings

    keyboard = media_review_keyboard(ready_allowed=not warnings)

    if len(result) <= 3900:
        await message.reply_text(result, reply_markup=keyboard)
    else:
        await send_long_text(message, result)
        if warnings:
            await message.reply_text(
                "⚠️ Проверка фактов ещё видит риск. Готовность пока заблокирована.",
                reply_markup=keyboard,
            )
        else:
            await message.reply_text("Что делаем с этим вариантом?", reply_markup=keyboard)


async def media_review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_allowed(update):
        return

    query = update.callback_query
    if not query:
        return

    await query.answer()

    if query.data == "media_ready":
        draft = context.user_data.get("last_draft")
        if not draft:
            await query.message.reply_text("Черновик уже потерялся. Пришли фото или видео ещё раз.")
            return

        # Не доверяем одной только кнопке: проверяем черновик кодом повторно.
        warnings = media_fact_warnings(draft)
        if warnings or not context.user_data.get("media_ready_allowed", False):
            await query.message.reply_text(
                "⚠️ Я ещё вижу риск выдуманного факта или противоречия. "
                "Готовность не подтверждаю — нажми «Переделать и проверить»."
            )
            return

        context.user_data["approved_draft"] = draft
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            "✅ Зафиксировала этот вариант как готовый.\n\n"
            "В VK я пока ничего не публикую. Следующим шагом подключим отдельное подтверждение «Публикуем?»."
        )
        return

    if query.data == "media_redo":
        draft = context.user_data.get("last_draft")
        if not draft:
            await query.message.reply_text("Черновик уже потерялся. Пришли фото или видео ещё раз.")
            return

        wait = await query.message.reply_text("Переделываю и проверяю факты…")
        prompt = f"""
Ты — строгий редактор фактов. Переделай исходный разбор, НЕ ДОБАВЛЯЯ НИ ОДНОГО нового факта.

КРИТИЧЕСКИЕ ПРАВИЛА:
— используй только сведения, которые прямо содержатся в исходном разборе как видимые детали;
— пол и родство человека неизвестны, если пользователь их явно не сообщал: пиши «ребёнок», а не «сын» или «дочь»;
— не придумывай мысли, чувства, намерения, причины действий, реплики или отношения между людьми;
— не превращай предположение в факт: вместо «помогает» описывай видимое действие;
— не придумывай новые предметы и существующие кадры;
— не пиши от первого лица пользователя мысли или события, которых пользователь не сообщал;
— не называй место съёмки и город, если они не подтверждены;
— у тебя НЕТ истории реальных публикаций VK: не говори «второй подобный пост», «подряд», «странице не хватает», «мы уже публиковали»;
— не обещай и не предсказывай охваты, реакции, удержание, алгоритмы, «утонет в ленте» или «пройдёт незамеченным»;
— не утверждай общие правила VK вроде «такой формат требует зацепа», если у тебя нет статистики страницы;
— совет по монтажу должен быть ОДИН и непротиворечивый: либо оставить как есть, либо конкретно изменить;
— если фактов для подписи мало, сделай короткую нейтральную подпись;
— хэштеги необязательны;
— новый кадр разрешено предложить только как ИДЕЮ на будущее.

Сохрани исходное решение ПУБЛИКОВАТЬ / ДОРАБОТАТЬ / НЕ ПУБЛИКОВАТЬ.

Структура:
🧭 Решение менеджера
👀 Что видно
⭐ Самое сильное
✂️ Что сделать
📱 Как публиковать
✍️ Готовая подпись
➡️ Что снять следующим
💡 Роль в блоге

Исходный разбор:
{draft}
"""
        try:
            result = await ai_text(prompt)
            city = await get_current_city(context, update.effective_user.id)
            result = await polish_media_result(result, city)
            result, warnings = await fact_safe_media_result(result, city)
            await wait.delete()
            await query.edit_message_reply_markup(reply_markup=None)
            await send_media_result(query.message, context, result)
            if warnings:
                await query.message.reply_text(
                    "⚠️ Проверка всё ещё видит риск выдумки или противоречия, поэтому кнопка «Готово» пока не показана."
                )
        except Exception:
            logger.exception("Media redo failed")
            await wait.edit_text("Не получилось переделать. Нажми «Переделать» ещё раз чуть позже.")


def get_pool(context: ContextTypes.DEFAULT_TYPE):
    return context.application.bot_data.get(DB_KEY)


async def ensure_profile_table(context: ContextTypes.DEFAULT_TYPE):
    pool = get_pool(context)
    if not pool:
        return

    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vk_manager_profile_state (
                telegram_id BIGINT PRIMARY KEY,
                current_city TEXT,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )


async def ensure_task_history_table(context: ContextTypes.DEFAULT_TYPE):
    pool = get_pool(context)
    if not pool:
        return

    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vk_manager_task_history (
                id BIGSERIAL PRIMARY KEY,
                telegram_id BIGINT NOT NULL,
                task_text TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )


async def set_current_city(context: ContextTypes.DEFAULT_TYPE, telegram_id: int, city: str):
    pool = get_pool(context)
    if not pool:
        return

    await ensure_profile_table(context)

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO vk_manager_profile_state
                (telegram_id, current_city, updated_at)
            VALUES ($1, $2, now())
            ON CONFLICT (telegram_id)
            DO UPDATE SET
                current_city = EXCLUDED.current_city,
                updated_at = now();
            """,
            telegram_id,
            city,
        )


async def get_current_city(context: ContextTypes.DEFAULT_TYPE, telegram_id: int) -> Optional[str]:
    pool = get_pool(context)
    if not pool:
        return None

    await ensure_profile_table(context)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT current_city
            FROM vk_manager_profile_state
            WHERE telegram_id = $1;
            """,
            telegram_id,
        )

    if not row:
        return None

    return row["current_city"]


async def save_today_task(context: ContextTypes.DEFAULT_TYPE, telegram_id: int, task_text: str):
    pool = get_pool(context)
    if not pool:
        return

    await ensure_task_history_table(context)

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO vk_manager_task_history
                (telegram_id, task_text)
            VALUES ($1, $2);
            """,
            telegram_id,
            task_text,
        )

        await conn.execute(
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


async def get_recent_tasks(context: ContextTypes.DEFAULT_TYPE, telegram_id: int):
    pool = get_pool(context)
    if not pool:
        return []

    await ensure_task_history_table(context)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT task_text
            FROM vk_manager_task_history
            WHERE telegram_id = $1
            ORDER BY created_at DESC, id DESC
            LIMIT 10;
            """,
            telegram_id,
        )

    return [row["task_text"] for row in rows]


def detect_city(text: str) -> Optional[str]:
    t = text.lower().replace("ё", "е")

    if "нижн" in t and "новгород" in t:
        return "Нижний Новгород"

    if "мурманск" in t:
        return "Мурманск"

    return None


def is_location_statement(text: str) -> bool:
    t = text.lower().strip().replace("ё", "е")

    exact_answers = {
        "мурманск",
        "в мурманске",
        "нижний новгород",
        "в нижнем новгороде",
    }

    if t in exact_answers:
        return True

    location_phrases = [
        "я сейчас в ",
        "сейчас я в ",
        "я в ",
        "нахожусь в ",
        "я теперь в ",
        "теперь я в ",
        "сегодня я в ",
        "приехала в ",
        "приехал в ",
        "вернулась в ",
        "вернулся в ",
    ]

    return any(phrase in t for phrase in location_phrases)


def city_in_phrase(city: Optional[str]) -> str:
    if city == "Нижний Новгород":
        return "Нижнем Новгороде"

    if city == "Мурманск":
        return "Мурманске"

    return "текущем городе"


def recent_repeat_signals(tasks):
    combined = "\n".join(tasks).lower()

    groups = {
        "кофе или чашка": ["кофе", "чашк"],
        "окно": ["окно", "окна", "подокон"],
        "селфи": ["селфи"],
        "ноги или шаги": ["ноги", "ног", "шаг"],
        "маршрут или прогулка": ["маршрут", "прогул", "идти", "пройти"],
        "отражение или тень": ["отраж", "тень"],
        "дверь или подъезд": ["двер", "подъезд"],
        "туристическая точка как фон": ["кремл", "чкалов", "набереж", "достопримеч"],
    }

    found = []
    for name, words in groups.items():
        if any(word in combined for word in words):
            found.append(name)

    return found


async def build_today_task(context: ContextTypes.DEFAULT_TYPE, telegram_id: int):
    city = await get_current_city(context, telegram_id)
    tasks = await get_recent_tasks(context, telegram_id)

    recent_text = "\n\n".join(tasks) if tasks else "Истории пока нет."
    repeats = recent_repeat_signals(tasks)
    repeat_text = ", ".join(repeats) if repeats else "явных повторов пока нет"

    city_text = (
        f"Пользователь сейчас находится в {city_in_phrase(city)}."
        if city
        else "Текущий город пользователя неизвестен. Не придумывай его."
    )

    prompt = f"""
{city_text}

Ты сегодня управляешь контентом страницы.
Выбери ОДНО лучшее конкретное задание на сегодня.
Не предлагай меню из вариантов.

Последние задания:
{recent_text}

Уже часто использовавшиеся элементы:
{repeat_text}

Сделай новое задание заметно отличающимся от последних.

Не повторяй без необходимости:
кофе, чашку, окно, селфи, ноги, шаги, обычную прогулку,
отражение, тень, подъезд и дверь.

Не отправляй пользователя специально к туристической
достопримечательности только ради красивого фона.

Используй место только если оно естественно связано с реальным днём.
Задание должно быть реально выполнимо с телефона.

Формат ответа строго такой:

🎯 Сегодня
[одно конкретное задание]

📸 Сними
1. ...
2. ...
3. ...

✍️ Идея
[что может стать смыслом публикации]

💡 Зачем
[короткое объяснение простыми словами, без технического жаргона]
"""

    result = await ai_text(prompt)
    result = await rewrite_to_clean_russian(result)
    await save_today_task(context, telegram_id, result)
    return result


async def image_bytes_to_data_url(data: bytes, mime_type="image/jpeg"):
    encoded = base64.b64encode(data).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


async def ai_post_from_photos(image_urls, prompt: str) -> str:
    content = [{"type": "input_text", "text": SYSTEM_PROMPT + "\n\n" + prompt}]

    for image_url in image_urls:
        content.append({"type": "input_image", "image_url": image_url})

    try:
        response = await openai_client.responses.create(
            model=VISION_MODEL,
            input=[{"role": "user", "content": content}],
        )

        text = clean_ai_text(response.output_text or "")
        if text:
            return await rewrite_to_clean_russian(text)

    except Exception:
        logger.exception("Vision responses API failed")

    chat_content = [{"type": "text", "text": SYSTEM_PROMPT + "\n\n" + prompt}]

    for image_url in image_urls:
        chat_content.append(
            {
                "type": "image_url",
                "image_url": {"url": image_url},
            }
        )

    response = await openai_client.chat.completions.create(
        model=VISION_MODEL,
        messages=[{"role": "user", "content": chat_content}],
    )

    if not response.choices:
        raise RuntimeError("Модель не вернула результат анализа изображений")

    text = clean_ai_text(response.choices[0].message.content or "")
    return await rewrite_to_clean_russian(text)


def jpeg_from_video_frame(frame) -> bytes:
    width = frame.width
    height = frame.height
    max_side = 1280

    scale = min(1.0, max_side / max(width, height))
    new_width = max(2, int(width * scale))
    new_height = max(2, int(height * scale))

    if new_width % 2:
        new_width -= 1
    if new_height % 2:
        new_height -= 1

    frame = frame.reformat(width=new_width, height=new_height, format="yuvj420p")

    codec = av.CodecContext.create("mjpeg", "w")
    codec.width = new_width
    codec.height = new_height
    codec.pix_fmt = "yuvj420p"

    packets = codec.encode(frame)
    packets += codec.encode(None)

    if not packets:
        raise RuntimeError("Не удалось превратить кадр в JPEG")

    return b"".join(bytes(packet) for packet in packets)


def extract_video_frames(video_bytes: bytes):
    container = av.open(io.BytesIO(video_bytes))

    try:
        video_stream = next(stream for stream in container.streams if stream.type == "video")
    except StopIteration:
        container.close()
        raise RuntimeError("В файле не найден видеопоток")

    duration_seconds = None

    try:
        if video_stream.duration is not None and video_stream.time_base is not None:
            duration_seconds = float(video_stream.duration * video_stream.time_base)
        elif container.duration is not None:
            duration_seconds = float(container.duration / av.time_base)
    except Exception:
        duration_seconds = None

    if duration_seconds and duration_seconds > 0:
        if MAX_VIDEO_FRAMES == 1:
            targets = [duration_seconds / 2]
        else:
            start = min(0.1, duration_seconds * 0.05)
            end = max(start, duration_seconds - start)
            targets = [
                start + (end - start) * i / (MAX_VIDEO_FRAMES - 1)
                for i in range(MAX_VIDEO_FRAMES)
            ]
    else:
        targets = [0, 0.5, 1, 1.5, 2, 2.5]

    frames = []
    target_index = 0
    decoded_count = 0

    for frame in container.decode(video=video_stream.index):
        decoded_count += 1
        if decoded_count > 5000:
            break

        try:
            frame_time = float(frame.time) if frame.time is not None else None
        except Exception:
            frame_time = None

        if frame_time is None:
            if decoded_count == 1 or decoded_count % 30 == 0:
                frames.append(jpeg_from_video_frame(frame))
                if len(frames) >= MAX_VIDEO_FRAMES:
                    break
            continue

        while target_index < len(targets) and frame_time >= targets[target_index]:
            frames.append(jpeg_from_video_frame(frame))
            target_index += 1
            if len(frames) >= MAX_VIDEO_FRAMES:
                break

        if len(frames) >= MAX_VIDEO_FRAMES:
            break

    container.close()

    if not frames:
        container = av.open(io.BytesIO(video_bytes))
        try:
            stream = next(stream for stream in container.streams if stream.type == "video")
            for frame in container.decode(video=stream.index):
                frames.append(jpeg_from_video_frame(frame))
                break
        finally:
            container.close()

    if not frames:
        raise RuntimeError("Не удалось извлечь ни одного кадра")

    return frames


async def telegram_photo_data_url(photo):
    tg_file = await photo.get_file()
    data = bytes(await tg_file.download_as_bytearray())
    return await image_bytes_to_data_url(data, "image/jpeg")


async def telegram_video_frames(video):
    if video.file_size and video.file_size > MAX_VIDEO_BYTES:
        raise ValueError("VIDEO_TOO_LARGE")

    tg_file = await video.get_file()
    data = bytes(await tg_file.download_as_bytearray())

    if len(data) > MAX_VIDEO_BYTES:
        raise ValueError("VIDEO_TOO_LARGE")

    frames = await asyncio.to_thread(extract_video_frames, data)

    urls = []
    for frame_bytes in frames:
        urls.append(await image_bytes_to_data_url(frame_bytes, "image/jpeg"))

    return urls


def save_draft(context: ContextTypes.DEFAULT_TYPE, text: str):
    context.user_data["last_draft"] = text


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_allowed(update):
        return

    text = (
        "Я готова работать как твой AI-менеджер VK.\n\n"
        "Я могу придумать, что публиковать, написать пост, составить план, "
        "разобрать фотографии и короткое видео.\n\n"
        "После фото или видео я не только анализирую материал, но и даю "
        "решение: публиковать, доработать или пока не публиковать.\n\n"
        "Видео анализируется бесплатно по кадрам — без отправки самого видео "
        "в платный видео-API."
    )

    await update.message.reply_text(text, reply_markup=main_keyboard())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_allowed(update):
        return

    text = """
Что умею:

/today — одно лучшее задание на сегодня
/post — придумать пост
/plan — план на неделю
/strategy — стратегия роста
/next — что публиковать дальше
/status — состояние менеджера
/myid — твой Telegram ID
/ping — проверка работы

Можно просто прислать фотографию или несколько фотографий.
Можно прислать короткое видео из галереи.

После разбора я сам выбираю одно решение:
ПУБЛИКОВАТЬ / ДОРАБОТАТЬ / НЕ ПУБЛИКОВАТЬ.

Для видео я беру несколько кадров и оцениваю их как одну визуальную историю.
Звук в бесплатном режиме пока не анализируется.
"""

    await update.message.reply_text(text.strip())


async def myid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user:
        return

    await update.message.reply_text(f"Твой Telegram ID: {update.effective_user.id}")


async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_allowed(update):
        return

    await update.message.reply_text("Работаю ✅")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_allowed(update):
        return

    user = update.effective_user
    city = await get_current_city(context, user.id)
    tasks = await get_recent_tasks(context, user.id)
    city_text = city or "не указан"

    text = (
        "✅ AI-менеджер работает\n"
        f"📍 Текущий город: {city_text}\n"
        f"🧠 Память заданий: {len(tasks)}/10\n"
        "📷 Анализ фото: включён\n"
        "🎞 Анализ коротких видео по кадрам: включён\n"
        "🧭 Решение менеджера после анализа: включено\n"
        "🔊 Анализ звука видео: пока выключен\n"
        "🚫 Автопубликация без подтверждения: выключена"
    )

    await update.message.reply_text(text)


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_allowed(update):
        return

    message = await update.message.reply_text(
        "Думаю, какое одно задание сегодня будет самым полезным…"
    )

    try:
        result = await build_today_task(context, update.effective_user.id)
        await message.delete()
        await send_long_text(update.message, result)
    except Exception:
        logger.exception("Today command failed")
        await message.edit_text("Не получилось придумать задание. Попробуй ещё раз чуть позже.")


async def post_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_allowed(update):
        return

    city = await get_current_city(context, update.effective_user.id)
    city_info = (
        f"Подтверждённый текущий город: {city}."
        if city
        else "Текущий город не подтверждён."
    )

    prompt = f"""
{city_info}

Предложи ОДНУ сильную идею публикации для моего VK-блога сегодня.

Если для готового текста тебе не хватает реального события,
не придумывай его.

В таком случае дай конкретную идею:
что снять или какую фотографию найти в галерее,
какой должен быть смысл публикации.

Если можно написать пост без выдуманных фактов — напиши готовый пост.
"""

    wait = await update.message.reply_text("Готовлю идею поста…")

    try:
        result = await ai_text(prompt)
        result = await rewrite_to_clean_russian(result)
        save_draft(context, result)
        await wait.delete()
        await send_long_text(update.message, result)
    except Exception:
        logger.exception("Post command failed")
        await wait.edit_text("Не получилось создать пост. Попробуй ещё раз.")


async def plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_allowed(update):
        return

    city = await get_current_city(context, update.effective_user.id)

    prompt = f"""
Составь практичный контент-план на ближайшие 7 дней.

Текущий подтверждённый город:
{city if city else "неизвестен"}.

Не придумывай события из жизни пользователя.

На каждый день:
— один основной формат;
— тема;
— что реально снять или найти в галерее;
— зачем это нужно странице.

Чередуй:
личность автора, города, семью, мысли, быт,
юмор, видео, фото и полезный настоящий опыт.

Не заставляй публиковать ежедневно,
если пауза логичнее.
"""

    wait = await update.message.reply_text("Составляю план на неделю…")

    try:
        result = await ai_text(prompt)
        result = await rewrite_to_clean_russian(result)
        await wait.delete()
        await send_long_text(update.message, result)
    except Exception:
        logger.exception("Plan command failed")
        await wait.edit_text("Не получилось составить план.")


async def strategy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_allowed(update):
        return

    prompt = """
Дай практичную стратегию органического роста этой VK-страницы
на ближайший месяц.

Не обещай гарантированный рост.
Не предлагай накрутку и спам.

Сосредоточься на:
— узнаваемом образе автора;
— теме жизни между двумя городами;
— сильных фото и коротких видео;
— удержании интереса;
— комментариях и реакции аудитории;
— повторяемых рубриках без однообразия.

Пиши конкретно и простым русским языком.
"""

    wait = await update.message.reply_text("Собираю стратегию…")

    try:
        result = await ai_text(prompt)
        result = await rewrite_to_clean_russian(result)
        await wait.delete()
        await send_long_text(update.message, result)
    except Exception:
        logger.exception("Strategy command failed")
        await wait.edit_text("Не получилось подготовить стратегию.")


async def next_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_allowed(update):
        return

    tasks = await get_recent_tasks(context, update.effective_user.id)
    recent = "\n\n".join(tasks[:5]) if tasks else "Нет истории."

    prompt = f"""
Скажи, что лучше публиковать следующим.

Последние задания контент-менеджера:
{recent}

Выбери один формат и одну идею.
Не повторяй автоматически недавние приёмы.
Не придумывай факты из жизни.

Скажи:
1. Что именно сделать.
2. Что снять или найти в галерее.
3. Главную мысль.
4. Почему это логичный следующий материал.
"""

    wait = await update.message.reply_text("Выбираю следующий материал…")

    try:
        result = await ai_text(prompt)
        result = await rewrite_to_clean_russian(result)
        await wait.delete()
        await send_long_text(update.message, result)
    except Exception:
        logger.exception("Next command failed")
        await wait.edit_text("Не получилось выбрать следующий материал.")


async def analyse_photo_urls(update: Update, context: ContextTypes.DEFAULT_TYPE, urls):
    city = await get_current_city(context, update.effective_user.id)

    prompt = f"""
Перед тобой реальные фотографии пользователя.

Текущий подтверждённый город:
{city if city else "не указан"}.

ВАЖНО:
не определяй место по сохранённому городу.
Говори о городе только если он действительно узнаваем на изображении
или пользователь сам его указал.

Ты не просто анализатор. Ты контент-менеджер, который должен принять решение.

В САМОМ НАЧАЛЕ выбери ровно один статус:
✅ ПУБЛИКОВАТЬ
🟡 ДОРАБОТАТЬ
🔴 НЕ ПУБЛИКОВАТЬ

Не ставь «ПУБЛИКОВАТЬ» из вежливости. Если материал слабый или бессмысленный,
лучше честно выбрать «ДОРАБОТАТЬ» или «НЕ ПУБЛИКОВАТЬ».

Дальше ответ строго по структуре:

🧭 Решение менеджера
[статус + одно короткое объяснение]

👀 Что видно
[только реальные видимые детали]

⭐ Что здесь самое сильное
[один главный плюс материала]

✂️ Что сделать перед публикацией
[конкретно: выбрать кадр, обрезать, убрать лишнее, оставить как есть и т.п.]

📱 Как публиковать
[один лучший формат, а не список]

✍️ Готовая подпись
[один естественный вариант; не выдумывай факты]

➡️ Что делать следующим
[одно конкретное следующее действие для контента страницы]

💡 Зачем
[какую роль этот материал МОЖЕТ сыграть в общей истории страницы]

Не утверждай, что материал точно даст охваты или понравится алгоритмам.
Без статистики страницы говори только о потенциале.
"""

    result = await ai_post_from_photos(urls, prompt)
    result = await polish_media_result(result, city)
    await send_media_result(update.message, context, result)


async def photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_allowed(update):
        return

    message = update.message
    if not message or not message.photo:
        return

    media_group_id = message.media_group_id

    if media_group_id:
        key = f"{update.effective_user.id}:{media_group_id}"

        if key not in PHOTO_GROUPS:
            PHOTO_GROUPS[key] = {
                "photos": [],
                "message": message,
                "context": context,
                "update": update,
                "task": None,
            }

        PHOTO_GROUPS[key]["photos"].append(message.photo[-1])
        old_task = PHOTO_GROUPS[key].get("task")

        if old_task and not old_task.done():
            old_task.cancel()

        PHOTO_GROUPS[key]["task"] = asyncio.create_task(
            process_photo_album_after_delay(key)
        )
        return

    wait = await message.reply_text("Смотрю фотографию и решаю, стоит ли её публиковать…")

    try:
        url = await telegram_photo_data_url(message.photo[-1])
        await wait.delete()
        await analyse_photo_urls(update, context, [url])
    except Exception:
        logger.exception("Photo analysis failed")
        await wait.edit_text("Не получилось разобрать фотографию. Попробуй отправить её ещё раз.")


async def process_photo_album_after_delay(key):
    try:
        await asyncio.sleep(2.5)
        data = PHOTO_GROUPS.pop(key, None)

        if not data:
            return

        update = data["update"]
        context = data["context"]
        message = data["message"]
        photos = data["photos"]

        wait = await message.reply_text(
            f"Смотрю подборку: {len(photos)} фото. Выбираю, что с ней делать…"
        )

        urls = []
        for photo in photos[:10]:
            urls.append(await telegram_photo_data_url(photo))

        await wait.delete()
        await analyse_photo_urls(update, context, urls)

    except asyncio.CancelledError:
        return

    except Exception:
        logger.exception("Photo album analysis failed")
        data = PHOTO_GROUPS.pop(key, None)

        if data:
            try:
                await data["message"].reply_text("Не получилось разобрать подборку фотографий.")
            except Exception:
                pass


async def video_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_allowed(update):
        return

    message = update.message
    if not message or not message.video:
        return

    wait = await message.reply_text(
        "Смотрю видео по кадрам и решаю, стоит ли его публиковать…"
    )

    try:
        image_urls = await telegram_video_frames(message.video)
        city = await get_current_city(context, update.effective_user.id)

        duration_seconds = message.video.duration or 0
        duration_text = (
            f"{duration_seconds} сек."
            if duration_seconds
            else "не удалось определить"
        )

        prompt = f"""
Это НЕ фотографии, а несколько кадров,
автоматически извлечённых из одного настоящего видео пользователя.

Видео анализируется только визуально.
Звук и речь тебе недоступны.

Количество кадров:
{len(image_urls)}.

Фактическая длительность присланного видео:
{duration_text}

Учитывай эту длительность буквально.
Если видео длится 3 секунды, НЕ советуй делать его «до 10–15 секунд»
и не предлагай сокращать его только ради общей рекомендации по длительности.

Текущий сохранённый город:
{city if city else "не указан"}.

Не делай вывод о месте только из сохранённого города.

Не придумывай:
— что человек говорит;
— музыку;
— звук;
— точные таймкоды;
— события вне видимых кадров.

Ты не просто анализатор. Ты контент-менеджер и должен сам принять решение,
нужен ли этот ролик странице сейчас.

В САМОМ НАЧАЛЕ выбери ровно один статус:
✅ ПУБЛИКОВАТЬ
🟡 ДОРАБОТАТЬ
🔴 НЕ ПУБЛИКОВАТЬ

Не выбирай «ПУБЛИКОВАТЬ» из вежливости.
Статус «ПУБЛИКОВАТЬ» разрешён только если в ролике есть хотя бы один
понятный визуальный крючок: действие, эмоция, юмор, необычная деталь,
сильная композиция или ясная роль в истории блога.
Если ролик просто нормальный, но ничем не выделяется — «ДОРАБОТАТЬ».
Если он слабый, бессмысленный, сильно повторяет недавний контент
или визуально нечитабельный — «НЕ ПУБЛИКОВАТЬ».

Пиши живым разговорным русским языком.
Запрещены канцелярские и искусственные выражения вроде
«уборочная инфраструктура», «визуальная единица», «контентная сущность»,
«формирование доверительных отношений с аудиторией».
Не используй банальные красивые фразы вроде «маленькие чудеса»,
если они не следуют из реального контекста.
Не приписывай ребёнку мысли, намерения или «подражание взрослым»,
если этого нельзя достоверно увидеть по кадрам.

Ответ строго по структуре:

🧭 Решение менеджера
[статус + коротко почему]

👀 Что происходит визуально
[что действительно видно в последовательности кадров]

⭐ Самый сильный момент
[опиши визуально, без выдуманного таймкода]

✂️ Монтаж
Сначала учти фактическую длительность видео.
Скажи ОДНО конкретное решение:
— оставить как есть;
— укоротить начало;
— укоротить конец;
— оставить только центральный фрагмент;
— переснять.
Не давай абстрактных советов про «идеальные 10–15 секунд».
Коротко объясни решение именно для этого ролика.

📱 Как публиковать
Выбери ОДИН лучший формат для VK.
Если ролик не стоит публиковать — так и скажи.

✍️ Готовая подпись
Дай один короткий естественный вариант.
Если контекста для честной подписи недостаточно — напиши нейтральную подпись,
основанную только на видимом, без выдуманной истории.

➡️ Что делать следующим
Дай ОДНО конкретное следующее действие:
что снять, какой кадр добавить или какой следующий материал подготовить,
чтобы страница не зацикливалась на одном типе контента.

💡 Роль в блоге
Объясни, какую роль этот ролик МОЖЕТ сыграть в общей истории страницы.
Не утверждай, что он точно даст охваты, удержание или реакцию аудитории.
Без реальной статистики говори только о потенциале.

В конце отдельной строкой:
«Звук в этом анализе не учитывался».
"""

        result = await ai_post_from_photos(image_urls, prompt)
        result = await polish_media_result(result, city)

        await wait.delete()
        await send_media_result(message, context, result)

    except ValueError as exc:
        if str(exc) == "VIDEO_TOO_LARGE":
            await wait.edit_text(
                "Этот ролик слишком большой для текущего режима. "
                "Для начала отправь видео до 18 МБ."
            )
        else:
            logger.exception("Video validation failed")
            await wait.edit_text("Не получилось обработать это видео.")

    except Exception:
        logger.exception("Video frame analysis failed")
        await wait.edit_text(
            "Не получилось разобрать видео по кадрам.\n\n"
            "Если ролик короткий, значит дело уже не в размере — "
            "посмотрим одну строку ошибки в Railway."
        )


async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_allowed(update):
        return

    message = update.message
    if not message or not message.text:
        return

    text = message.text.strip()

    if text == "Что делать сегодня":
        await today_command(update, context)
        return

    if text == "План на неделю":
        await plan_command(update, context)
        return

    if text == "Что публиковать дальше":
        await next_command(update, context)
        return

    if text == "Стратегия роста":
        await strategy_command(update, context)
        return

    city = detect_city(text)

    if city and is_location_statement(text):
        await set_current_city(context, update.effective_user.id, city)
        await message.reply_text(f"Запомнила: сейчас ты в {city_in_phrase(city)}.")
        return

    saved_city = await get_current_city(context, update.effective_user.id)

    city_context = (
        f"Подтверждённый текущий город пользователя: {saved_city}."
        if saved_city
        else "Подтверждённый текущий город пока неизвестен."
    )

    prompt = f"""
{city_context}

Сообщение пользователя:
{text}

Ответь как её персональный контент-менеджер VK.

Если пользователь рассказывает реальный факт или событие,
можешь использовать только то, что он действительно написал.

Если просит текст публикации — подготовь сильный готовый вариант.
Если просит совет — выбери один наиболее полезный вариант, а не длинный список.

Не говори, что что-то «точно сработает» без реальной статистики страницы.
"""

    wait = await message.reply_text("Думаю…")

    try:
        result = await ai_text(prompt)
        result = await rewrite_to_clean_russian(result)
        save_draft(context, result)
        await wait.delete()
        await send_long_text(message, result)
    except Exception:
        logger.exception("Text message failed")
        await wait.edit_text("Сейчас не получилось получить ответ от AI. Попробуй ещё раз.")


async def error_handler(update: object, context: CallbackContext):
    logger.error(
        "Exception while handling an update:",
        exc_info=context.error,
    )


def register_handlers(application: Application):
    application.add_handler(CallbackQueryHandler(media_review_callback, pattern=r"^media_(ready|redo)$"))
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("today", today_command))
    application.add_handler(CommandHandler("post", post_command))
    application.add_handler(CommandHandler("plan", plan_command))
    application.add_handler(CommandHandler("strategy", strategy_command))
    application.add_handler(CommandHandler("next", next_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("myid", myid_command))
    application.add_handler(CommandHandler("ping", ping_command))

    application.add_handler(MessageHandler(filters.VIDEO, video_message))
    application.add_handler(MessageHandler(filters.PHOTO, photo_message))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message))


async def set_bot_commands(application: Application):
    commands = [
        BotCommand("start", "Запустить менеджера"),
        BotCommand("today", "Что делать сегодня"),
        BotCommand("post", "Идея или текст поста"),
        BotCommand("plan", "План на неделю"),
        BotCommand("next", "Что публиковать дальше"),
        BotCommand("strategy", "Стратегия роста"),
        BotCommand("status", "Проверить состояние"),
        BotCommand("help", "Что умеет бот"),
        BotCommand("myid", "Мой Telegram ID"),
        BotCommand("ping", "Проверить бота"),
    ]

    await application.bot.set_my_commands(commands)
