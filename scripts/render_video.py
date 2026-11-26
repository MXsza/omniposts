#!/usr/bin/env python3
"""
Omniposts.online — 24/7 1080p Cloud Video Worker (Pro Cinema Edition)
Pipeline:
  1. Load job & YouTube channel credentials from Supabase (render_jobs + channels)
  2. Generate a real, gripping localized story script + mood + scene prompts + viral title/description
     via Runware Chat Completions (with rich dialect-matched fallback stories)
  3. Generate N scene images in parallel via Runware imageInference (runware:100@1 FLUX.1 schnell)
     and push live preview image URLs to Supabase render_jobs
  4. Synthesize natural voiceover in any world language/dialect (Male/Female) via Edge TTS
  5. Synthesize 100% copyright-free mood-matched cinematic background music & subtle transition whoosh SFX
     (epic / mystery / sad / happy / calm)
  6. Assemble Full HD 1080p MP4 with full-frame gentle Ken Burns motion (no edge cropping or dark vignette),
     smooth xfade transitions, and sleek compact 1–2 line timed subtitles
  7. Upload MP4 to Supabase Storage (for instant download), upload to YouTube via OAuth 2.0,
     deduct exact minutes ONLY on success, and update render_jobs + publish_logs.
"""

import asyncio
import datetime
import json
import math
import os
import random
import re
import struct
import subprocess
import sys
import tempfile
import time
import uuid
import wave
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import arabic_reshaper
import edge_tts
import requests
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont, features

# ==============================================================================
# Environment & Configuration
# ==============================================================================
OWNER_ADMIN_EMAIL = "ma1979368@gmail.com"
JOB_ID = os.environ.get("JOB_ID", "").strip()
RUNWARE_API_KEY = os.environ.get("RUNWARE_API_KEY", "").strip()
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://kljpelpjdzoagpxwdsnr.supabase.co").strip().rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
GOOGLE_CLIENT_ID = (
    os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    or "8449628626-383b2k7efdo40c92s927dbme15nt7pda.apps.googleusercontent.com"
)
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()

SB_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}

HAS_RAQM = bool(features.check("raqm"))

# ==============================================================================
# Comprehensive World Languages & Dialects Voice Map (Edge TTS — Male & Female)
# ==============================================================================
VOICE_MAP = {
    # Arabic Dialects (15 dialects)
    "ar-EG": {"male": "ar-EG-ShakirNeural", "female": "ar-EG-SalmaNeural"},
    "ar-SA": {"male": "ar-SA-HamedNeural", "female": "ar-SA-ZariyahNeural"},
    "ar-AE": {"male": "ar-AE-HamdanNeural", "female": "ar-AE-FatimaNeural"},
    "ar-KW": {"male": "ar-KW-FahedNeural", "female": "ar-KW-NouraNeural"},
    "ar-QA": {"male": "ar-QA-MoazNeural", "female": "ar-QA-AmalNeural"},
    "ar-JO": {"male": "ar-JO-TaimNeural", "female": "ar-JO-SanaNeural"},
    "ar-LB": {"male": "ar-LB-RamiNeural", "female": "ar-LB-LaylaNeural"},
    "ar-SY": {"male": "ar-SY-LaithNeural", "female": "ar-SY-AmanyNeural"},
    "ar-IQ": {"male": "ar-IQ-BasselNeural", "female": "ar-IQ-RanaNeural"},
    "ar-MA": {"male": "ar-MA-JamalNeural", "female": "ar-MA-MounaNeural"},
    "ar-DZ": {"male": "ar-DZ-IsmaelNeural", "female": "ar-DZ-AminaNeural"},
    "ar-TN": {"male": "ar-TN-HediNeural", "female": "ar-TN-ReemNeural"},
    "ar-LY": {"male": "ar-LY-OmarNeural", "female": "ar-LY-ImanNeural"},
    "ar-YE": {"male": "ar-YE-SalehNeural", "female": "ar-YE-MaryamNeural"},
    "ar-OM": {"male": "ar-OM-AbdullahNeural", "female": "ar-OM-AyshaNeural"},
    # English Dialects
    "en-US": {"male": "en-US-AndrewNeural", "female": "en-US-AvaNeural"},
    "en-GB": {"male": "en-GB-RyanNeural", "female": "en-GB-SoniaNeural"},
    "en-AU": {"male": "en-AU-WilliamNeural", "female": "en-AU-NatashaNeural"},
    "en-CA": {"male": "en-CA-LiamNeural", "female": "en-CA-ClaraNeural"},
    "en-IN": {"male": "en-IN-PrabhatNeural", "female": "en-IN-NeerjaNeural"},
    # European Languages
    "fr-FR": {"male": "fr-FR-HenriNeural", "female": "fr-FR-DeniseNeural"},
    "fr-CA": {"male": "fr-CA-AntoineNeural", "female": "fr-CA-SylvieNeural"},
    "es-ES": {"male": "es-ES-AlvaroNeural", "female": "es-ES-ElviraNeural"},
    "es-MX": {"male": "es-MX-JorgeNeural", "female": "es-MX-DaliaNeural"},
    "es-AR": {"male": "es-AR-TomasNeural", "female": "es-AR-ElenaNeural"},
    "de-DE": {"male": "de-DE-ConradNeural", "female": "de-DE-KatjaNeural"},
    "it-IT": {"male": "it-IT-DiegoNeural", "female": "it-IT-ElsaNeural"},
    "pt-BR": {"male": "pt-BR-AntonioNeural", "female": "pt-BR-FranciscaNeural"},
    "pt-PT": {"male": "pt-PT-DuarteNeural", "female": "pt-PT-RaquelNeural"},
    "ru-RU": {"male": "ru-RU-DmitryNeural", "female": "ru-RU-SvetlanaNeural"},
    "nl-NL": {"male": "nl-NL-MaartenNeural", "female": "nl-NL-ColetteNeural"},
    "pl-PL": {"male": "pl-PL-MarekNeural", "female": "pl-PL-ZofiaNeural"},
    "sv-SE": {"male": "sv-SE-MattiasNeural", "female": "sv-SE-SofieNeural"},
    "el-GR": {"male": "el-GR-NestorasNeural", "female": "el-GR-AthinaNeural"},
    "uk-UA": {"male": "uk-UA-OstapNeural", "female": "uk-UA-PolinaNeural"},
    # Middle East, Asian & African Languages
    "tr-TR": {"male": "tr-TR-AhmetNeural", "female": "tr-TR-EmelNeural"},
    "fa-IR": {"male": "fa-IR-FaridNeural", "female": "fa-IR-DilaraNeural"},
    "ur-PK": {"male": "ur-PK-AsadNeural", "female": "ur-PK-UzmaNeural"},
    "hi-IN": {"male": "hi-IN-MadhurNeural", "female": "hi-IN-SwaraNeural"},
    "bn-BD": {"male": "bn-BD-PradeepNeural", "female": "bn-BD-NabanitaNeural"},
    "id-ID": {"male": "id-ID-ArdiNeural", "female": "id-ID-GadisNeural"},
    "ms-MY": {"male": "ms-MY-OsmanNeural", "female": "ms-MY-YasminNeural"},
    "vi-VN": {"male": "vi-VN-NamMinhNeural", "female": "vi-VN-HoaiMyNeural"},
    "th-TH": {"male": "th-TH-NiwatNeural", "female": "th-TH-PremwadeeNeural"},
    "zh-CN": {"male": "zh-CN-YunxiNeural", "female": "zh-CN-XiaoxiaoNeural"},
    "ja-JP": {"male": "ja-JP-KeitaNeural", "female": "ja-JP-NanamiNeural"},
    "ko-KR": {"male": "ko-KR-InJoonNeural", "female": "ko-KR-SunHiNeural"},
    "fil-PH": {"male": "fil-PH-AngeloNeural", "female": "fil-PH-BlessicaNeural"},
    "sw-KE": {"male": "sw-KE-RafikiNeural", "female": "sw-KE-ZuriNeural"},
}


# ==============================================================================
# Supabase Helpers (Exact Live Schema Match)
# ==============================================================================
def update_job(fields: dict):
    if not JOB_ID or not SUPABASE_KEY:
        return
    fields["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        requests.patch(
            f"{SUPABASE_URL}/rest/v1/render_jobs?id=eq.{JOB_ID}",
            headers=SB_HEADERS,
            json=fields,
            timeout=20,
        )
    except Exception as exc:
        print(f"[WARN] Failed updating render_jobs: {exc}", flush=True)


def get_job() -> dict:
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/render_jobs?id=eq.{JOB_ID}&select=*",
        headers=SB_HEADERS,
        timeout=20,
    )
    r.raise_for_status()
    rows = r.json()
    if not rows:
        raise RuntimeError(f"Job not found: {JOB_ID}")
    return rows[0]


def get_channel(user_email: str, slot_number: int) -> dict:
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/channels?user_email=ilike.{requests.utils.quote(user_email)}&slot_number=eq.{slot_number}&select=*",
        headers=SB_HEADERS,
        timeout=20,
    )
    r.raise_for_status()
    rows = r.json()
    return rows[0] if rows else {}


def parse_balance_from_ai_provider(raw: str) -> tuple[float, int, float]:
    s = str(raw or "")
    cr = re.search(r"CR:([0-9.]+)", s)
    rwd = re.search(r"RWD:(\d+)", s)
    paid = re.search(r"PAID:([0-9.]+)", s)
    return (
        float(cr.group(1)) if cr else 0.0,
        int(rwd.group(1)) if rwd else 0,
        float(paid.group(1)) if paid else 0.0,
    )


def deduct_user_minutes_and_log(job: dict, youtube_video_id: str, youtube_url: str):
    email = str(job["user_email"] or "").strip()
    cost_min = float(job.get("cost_minutes") or 0.5)

    if email.lower() != OWNER_ADMIN_EMAIL.lower():
        pr = requests.get(
            f"{SUPABASE_URL}/rest/v1/profiles?email=ilike.{requests.utils.quote(email)}&select=ai_provider",
            headers=SB_HEADERS,
            timeout=20,
        )
        if pr.ok and pr.json():
            raw_meta = pr.json()[0].get("ai_provider") or ""
            cur_bal, rwd, paid = parse_balance_from_ai_provider(raw_meta)
            new_bal = round(max(0.0, cur_bal - cost_min), 2)
            encoded = f"CR:{new_bal}|RWD:{rwd}|PAID:{paid}"
            requests.patch(
                f"{SUPABASE_URL}/rest/v1/profiles?email=ilike.{requests.utils.quote(email)}",
                headers=SB_HEADERS,
                json={"ai_provider": encoded},
                timeout=20,
            )

    date_key = job.get("date_key") or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    try:
        requests.post(
            f"{SUPABASE_URL}/rest/v1/publish_logs",
            headers=SB_HEADERS,
            json={
                "user_email": email,
                "slot_number": int(job.get("slot_number") or 1),
                "channel_name": job.get("channel_name") or f"Channel #{job.get('slot_number', 1)}",
                "date_key": date_key,
                "time_slot": job.get("time_slot") or "Instant",
                "video_title": job.get("video_title") or "قصة قصيرة",
                "status": "success",
                "youtube_video_id": youtube_video_id,
                "video_url": youtube_url,
                "error_reason": "",
                "is_scheduled": job.get("trigger_source") == "cron",
            },
            timeout=20,
        )
    except Exception as exc:
        print(f"[WARN] publish_logs insert skipped: {exc}", flush=True)


# ==============================================================================
# Step 1: Real Viral Story Script, Mood & Scene Prompt Generator
# ==============================================================================
def compute_scene_count(duration_sec: int) -> int:
    duration_sec = max(5, min(3600, int(duration_sec)))
    if duration_sec <= 60:
        return max(2, math.ceil(duration_sec / 5))
    return max(12, min(260, math.ceil(duration_sec / 14)))


def is_arabic_language(language: str, voice_locale: str = "") -> bool:
    lang_l = str(language or "").lower()
    loc_l = str(voice_locale or "").lower()
    return ("عرب" in lang_l) or ("arab" in lang_l) or loc_l.startswith("ar") or ("مصر" in lang_l) or ("سعود" in lang_l)


def detect_story_mood(niche: str, title: str = "", raw_mood: str = "") -> str:
    m = str(raw_mood or "").strip().lower()
    if m in ("epic", "mystery", "sad", "happy", "calm"):
        return m
    text = f"{niche} {title}".lower()
    if any(k in text for k in ["mystery", "suspense", "night", "horror", "space", "ocean", "غامض", "لغز", "تشويق", "رعب", "فضاء", "سر"]):
        return "mystery"
    if any(k in text for k in ["sad", "cry", "tears", "poor", "حزين", "أبكى", "دموع", "فقد", "فقير", "مؤثر"]):
        return "sad"
    if any(k in text for k in ["kids", "pixar", "fun", "comedy", "amazing", "wonder", "أطفال", "كوميدي", "ترفيه", "مضحك", "معلومة"]):
        return "happy"
    if any(k in text for k in ["success", "wealth", "sport", "football", "epic", "battle", "نجاح", "ثروة", "حماس", "رياض", "أسطورة", "مليونير"]):
        return "epic"
    if any(k in text for k in ["islam", "wisdom", "book", "calm", "stoic", "حكم", "تاريخ", "تأمل", "كتاب"]):
        return "calm"
    return "epic"


def extract_json_object(raw_text: str) -> dict:
    cleaned = re.sub(r"```(?:json)?", "", str(raw_text or ""), flags=re.IGNORECASE).replace("```", "").strip()
    try:
        return json.loads(cleaned)
    except Exception:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        return json.loads(cleaned[start : end + 1])
    raise ValueError("No valid JSON object found in LLM output")


def resolve_visual_style_prompt(style: str, niche: str = "") -> tuple[str, bool]:
    """
    Map every selected Omniposts art style (English or Arabic) to a crisp,
    model-optimized English visual prompt, and detect whether the topic/style
    should enforce bright, expressive, clear-faced visuals (never dark silhouettes).
    """
    st = str(style or "").strip().lower()
    ni = str(niche or "").strip().lower()

    is_dark_requested = any(k in ni for k in ["horror", "scary", "ghost", "رعب", "مخيف", "أشباح", "جريمة", "crime", "mystery", "غموض"]) or (
        "dark luxury" in st or "moody" in st or "داكنة" in st
    )
    is_kids_or_bright = any(k in ni for k in ["kid", "child", "bedtime", "cartoon", "animal", "funny", "أطفال", "طفل", "كرتون", "مضحك", "قصص أطفال", "هادفة"]) or any(
        k in st for k in ["pixar", "disney", "storybook", "بيكسار", "قصص مصورة", "ghibli", "anime", "أنمي"]
    )

    if "pixar" in st or "disney" in st or "بيكسار" in st:
        base = (
            "3D Pixar and Disney animated movie still, bright cheerful daylight lighting, "
            "adorable expressive 3D characters facing the camera with clear detailed faces and big sparkling eyes, "
            "vibrant rich colors, soft global illumination, Octane 3D render, ultra detailed"
        )
        return base, True
    if "storybook" in st or "قصص مصورة" in st:
        base = (
            "Charming colorful children's storybook illustration, warm sunny daylight, "
            "friendly smiling characters with clear expressive faces, rich vibrant pastel palette, magical whimsical world, crisp art"
        )
        return base, True
    if "anime" in st or "ghibli" in st or "أنمي" in st:
        base = (
            "Vibrant Studio Ghibli Japanese anime film still, crisp cel shading, "
            "expressive anime characters facing the camera with clear detailed faces and eyes, bright lush sky and vivid colors"
        )
        return base, (not is_dark_requested)
    if "historical" in st or "oil painting" in st or "تاريخي" in st:
        base = (
            "Epic historical documentary film art, rich museum-grade painting style, "
            "clear expressive character faces, authentic period clothing, warm dramatic golden lighting, ultra detailed"
        )
        return base, False
    if "dark luxury" in st or "moody" in st or "داكنة" in st:
        base = (
            "Sleek luxury editorial 8K cinematography, crisp studio rim lighting, "
            "sharp clear foreground subject and refined rich colors, modern high-end aesthetic"
        )
        return base, False
    if "realistic" in st or "واقعي" in st or "8k" in st:
        base = (
            "Hyper-realistic 8K documentary photography, sharp focus on clear expressive human faces and authentic details, "
            "natural daylight or clean balanced studio lighting, ARRI Alexa 35mm cinema lens"
        )
        return base, (is_kids_or_bright and not is_dark_requested)

    if is_kids_or_bright and not is_dark_requested:
        return (
            "Vibrant 3D Pixar style illustration, bright joyful daylight, clear expressive character faces looking toward camera, colorful detailed world"
        ), True

    return (
        f"{style or 'Cinematic 8K photography'}, vivid balanced lighting, clear detailed faces and expressive subjects, sharp focus"
    ), False


def build_rich_fallback_story(niche: str, style: str, language: str, voice_locale: str, scene_count: int, short_tag: str) -> dict:
    """Rich, niche-aware storytelling fallback bank (bright & clear-faced for kids/general, custom-topic aware)."""
    low = f"{niche} {style}".lower()
    is_ar = is_arabic_language(language, voice_locale)
    is_eg = "eg" in (voice_locale or "").lower() or "مصر" in (language or "")
    style_desc, force_bright = resolve_visual_style_prompt(style, niche)
    bright_suffix = (
        ", bright sunny daylight, vibrant cheerful colors, clear expressive faces facing camera, no dark shadows, no silhouette, no text, no watermark"
        if force_bright
        else ", vivid balanced lighting, clear detailed faces and subjects, no text, no watermark"
    )

    is_kids = any(k in low for k in ["kid", "child", "bedtime", "أطفال", "طفل", "هادفة", "storybook", "cartoon"])
    is_horror = any(k in low for k in ["horror", "scary", "ghost", "رعب", "غموض", "مخيف", "جريمة"])
    is_science = any(k in low for k in ["science", "space", "fact", "tech", "ai", "علم", "فضاء", "حقائق", "معلومات", "تكنولوجيا"])
    is_money = any(k in low for k in ["money", "business", "wealth", "success", "مال", "أعمال", "نجاح", "ثروة", "تحفيز"])

    if is_ar:
        if is_kids:
            title = "الأرنب الشجاع والغابة المضيئة 🐰✨"
            desc = "قصة أطفال هادفة وممتعة تعلم الشجاعة ومساعدة الأصدقاء! اشترك لمتابعة قصص جديدة يومياً. #قصص_أطفال #حكايات #كرتون"
            tags = ["قصص أطفال", "حكايات", "بيكسار", "أطفال"]
            mood = "happy"
            beats = [
                ("في غابة مشمسة مليانة ألوان، كان فيه أرنب صغير اسمه بيبو بيحب يساعد كل أصحابه." if is_eg else "في غابة مشمسة مليئة بالألوان، عاش أرنب صغير لطيف يحب مساعدة جميع أصدقائه.",
                 "Cute cheerful little white bunny wearing a small blue scarf smiling in a bright sunny green meadow filled with colorful flowers, facing camera"),
                ("في يوم من الأيام، شاف عصفورة صغيرة وقعت من عشها وكانت خايفة جداً." if is_eg else "في أحد الأيام، رأى عصفورة صغيرة سقطت من عشها وكانت تشعر بالخوف.",
                 "Adorable baby yellow bird sitting on soft grass looking up with big expressive eyes while the friendly little bunny gently approaches in warm morning sunlight"),
                ("بيبو فكر بسرعة، ونادى على صحابه السنجاب والسلحفاة عشان يتعاونوا سوا." if is_eg else "فكر الأرنب بسرعة، ونادى صديقيه السنجاب والسلحفاة ليتعاونوا معاً.",
                 "Cute smiling bunny, cheerful orange squirrel, and friendly green turtle talking happily together under a tall sunny oak tree, colorful vibrant world"),
                ("بالتعاون، عملوا سلم صغير من الفروع ورجعوا العصفورة لأمها في العش بأمان." if is_eg else "بالتعاون والعمل الجماعي، أعادوا العصفورة الصغيرة بأمان إلى أمها في العش.",
                 "Joyful mother bird hugging her baby bird inside a cozy sunlit tree nest while the bunny and squirrel wave happily below, bright golden daylight"),
                ("ومن اليوم ده، كل حيوانات الغابة اتعلمت إن التعاون بيخلي أي مستحيل سهل!" if is_eg else "ومنذ ذلك اليوم، تعلمت كل حيوانات الغابة أن التعاون يصنع المعجزات!",
                 "Happy celebration picnic of cute forest animal friends smiling together under a bright rainbow and sunny blue sky, cheerful warm colors"),
            ]
        elif is_horror:
            title = "الباب المقفول في آخر الممر 🚪"
            desc = "قصة غموض وتشويق قصيرة لن تنساها! #غموض #قصص #حكايات"
            tags = ["غموض", "قصص", "تشويق", "شورتس"]
            mood = "mystery"
            beats = [
                ("الساعة كانت اتنين بالليل لما سمع خبط هادي على باب الشقة اللي فوقيه." if is_eg else "كانت الساعة الثانية ليلاً حين سمع طرقاً هادئاً على باب الشقة العلوية.",
                 "Young man looking up curiously in a warmly lit hallway with wooden doors, clear expressive face, atmospheric evening lighting"),
                ("الغريب إن الشقة دي مقفولة من عشر سنين ومفيش فيها أي ساكن!" if is_eg else "الغريب أن تلك الشقة مغلقة منذ عشر سنوات ولا يسكنها أحد!",
                 "Close-up of an antique wooden apartment door with brass handle and soft hallway lamp light, intriguing suspenseful framing"),
                ("لما طلع يبص، لقى ورقة قديمة تحت الباب مكتوب عليها اسمه بخط واضح." if is_eg else "وعندما صعد ليتفقد الأمر، وجد رسالة قديمة تحت الباب تحمل اسمه.",
                 "Hand picking up a folded vintage cream envelope from a wooden floor under warm hallway light, crisp cinematic detail"),
                ("فتح الورقة واتصدم لما عرف إن ده كان مفتاح سر عائلي مدفون من سنين!" if is_eg else "فتح الرسالة واندهش حين اكتشف أنها مفتاح سر عائلي قديم!",
                 "Surprised young man smiling with realization holding an open letter and a glowing brass key in warm indoor lighting, clear face"),
            ]
        elif is_science:
            title = "معلومة مذهلة عن كوكبنا والعالم 🌍"
            desc = "حقائق علمية مدهشة في ثوانٍ! اشترك لمزيد من المعلومات اليومية. #معلومات #علوم #حقائق"
            tags = ["معلومات", "حقائق", "علوم", "شورتس"]
            mood = "epic"
            beats = [
                ("هل تعرف إن المحيطات لسه فيها أكتر من 80% مناطق محدش استكشفها لحد النهارده؟" if is_eg else "هل تعلم أن أكثر من 80% من المحيطات لم يتم استكشافها حتى اليوم؟",
                 "Crystal clear turquoise tropical ocean from above with bright sunlight shimmering on vibrant coral reefs and colorful fish"),
                ("تحت المية دي فيه جبال أطول من جبل إيفرست وبحيرات كاملة تحت البحر!" if is_eg else "تحت هذه المياه توجد جبال أطول من قمة إيفرست وبحيرات مائية كاملة!",
                 "Majestic sunlit underwater mountain ridges and glowing colorful marine life in vivid blue ocean water, ultra crisp"),
                ("وكل سنة العلماء بيكتشفوا كائنات جديدة بألوان وأشكال كأنها من كوكب تاني." if is_eg else "وكل عام يكتشف العلماء كائنات بحرية جديدة بألوان مدهشة للغاية.",
                 "Vibrant bioluminescent jellyfish and colorful tropical sea creatures swimming in crystal blue water, clear sharp focus"),
                ("عالمنا مليان أسرار مدهشة لسه بنكتشفها كل يوم!" if is_eg else "عالمنا مليء بالأسرار الرائعة التي نكتشفها كل يوم!",
                 "Smiling marine explorer looking through a bright glass research submarine window at colorful reefs, clear expressive face"),
            ]
        elif is_money:
            title = "العادة البسيطة اللي بتغيّر مستقبلك 💡"
            desc = "خطوة عملية واحدة تصنع فرقاً كبيراً في نجاحك. #نجاح #تطوير_الذات #بيزنس"
            tags = ["نجاح", "بيزنس", "تحفيز", "تطوير الذات"]
            mood = "epic"
            beats = [
                ("أكبر فرق بين اللي بينجح واللي بيقف مكانه مش الحظ... دي عادة يومية بسيطة." if is_eg else "الفرق الأكبر بين النجاح والتوقف ليس الحظ، بل عادة يومية بسيطة.",
                 "Confident young entrepreneur smiling at a bright sunlit modern desk with notebook and coffee, clear detailed face, warm daylight"),
                ("كل يوم يخصّص ساعة واحدة بس يتعلم فيها مهارة جديدة ويطبّقها عملي." if is_eg else "يخصص كل يوم ساعة واحدة لتعلم مهارة جديدة وتطبيقها عملياً.",
                 "Focused creative person working on a sleek laptop in a bright modern sunlit studio with plants, clear face and warm natural light"),
                ("بعد شهور قليلة، الساعة اليومية دي بتتحول لمصدر دخل وفرص ما كانش يتخيلها." if is_eg else "وبعد أشهر قليلة، تتحول هذه الساعة اليومية إلى مصدر دخل وفرص حقيقية.",
                 "Happy smiling business owner celebrating success in a bright modern glass office overlooking a sunny city, crisp sharp detail"),
                ("ابدأ بساعة واحدة النهارده... وهتشكر نفسك بعد سنة!" if is_eg else "ابدأ بساعة واحدة اليوم، وستشكر نفسك بعد عام!",
                 "Inspiring bright sunrise over a vibrant modern city with a joyful confident person smiling toward the morning sun, clear face"),
            ]
        else:
            clean_topic = str(niche or "قصة ملهمة").strip()[:60]
            title = f"{clean_topic}"[:85]
            desc = f"فيديو مميز عن {clean_topic}. اشترك في القناة لمتابعة كل جديد يومياً! #قصص #محتوى #شورتس"
            tags = ["قصص", "معلومات", "شورتس", "فيديو"]
            mood = "happy" if force_bright else "epic"
            beats = [
                (f"النهارده هنتكلم عن {clean_topic} بطريقة بسيطة وممتعة هتفاجئك!" if is_eg else f"اليوم سنستكشف {clean_topic} بطريقة شيقة وممتعة!",
                 f"Bright vivid detailed scene illustrating {clean_topic}, cheerful expressive characters facing camera, clear faces, crisp natural lighting"),
                ("كتير من الناس ميعرفوش التفاصيل الحقيقية ورا الموضوع ده." if is_eg else "الكثير من الناس لا يعرفون التفاصيل الرائعة خلف هذا الموضوع.",
                 f"Close-up rich detailed visual exploring {clean_topic}, vibrant balanced colors, clear expressive subjects, ultra sharp"),
                ("لما تبص للصورة الكاملة، هتكتشف فكرة جديدة تماماً تغيّر نظرتك." if is_eg else "وعندما ترى الصورة الكاملة، ستكتشف فكرة جديدة تغير نظرتك تماماً.",
                 f"Inspiring dynamic wide scene showcasing the key highlight of {clean_topic}, bright clear lighting, vivid colors"),
                ("شاركنا رأيك في التعليقات واشترك عشان تشوف الجزء الجاي!" if is_eg else "شاركنا رأيك في التعليقات واشترك لمتابعة المزيد!",
                 f"Warm uplifting closing scene about {clean_topic}, smiling expressive character looking at camera, sunny golden daylight"),
            ]
    else:
        if is_kids:
            title = "The Brave Little Bunny's Big Adventure"
            desc = "A heartwarming 3D kids story about kindness, courage, and teamwork! Subscribe for new bedtime stories every day. #KidsStories #PixarStyle #Shorts"
            tags = ["KidsStories", "BedtimeStory", "3DAnimation", "Shorts"]
            mood = "happy"
            beats = [
                ("In a sunny meadow bursting with flowers, a tiny bunny named Pip loved helping everyone.",
                 "Cute joyful little white bunny wearing a blue scarf smiling in a bright sunny colorful flower meadow, facing camera with big sparkling eyes"),
                ("One bright morning, Pip spotted a little yellow bird who had tumbled out of her cozy nest.",
                 "Adorable baby yellow bird sitting on lush green grass looking up with big expressive eyes while the friendly bunny gently greets her in warm morning sunlight"),
                ("Pip quickly called his best friends, a playful squirrel and a wise little turtle, to team up.",
                 "Cute smiling bunny, cheerful orange squirrel, and happy green turtle talking together excitedly under a sunny oak tree, vibrant cheerful colors"),
                ("Working together, they built a soft leafy ramp and lifted the baby bird safely back to her mom.",
                 "Happy mother bird hugging her baby bird in a sunlit cozy tree nest while the bunny and squirrel cheer happily below, bright sunny daylight"),
                ("That day, the whole forest learned that teamwork turns even the smallest friend into a hero!",
                 "Joyful celebration picnic of cute forest animal friends smiling together under a bright rainbow and blue sky, vibrant cheerful colors"),
            ]
        else:
            clean_topic = str(niche or "Amazing Story").strip()[:60]
            title = f"{clean_topic}: What Nobody Told You"[:85]
            desc = f"Discover the real story behind {clean_topic}. Subscribe for new videos every day! #Storytime #Viral #Shorts"
            tags = ["Storytime", "Facts", "Viral", "Shorts"]
            mood = "happy" if force_bright else "epic"
            beats = [
                (f"Here is the fascinating truth about {clean_topic} that almost everyone overlooks.",
                 f"Vivid bright detailed opening scene depicting {clean_topic}, clear expressive faces looking toward camera, crisp balanced lighting"),
                (f"Look closely at how {clean_topic} actually works behind the scenes.",
                 f"Detailed colorful close-up illustrating an intriguing aspect of {clean_topic}, sharp focus, bright natural lighting"),
                (f"Once you see the full picture of {clean_topic}, everything suddenly clicks into place.",
                 f"Inspiring sunlit wide scene showing the breakthrough moment of {clean_topic}, clear expressive people and vivid colors"),
                (f"What surprised you most about {clean_topic}? Tell us in the comments!",
                 f"Uplifting bright closing scene celebrating {clean_topic}, smiling expressive character facing camera, golden daylight"),
            ]

    scenes = []
    for idx in range(scene_count):
        nar, img_p = beats[idx % len(beats)]
        scenes.append({
            "narration": nar,
            "image_prompt": f"{style_desc}, {img_p}{bright_suffix}",
        })
    if short_tag and "#shorts" not in title.lower():
        title = f"{title}{short_tag}"[:95]
    return {
        "title": title,
        "description": desc,
        "tags": tags,
        "mood": mood,
        "scenes": scenes,
    }


def _parse_llm_story_response(raw: str, niche: str, style: str, is_ar: bool, scene_count: int, short_tag: str) -> dict | None:
    if not raw or not raw.strip():
        return None
    parsed = extract_json_object(raw)
    scenes = parsed.get("scenes") or []
    if len(scenes) < 2:
        return None
    clean_scenes = []
    for s in scenes:
        if not isinstance(s, dict):
            continue
        nar = str(s.get("narration") or "").strip()
        img_p = str(s.get("image_prompt") or "").strip()
        if nar and img_p:
            clean_scenes.append({"narration": nar, "image_prompt": img_p})
    if len(clean_scenes) < 2:
        return None
    while len(clean_scenes) < scene_count:
        clean_scenes.append(clean_scenes[-1])
    clean_scenes = clean_scenes[:scene_count]
    title = str(parsed.get("title") or "").strip()[:90]
    desc = str(parsed.get("description") or title).strip()
    if is_ar and not re.search(r"[\u0600-\u06FF]", title):
        return None
    if short_tag and "#shorts" not in title.lower():
        title = f"{title}{short_tag}"[:95]
    mood = detect_story_mood(niche, title, parsed.get("mood") or "")
    return {
        "title": title,
        "description": desc,
        "tags": parsed.get("tags") or (["قصص", "حكايات", "شورتس"] if is_ar else ["Storytime", "Shorts"]),
        "mood": mood,
        "scenes": clean_scenes,
    }


def generate_story_package(
    niche: str,
    style: str,
    language: str,
    voice_locale: str,
    duration_sec: int,
    scene_count: int,
    is_vertical: bool,
) -> dict:
    approx_words = max(20, min(7500, int(duration_sec * 2.2)))
    short_tag = " #Shorts" if (is_vertical and duration_sec <= 60) else ""
    is_ar = is_arabic_language(language, voice_locale)
    style_desc, force_bright = resolve_visual_style_prompt(style, niche)

    visual_rules = (
        "CRITICAL VISUAL PROMPT RULES (for every scene's image_prompt in English):\n"
        f"- EVERY image_prompt MUST visually depict THIS EXACT topic: '{niche}' in the style: '{style_desc}'.\n"
        "- Describe concrete, specific characters, objects, actions, facial expressions, and backgrounds directly matching that scene's narration.\n"
        "- NEVER draw dark silhouettes, faceless figures, people turned away from the camera, or gloomy dark caves unless the topic explicitly asks for horror.\n"
        + (
            "- BRIGHTNESS & FACES MANDATORY: Use bright sunny daylight, vibrant joyful colors, and clear cute expressive character faces looking toward the camera with big detailed eyes!\n"
            if force_bright
            else "- Keep lighting vivid, balanced, and crisp with clear detailed character faces and distinct visual variety across every scene.\n"
        )
    )

    lang_rules = (
        f"CRITICAL LANGUAGE & STORYTELLING RULES: Write 'title', 'description', 'tags', and EVERY scene's 'narration' "
        f"100% in natural, authentic '{language}' (locale: {voice_locale}). "
        + (
            "ZERO English/Latin words allowed in title, description, or narration (except optional #Shorts at the end of description). "
            "PRONUNCIATION PERFECTION: Add light Arabic diacritics (تشكيل) on any ambiguous words and use clear punctuation (commas, periods, exclamation marks) so voice narration sounds 100% human with zero mispronunciations. "
            "VIRAL STORY STRUCTURE (MANDATORY): Scene 1 MUST start with an irresistible 2-second hook (shocking moment, curious question, or immediate conflict — NEVER start with boring clichés like 'في يوم من الأيام' or 'النهارده هنتكلم عن'). "
            "Build escalating tension/curiosity in every scene and deliver a memorable emotional payoff or surprising twist in the final scene!"
            if is_ar
            else "VIRAL STORY STRUCTURE (MANDATORY): Scene 1 MUST start with an irresistible 2-second hook (immediate action, shocking fact, or curious conflict — NEVER start with boring clichés like 'Once upon a time' or 'Today we will talk about'). "
                 "Build escalating curiosity in every scene and deliver a memorable emotional payoff or surprising twist in the final scene!"
        )
    )

    system_prompt = (
        "You are a top 1% viral YouTube Shorts & faceless storytelling director (10M+ views style). "
        "Return ONLY valid JSON with no markdown fences and no extra commentary. "
        "NEVER mention any AI tool, website name, or 'Generated automatically' anywhere. "
        "CHARACTER CONSISTENCY RULE: Define ONE specific recurring main character (exact age/species, hair/fur, outfit colors) and repeat that EXACT character description in EVERY scene's image_prompt so the entire video stars the SAME hero in different camera angles and actions!\n"
        + lang_rules + "\n" + visual_rules
    )
    user_prompt = (
        f"Create a gripping, high-retention 100% original story strictly about this topic: '{niche}'.\n"
        f"Visual style: '{style}' ({style_desc}).\n"
        f"Language & Dialect: '{language}' ({voice_locale}).\n"
        f"Target duration: {duration_sec} seconds (~{approx_words} words total across all scenes).\n"
        f"Divide the story into EXACTLY {scene_count} fast-paced sequential scenes (Scene 1 = instant hook, middle scenes = rising action/conflict, final scene = unforgettable twist/payoff).\n"
        f"Keep each scene's narration punchy and dramatic (7 to 13 words per scene) for high retention.\n"
        f"Keep the SAME recurring hero/subject visually consistent across every scene's image_prompt, varying camera angles (close-up face, medium action shot, wide establishing shot).\n"
        'Also classify the emotional soundtrack mood as ONE of: "epic", "mystery", "sad", "happy", or "calm".\n'
        "Return strict JSON matching this exact schema:\n"
        "{\n"
        '  "title": "Irresistible curiosity-gap viral YouTube title strictly in the requested language (max 82 chars)",\n'
        '  "description": "Engaging YouTube description strictly in the requested language with 4 relevant hashtags",\n'
        '  "tags": ["tag1", "tag2", "tag3", "tag4"],\n'
        '  "mood": "epic | mystery | sad | happy | calm",\n'
        '  "scenes": [\n'
        '    {"narration": "Punchy spoken story line strictly in the requested language/dialect", "image_prompt": "Rich specific English visual prompt featuring the consistent main character, clear expressive face, dynamic action, vivid lighting, no text in image"}\n'
        "  ]\n"
        "}"
    )

    # 1. Try fast verified Runware LLM models first
    runware_models = [
        "deepseek:v4.1@flash",
        "google:gemini@3.5-flash",
        "google:gemini@3.1-flash-lite",
        "minimax:m3.1@flash",
        "alibaba:qwen@4-max",
    ]
    if RUNWARE_API_KEY:
        for model_id in runware_models:
            try:
                resp = requests.post(
                    "https://api.runware.ai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {RUNWARE_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model_id,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": 0.85,
                    },
                    timeout=55,
                )
                if not resp.ok:
                    print(f"[WARN] Runware LLM {model_id} HTTP {resp.status_code}: {resp.text[:200]}", flush=True)
                    continue
                data = resp.json()
                raw = (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
                story_pkg = _parse_llm_story_response(raw, niche, style, is_ar, scene_count, short_tag)
                if story_pkg:
                    print(f"[OK] Generated story via Runware LLM ({model_id}) [mood={story_pkg['mood']}]: {story_pkg['title']}", flush=True)
                    return story_pkg
                print(f"[WARN] Runware LLM {model_id} returned invalid/non-matching JSON, trying next...", flush=True)
            except Exception as exc:
                print(f"[WARN] Runware LLM {model_id} error: {exc}", flush=True)

    # 2. Free Zero-Key Backup LLM (Pollinations OpenAI-compatible API) so custom topics ALWAYS work even on low Runware balance
    for p_model in ["openai", "mistral"]:
        try:
            resp = requests.post(
                "https://text.pollinations.ai/openai",
                headers={"Content-Type": "application/json"},
                json={
                    "model": p_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.85,
                    "jsonMode": True,
                },
                timeout=45,
            )
            if not resp.ok:
                print(f"[WARN] Free Backup LLM ({p_model}) HTTP {resp.status_code}", flush=True)
                continue
            data = resp.json()
            raw = (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
            story_pkg = _parse_llm_story_response(raw, niche, style, is_ar, scene_count, short_tag)
            if story_pkg:
                print(f"[OK] Generated custom story via Free Backup LLM ({p_model}): {story_pkg['title']}", flush=True)
                return story_pkg
        except Exception as exc:
            print(f"[WARN] Free Backup LLM ({p_model}) error: {exc}", flush=True)

    print("[INFO] Using niche-aware localized story fallback bank.", flush=True)
    return build_rich_fallback_story(niche, style, language, voice_locale, scene_count, short_tag)


# ==============================================================================
# Step 2: Parallel Scene Image Generation (Runware FLUX.1 schnell)
# ==============================================================================
def generate_single_image(prompt: str, width: int, height: int, out_path: Path) -> str:
    # 1. Primary: Runware FLUX.1 schnell (ultra-fast when balance is available)
    if RUNWARE_API_KEY:
        payload = [
            {
                "taskType": "imageInference",
                "taskUUID": str(uuid.uuid4()),
                "model": "runware:100@1",
                "positivePrompt": prompt[:950],
                "width": width,
                "height": height,
                "steps": 4,
                "numberResults": 1,
                "outputType": "URL",
                "outputFormat": "JPEG",
                "includeCost": True,
            }
        ]
        for attempt in range(2):
            try:
                r = requests.post(
                    "https://api.runware.ai/v1",
                    headers={
                        "Authorization": f"Bearer {RUNWARE_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=35,
                )
                if r.status_code in (401, 402, 403):
                    print(f"[WARN] Runware balance/auth HTTP {r.status_code} — switching to Free FLUX backup!", flush=True)
                    break
                r.raise_for_status()
                data = r.json().get("data") or []
                if data and data[0].get("imageURL"):
                    img_url = data[0]["imageURL"]
                    img_bytes = requests.get(img_url, timeout=30).content
                    if len(img_bytes) > 5000:
                        out_path.write_bytes(img_bytes)
                        return img_url
            except Exception as exc:
                print(f"[WARN] Runware image attempt {attempt+1} failed: {exc}", flush=True)

    # 2. Automatic Free $0 FLUX Backup (Pollinations AI — zero balance required, no watermark)
    import urllib.parse
    encoded_p = urllib.parse.quote(prompt[:650], safe="")
    for attempt in range(3):
        try:
            seed = random.randint(1000, 9999999)
            free_url = f"https://image.pollinations.ai/prompt/{encoded_p}?width={width}&height={height}&model=flux&nologo=true&seed={seed}"
            resp = requests.get(free_url, timeout=60)
            if resp.ok and len(resp.content) > 8000 and "image" in (resp.headers.get("Content-Type") or "").lower():
                out_path.write_bytes(resp.content)
                print(f"[OK] Generated scene via Free $0 FLUX backup ({len(resp.content)//1024} KB)", flush=True)
                return free_url
            print(f"[WARN] Free FLUX attempt {attempt+1} HTTP {resp.status_code} ({len(resp.content)} bytes)", flush=True)
        except Exception as exc:
            print(f"[WARN] Free FLUX attempt {attempt+1} error: {exc}", flush=True)
        time.sleep(2)

    raise RuntimeError("Image generation failed on both Runware and Free FLUX backup")


def generate_all_scenes(scenes: list, style: str, is_vertical: bool, work_dir: Path, niche: str = "") -> tuple[list[Path], list[str]]:
    w, h = (768, 1344) if is_vertical else (1344, 768)
    total = len(scenes)
    paths: list[Path | None] = [None] * total
    urls: list[str] = []
    style_desc, force_bright = resolve_visual_style_prompt(style, niche)

    def _worker(i: int):
        p = work_dir / f"scene_{i:04d}.jpg"
        scene_desc = str(scenes[i].get("image_prompt") or "").strip()
        # Avoid duplicating style_desc if fallback already prepended it
        if style_desc[:28].lower() in scene_desc.lower():
            base_prompt = scene_desc
        else:
            base_prompt = f"{style_desc}. {scene_desc}"
        if force_bright:
            # Strip accidental dark words if kids/bright style is selected
            base_prompt = re.sub(r"\b(silhouette|darkness|gloomy|shadowy|pitch black|dimly lit)\b", "bright colorful", base_prompt, flags=re.IGNORECASE)
            prompt = f"{base_prompt}, bright cheerful daylight, clear expressive faces facing camera, vibrant colors, no text, no watermark"
        else:
            prompt = f"{base_prompt}, crisp balanced lighting, clear detailed faces and subjects, vivid colors, no text, no watermark"
        url = generate_single_image(prompt, w, h, p)
        return i, p, url

    completed = 0
    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = [pool.submit(_worker, i) for i in range(total)]
        for fut in as_completed(futs):
            idx, path, url = fut.result()
            paths[idx] = path
            urls.append(url)
            completed += 1
            if completed % 2 == 0 or completed == total:
                pct = 20 + int((completed / total) * 35)
                update_job({
                    "status": "imaging",
                    "progress_pct": pct,
                    "step_label": f"جاري رسم المشاهد بدقة عالية ({completed} / {total})...",
                    "preview_images": urls[:12],
                })

    return [p for p in paths if p is not None], urls


# ==============================================================================
# Step 2B: Native-Audio AI Video (Runware HeyGen Video 1.0 — heygen:video@1.0)
# ==============================================================================
def generate_heygen_video_clip(
    niche: str,
    style: str,
    language: str,
    voice_locale: str,
    duration_sec: int,
    is_vertical: bool,
    story: dict,
    out_mp4: Path,
) -> str:
    """
    Generate a complete 5-30s AI video with synchronized native dialogue, lip-sync,
    ambience, and sound effects in ONE pass using Runware HeyGen Video 1.0 (heygen:video@1.0).
    Exact 480p dimensions per Runware docs: 480x832 (9:16), 832x480 (16:9).
    """
    w, h = (480, 832) if is_vertical else (832, 480)
    dur = max(5, min(30, int(duration_sec or 15)))
    scenes = story.get("scenes") or []
    spoken_lines = " ".join(str(s.get("narration") or "").strip() for s in scenes[:3]).strip()
    visual_desc = str(scenes[0].get("image_prompt") or niche) if scenes else niche

    rich_prompt = (
        f"{style}. Topic: {niche}. Visual scene: {visual_desc}. "
        f"Expressive animated characters with natural facial expressions, smooth cinematic camera movement, "
        f"vivid lighting, no on-screen text or watermarks. "
        f"Audio & Synchronized Dialogue spoken clearly in {language} ({voice_locale}): "
        f'"{spoken_lines[:420]}" with matching natural sound effects and atmospheric ambience.'
    )[:3000]

    headers = {
        "Authorization": f"Bearer {RUNWARE_API_KEY}",
        "Content-Type": "application/json",
    }
    last_err = "Unknown HeyGen Video 1.0 error"
    for attempt in range(2):
        task_uuid = str(uuid.uuid4())
        payload = [
            {
                "taskType": "videoInference",
                "taskUUID": task_uuid,
                "model": "heygen:video@1.0",
                "positivePrompt": rich_prompt,
                "width": w,
                "height": h,
                "duration": dur,
                "numberResults": 1,
                "outputType": "URL",
                "outputFormat": "MP4",
                "deliveryMethod": "async",
                "includeCost": True,
                "settings": {"promptEnhancement": "turbo"},
            }
        ]
        try:
            update_job({
                "status": "imaging",
                "progress_pct": 35,
                "step_label": f"جاري توليد الفيديو المتحرك بالصوت والحوار المدمج بالذكاء الاصطناعي ({dur} ثانية)...",
            })
            r = requests.post("https://api.runware.ai/v1", headers=headers, json=payload, timeout=45)
            if not r.ok:
                raise RuntimeError(f"Runware HTTP {r.status_code}: {r.text[:260]}")
            init_body = r.json()
            if init_body.get("errors"):
                err0 = init_body["errors"][0]
                raise RuntimeError(f"Runware init error: {err0.get('message', err0)}")
            for item in (init_body.get("data") or []):
                if item.get("videoURL"):
                    vid_bytes = requests.get(item["videoURL"], timeout=90).content
                    out_mp4.write_bytes(vid_bytes)
                    return item["videoURL"]

            deadline = time.time() + 240
            poll_step = 0
            while time.time() < deadline:
                time.sleep(5)
                poll_step += 1
                if poll_step % 3 == 0:
                    update_job({
                        "status": "imaging",
                        "progress_pct": min(75, 35 + poll_step * 4),
                        "step_label": "جاري معالجة حركة الشخصيات ومزامنة الصوت والحوار بالذكاء الاصطناعي...",
                    })
                poll = requests.post(
                    "https://api.runware.ai/v1",
                    headers=headers,
                    json=[{"taskType": "getResponse", "taskUUID": task_uuid}],
                    timeout=30,
                )
                if not poll.ok:
                    continue
                body = poll.json()
                if body.get("errors"):
                    err0 = body["errors"][0]
                    raise RuntimeError(f"Runware poll error: {err0.get('message', err0)}")
                for item in (body.get("data") or []):
                    if item.get("status") == "error":
                        raise RuntimeError(f"HeyGen task failed: {item}")
                    vid_url = item.get("videoURL")
                    if vid_url:
                        vid_bytes = requests.get(vid_url, timeout=90).content
                        if len(vid_bytes) < 5000:
                            raise RuntimeError("Downloaded HeyGen MP4 is empty/corrupt")
                        out_mp4.write_bytes(vid_bytes)
                        print(f"[OK] HeyGen Video 1.0 clip ready ({len(vid_bytes)//1024} KB)", flush=True)
                        return vid_url
            raise RuntimeError("HeyGen Video 1.0 timed out after 240s")
        except Exception as exc:
            last_err = str(exc)
            print(f"[WARN] HeyGen Video 1.0 attempt {attempt+1} failed: {last_err}", flush=True)
            time.sleep(2)
    raise RuntimeError(f"HeyGen Video 1.0 failed: {last_err}")


# ==============================================================================
# Step 3: Multilingual / Multi-Dialect Edge TTS Voiceover (100% Free)
# ==============================================================================
def pick_voice(voice_locale: str, voice_gender: str) -> str:
    g = "female" if str(voice_gender or "").lower().startswith("f") else "male"
    entry = VOICE_MAP.get(voice_locale)
    if entry:
        return entry[g]
    prefix = (voice_locale or "ar-EG").split("-")[0].lower()
    for k, v in VOICE_MAP.items():
        if k.lower().startswith(prefix + "-"):
            return v[g]
    return VOICE_MAP["ar-EG"][g]


def _master_voice_audio(in_path: Path, out_mp3: Path):
    """Apply warm broadcast studio mastering (removes robotic metallic harshness, adds human warmth & punch)."""
    tmp_out = out_mp3.with_suffix(".master.mp3")
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(in_path),
                "-af", (
                    "highpass=f=80,"
                    "equalizer=f=180:width_type=o:width=1.4:g=2.8,"
                    "equalizer=f=3200:width_type=o:width=1.2:g=2.0,"
                    "equalizer=f=6500:width_type=o:width=1.0:g=-1.8,"
                    "acompressor=threshold=-18dB:ratio=2.8:attack=8:release=110:makeup=2,"
                    "loudnorm=I=-15:TP=-1.5:LRA=9"
                ),
                "-c:a", "libmp3lame", "-b:a", "192k", "-ar", "44100",
                str(tmp_out),
            ],
            check=True,
        )
        tmp_out.replace(out_mp3)
    except Exception:
        if in_path != out_mp3 and in_path.exists():
            in_path.replace(out_mp3)


def _try_elevenlabs_tts(text: str, is_female: bool, out_mp3: Path) -> bool:
    if not ELEVENLABS_API_KEY:
        return False
    voice_id = "21m00Tcm4TlvDq8ikWAM" if is_female else "pNInz6obpgDQGcFmaJgB"
    try:
        r = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers={
                "xi-api-key": ELEVENLABS_API_KEY,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            },
            json={
                "text": text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {"stability": 0.48, "similarity_boost": 0.78, "style": 0.35},
            },
            timeout=35,
        )
        if r.ok and len(r.content) > 2000:
            raw_mp3 = out_mp3.with_suffix(".raw.mp3")
            raw_mp3.write_bytes(r.content)
            _master_voice_audio(raw_mp3, out_mp3)
            raw_mp3.unlink(missing_ok=True)
            return True
    except Exception as exc:
        print(f"[WARN] ElevenLabs TTS fallback: {exc}", flush=True)
    return False


def _try_gemini_tts(text: str, is_female: bool, out_mp3: Path) -> bool:
    if not GEMINI_API_KEY:
        return False
    import base64
    voice_name = "Aoede" if is_female else "Charon"
    try:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent?key={GEMINI_API_KEY}",
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{"parts": [{"text": f"Speak naturally with warm storytelling emotion: {text}"}]}],
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice_name}}},
                },
            },
            timeout=40,
        )
        if r.ok:
            data = r.json()
            b64 = data["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
            pcm_bytes = base64.b64decode(b64)
            raw_pcm = out_mp3.with_suffix(".pcm")
            raw_pcm.write_bytes(pcm_bytes)
            subprocess.run(
                [
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "s16le", "-ar", "24000", "-ac", "1", "-i", str(raw_pcm),
                    "-c:a", "libmp3lame", "-b:a", "192k", str(out_mp3),
                ],
                check=True,
            )
            raw_pcm.unlink(missing_ok=True)
            _master_voice_audio(out_mp3, out_mp3)
            return True
    except Exception as exc:
        print(f"[WARN] Gemini TTS fallback: {exc}", flush=True)
    return False


async def synth_scene_audio(text: str, voice: str, out_mp3: Path):
    is_female = any(f in str(voice or "").lower() for f in ["salma", "zariyah", "fatima", "amany", "jenny", "aria", "ava", "emma", "denise", "katja", "elsa", "elvira", "nanami"])
    if _try_elevenlabs_tts(text, is_female, out_mp3):
        return
    if _try_gemini_tts(text, is_female, out_mp3):
        return
    raw_mp3 = out_mp3.with_suffix(".edge.mp3")
    comm = edge_tts.Communicate(text=text, voice=voice, rate="+8%", pitch="+2Hz" if is_female else "-2Hz")
    await comm.save(str(raw_mp3))
    _master_voice_audio(raw_mp3, out_mp3)
    raw_mp3.unlink(missing_ok=True)


def get_audio_duration(audio_path: Path) -> float:
    out = subprocess.check_output(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path),
        ],
        text=True,
    ).strip()
    return max(1.8, float(out or 4.0))


# ==============================================================================
# Step 3.5: 100% Copyright-Free Mood Soundtrack + Transition Whoosh SFX Engine
# ==============================================================================
def generate_mood_soundtrack(mood: str, total_dur: float, transition_times: list[float], out_wav: Path):
    """
    Synthesizes a warm, lush, 100% copyright-free cinematic background score matched to the story mood
    (epic, mystery, sad, happy, calm) PLUS subtle soft whoosh SFX on scene transitions.
    Uses warm multi-harmonic pads, slow LFO swells, soft plucked notes, and FFmpeg studio reverb/lowpass.
    """
    sr = 22050
    n_samples = max(sr, int(math.ceil(total_dur * sr)))

    # Chord progressions (Hz) tailored to each mood
    mood_chords = {
        "epic": [
            (73.42, 146.83, 220.00, 293.66, 349.23),   # Dm cinematic
            (58.27, 116.54, 174.61, 233.08, 293.66),   # Bbmaj7
            (65.41, 130.81, 196.00, 261.63, 329.63),   # Csus2
            (55.00, 110.00, 164.81, 220.00, 277.18),   # A major lift
        ],
        "mystery": [
            (55.00, 110.00, 164.81, 220.00, 261.63),   # Am dark pad
            (51.91, 103.83, 155.56, 207.65, 246.94),   # Ab/G# tension
            (65.41, 130.81, 196.00, 246.94, 293.66),   # Cmaj9 eerie
            (61.74, 123.47, 164.81, 220.00, 246.94),   # Bm7b5 suspense
        ],
        "sad": [
            (65.41, 130.81, 155.56, 196.00, 261.63),   # Cm warm melancholic
            (51.91, 103.83, 155.56, 196.00, 233.08),   # Abmaj7
            (77.78, 155.56, 196.00, 233.08, 293.66),   # Ebmaj7
            (58.27, 116.54, 146.83, 174.61, 233.08),   # Bb warm resolve
        ],
        "happy": [
            (98.00, 196.00, 246.94, 293.66, 392.00),   # G major bright
            (73.42, 146.83, 220.00, 293.66, 369.99),   # D major
            (82.41, 164.81, 196.00, 246.94, 329.63),   # Em7 uplifting
            (65.41, 130.81, 196.00, 246.94, 329.63),   # Cmaj7
        ],
        "calm": [
            (87.31, 174.61, 220.00, 261.63, 329.63),   # Fmaj7 peaceful
            (73.42, 146.83, 220.00, 261.63, 329.63),   # Dm9
            (58.27, 116.54, 174.61, 220.00, 293.66),   # Bbmaj7
            (65.41, 130.81, 196.00, 261.63, 329.63),   # C warm
        ],
    }

    chords = mood_chords.get(mood, mood_chords["epic"])
    chord_len = 4.0 if mood in ("calm", "sad", "mystery") else 3.2
    pulse_hz = 2.0 if mood == "epic" else (2.4 if mood == "happy" else 0.5)

    raw_wav = out_wav.with_suffix(".raw.wav")
    rng = random.Random(42)
    lp_noise = 0.0

    # Precompute transition sample windows for subtle whoosh SFX
    trans_windows = [(int((t - 0.28) * sr), int((t + 0.18) * sr), int(t * sr)) for t in transition_times]

    buf = bytearray()
    two_pi = 2.0 * math.pi
    for i in range(n_samples):
        t = i / sr
        c_idx = int(t / chord_len) % len(chords)
        local_t = t % chord_len
        chord = chords[c_idx]

        # Smooth chord envelope to eliminate any clicks between chords
        c_env = 1.0
        if local_t < 0.25:
            c_env = local_t / 0.25
        elif local_t > chord_len - 0.25:
            c_env = (chord_len - local_t) / 0.25

        # Warm breathing pad
        lfo = 0.82 + 0.18 * math.sin(two_pi * 0.22 * t)
        val = 0.0
        for idx_f, freq in enumerate(chord):
            w = 0.24 if idx_f == 0 else (0.19 if idx_f == 1 else 0.13)
            val += w * math.sin(two_pi * freq * t)
            # Soft warm detuned overtone
            if idx_f >= 1:
                val += (w * 0.28) * math.sin(two_pi * (freq * 1.003) * t)

        # Mood-specific musical character
        if mood == "epic":
            # Subtle rhythmic cinematic bass pulse
            beat_t = t % (1.0 / pulse_hz)
            pulse = math.exp(-beat_t * 7.5)
            val += 0.22 * pulse * math.sin(two_pi * chord[0] * t)
        elif mood == "happy":
            # Gentle bright plucked melody notes
            step_t = t % 0.45
            note_idx = int(t / 0.45) % 4
            pluck = math.exp(-step_t * 9.0)
            val += 0.16 * pluck * math.sin(two_pi * (chord[1 + (note_idx % 3)] * 2.0) * t)
        elif mood == "sad":
            # Soft slow piano-like arpeggio
            step_t = t % 0.95
            note_idx = int(t / 0.95) % 4
            pluck = math.exp(-step_t * 4.5)
            val += 0.15 * pluck * math.sin(two_pi * (chord[1 + (note_idx % 3)] * 2.0) * t)

        sample = val * c_env * lfo * 0.42

        # Soft filtered pink-noise whoosh SFX on scene transitions
        for w_start, w_end, w_peak in trans_windows:
            if w_start <= i <= w_end:
                white = rng.uniform(-1.0, 1.0)
                lp_noise = 0.86 * lp_noise + 0.14 * white
                dist = abs(i - w_peak) / max(1, (w_end - w_start) * 0.5)
                whoosh_env = max(0.0, 1.0 - dist) ** 2
                sample += lp_noise * whoosh_env * 0.35
                break

        # Global smooth fade-in (1.0s) & fade-out (1.4s)
        if t < 1.0:
            sample *= t
        elif t > total_dur - 1.4:
            sample *= max(0.0, (total_dur - t) / 1.4)

        sample = max(-0.92, min(0.92, sample))
        buf.extend(struct.pack("<h", int(sample * 32767)))

    with wave.open(str(raw_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(bytes(buf))

    # Apply studio warmth (lowpass + gentle spacious echo) and convert to 44100Hz stereo WAV
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(raw_wav),
            "-af", "lowpass=f=2400,aecho=0.8:0.7:60|120:0.25|0.15,aresample=44100",
            "-ac", "2", "-ar", "44100",
            str(out_wav),
        ],
        check=True,
    )


# ==============================================================================
# Step 4: Compact Sleek Subtitles (1–2 Lines, Timed Chunks) + Full-Frame Montage
# ==============================================================================
def find_font_path(has_arabic: bool = True, has_latin: bool = False) -> str:
    if has_arabic and has_latin:
        for c in [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]:
            if os.path.exists(c):
                return c

    if has_arabic:
        try:
            out = subprocess.check_output(["fc-list", ":lang=ar", "file"], text=True, stderr=subprocess.DEVNULL)
            files = [ln.split(":")[0].strip() for ln in out.splitlines() if ":" in ln]
            for pref in ["NotoSansArabic-Bold", "NotoKufiArabic-Bold", "NotoNaskhArabic-Bold", "DejaVuSans-Bold"]:
                for f in files:
                    if pref in f and os.path.exists(f):
                        return f
            for f in files:
                if f.endswith(".ttf") and os.path.exists(f):
                    return f
        except Exception:
            pass

    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf" if has_arabic else "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return ""


def prepare_caption_line(line: str, is_rtl: bool) -> tuple[str, dict]:
    cleaned = re.sub(r"[\U00010000-\U0010ffff\u2600-\u27BF]", "", str(line or "")).strip()
    if is_rtl:
        if HAS_RAQM:
            return cleaned, {"direction": "rtl"}
        return get_display(arabic_reshaper.reshape(cleaned)), {}
    return cleaned, {}


def split_caption_into_chunks(text: str, is_vertical: bool) -> list[str]:
    """Split narration into punchy 2-4 word viral TikTok/Shorts caption beats so text feels alive and dynamic."""
    cleaned = re.sub(r"[\U00010000-\U0010ffff\u2600-\u27BF]", "", str(text or "")).strip()
    words = cleaned.split()
    if not words:
        return []
    chunk_size = 3 if is_vertical else 5
    chunks = [" ".join(words[i:i + chunk_size]) for i in range(0, len(words), chunk_size)]
    if len(chunks) >= 2 and len(chunks[-1].split()) == 1:
        chunks[-2] = chunks[-2] + " " + chunks[-1]
        chunks.pop()
    return chunks[:4]


def render_subtitle_png(text: str, out_png: Path, width: int, height: int, accent_gold: bool = False):
    """Renders bold, crisp viral Shorts/Reels style pop-up captions (thick black outline + drop shadow, zero clunky box)."""
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    raw_clean = re.sub(r"[\U00010000-\U0010ffff\u2600-\u27BF]", "", str(text or "")).strip()
    has_ar = bool(re.search(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]", raw_clean))
    has_lat = bool(re.search(r"[A-Za-z]", raw_clean))

    if has_ar and has_lat:
        ar_chars = len(re.findall(r"[\u0600-\u06FF]", raw_clean))
        lat_chars = len(re.findall(r"[A-Za-z]", raw_clean))
        if ar_chars > lat_chars:
            raw_clean = re.sub(r"\s*[A-Za-z0-9_#\-]+\s*", " ", raw_clean).strip()
            has_lat = False

    font_size = 62 if width <= 1080 else 54
    font_path = find_font_path(has_arabic=has_ar, has_latin=has_lat)
    font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()

    words = raw_clean.split()
    lines = []
    cur = []
    max_chars = 22 if width <= 1080 else 40
    for w in words:
        if sum(len(x) + 1 for x in cur) + len(w) > max_chars and cur:
            lines.append(" ".join(cur))
            cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(" ".join(cur))
    lines = lines[:2]

    prepared = [prepare_caption_line(ln, is_rtl=has_ar) for ln in lines]
    metrics = []
    for txt_ln, kwargs in prepared:
        bbox = draw.textbbox((0, 0), txt_ln, font=font, stroke_width=6, **kwargs)
        metrics.append((bbox[2] - bbox[0], bbox[3] - bbox[1], bbox[0], bbox[1]))

    gap = 12
    total_h = sum(m[1] for m in metrics) + gap * max(0, len(prepared) - 1)
    y = int(height * 0.74) - total_h // 2

    text_fill = (255, 224, 71, 255) if accent_gold else (255, 255, 255, 255)
    for (txt_ln, kwargs), (lw, lh, bx0, by0) in zip(prepared, metrics):
        x = (width - lw) // 2 - bx0
        draw.text((x + 4, y - by0 + 6), txt_ln, font=font, fill=(0, 0, 0, 190), stroke_width=6, stroke_fill=(0, 0, 0, 190), **kwargs)
        draw.text(
            (x, y - by0),
            txt_ln,
            font=font,
            fill=text_fill,
            stroke_width=6,
            stroke_fill=(0, 0, 0, 255),
            **kwargs,
        )
        y += lh + gap

    img.save(str(out_png), "PNG")


def get_ken_burns_expr(scene_idx: int, frames: int, W: int, H: int, fps: int) -> str:
    """Dynamic, lively 16%-20% cinematic camera motions (zoom-in, zoom-out, diagonal pans, upward/downward reveal)."""
    mode = scene_idx % 6
    f_den = max(1, frames)
    if mode == 0:
        z = f"1.0+0.18*on/{f_den}"
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"
    elif mode == 1:
        z = f"1.18-0.18*on/{f_den}"
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"
    elif mode == 2:
        z = f"1.10+0.08*on/{f_den}"
        x = f"(iw-iw/zoom)*on/{f_den}"
        y = f"(ih-ih/zoom)*0.35*on/{f_den}"
    elif mode == 3:
        z = f"1.18-0.08*on/{f_den}"
        x = f"(iw-iw/zoom)*(1-on/{f_den})"
        y = f"(ih-ih/zoom)*0.4"
    elif mode == 4:
        z = f"1.08+0.10*on/{f_den}"
        x = "iw/2-(iw/zoom/2)"
        y = f"(ih-ih/zoom)*(1-on/{f_den})"
    else:
        z = f"1.08+0.10*on/{f_den}"
        x = "iw/2-(iw/zoom/2)"
        y = f"(ih-ih/zoom)*on/{f_den}"

    return (
        f"scale={W*2}:{H*2}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={W*2}:{H*2},"
        f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={W}x{H}:fps={fps},"
        f"eq=contrast=1.06:saturation=1.14:brightness=0.015,"
        f"setsar=1"
    )


def build_1080p_video(
    scenes: list,
    img_paths: list[Path],
    audio_paths: list[Path],
    durations: list[float],
    is_vertical: bool,
    show_subtitles: bool,
    mood: str,
    work_dir: Path,
) -> Path:
    W, H = (1080, 1920) if is_vertical else (1920, 1080)
    fps = 30
    use_xfade = 2 <= len(scenes) <= 24
    trans_dur = 0.35 if use_xfade else 0.0
    segment_files = []
    seg_durations = []

    for i, (scene, media_p, aud_p, dur) in enumerate(zip(scenes, img_paths, audio_paths, durations)):
        seg_out = work_dir / f"seg_{i:04d}.mp4"
        seg_dur = max(3.2, float(dur)) + (trans_dur if (use_xfade and i < len(scenes) - 1) else 0.0)
        frames = max(96, int(math.ceil(seg_dur * fps)))
        is_video_clip = str(media_p).lower().endswith(".mp4")
        if is_video_clip:
            vf_base = (
                f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,"
                f"crop={W}:{H},fps={fps},eq=contrast=1.04:saturation=1.08,setsar=1"
            )
            media_in_args = ["-stream_loop", "-1", "-i", str(media_p)]
        else:
            vf_base = get_ken_burns_expr(i, frames, W, H, fps)
            media_in_args = ["-i", str(media_p)]

        fade_parts = []
        if i == 0:
            fade_parts.append("fade=t=in:st=0:d=0.35")
        if i == len(scenes) - 1:
            fade_parts.append(f"fade=t=out:st={max(0.5, seg_dur - 0.45):.2f}:d=0.45")
        fade_str = ("," + ",".join(fade_parts)) if fade_parts else ""

        chunks = split_caption_into_chunks(scene.get("narration") or "", is_vertical) if show_subtitles else []

        if len(chunks) >= 1:
            sub_inputs = []
            ov_filters = [f"[0:v]{vf_base}[bg]"]
            prev_lbl = "bg"
            step_t = max(0.5, float(dur) / len(chunks))
            for c_idx, ch_txt in enumerate(chunks):
                sub_p = work_dir / f"sub_{i:04d}_{c_idx}.png"
                render_subtitle_png(ch_txt, sub_p, W, H, accent_gold=(c_idx % 2 == 1))
                sub_inputs.extend(["-loop", "1", "-t", f"{seg_dur:.2f}", "-i", str(sub_p)])
                t0 = c_idx * step_t
                t1 = seg_dur if c_idx == len(chunks) - 1 else (c_idx + 1) * step_t
                next_lbl = "v" if c_idx == len(chunks) - 1 else f"v{c_idx}"
                tail_fx = f"{fade_str},format=yuv420p" if c_idx == len(chunks) - 1 else ""
                ov_filters.append(
                    f"[{prev_lbl}][{c_idx + 1}:v]overlay=0:0:eof_action=repeat:enable='between(t,{t0:.2f},{t1:.2f})'{tail_fx}[{next_lbl}]"
                )
                prev_lbl = next_lbl
            aud_idx = len(chunks) + 1
            ov_filters.append(f"[{aud_idx}:a]apad=whole_dur={seg_dur:.2f}[a]")
            cmd = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                *media_in_args,
                *sub_inputs,
                "-i", str(aud_p),
                "-filter_complex", ";".join(ov_filters),
                "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p",
                "-preset", "veryfast", "-crf", "21", "-r", str(fps),
                "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-ar", "44100",
                "-t", f"{seg_dur:.2f}",
                str(seg_out),
            ]
        else:
            cmd = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                *media_in_args,
                "-i", str(aud_p),
                "-filter_complex",
                f"[0:v]{vf_base}{fade_str},format=yuv420p[v];[1:a]apad=whole_dur={seg_dur:.2f}[a]",
                "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p",
                "-preset", "veryfast", "-crf", "21", "-r", str(fps),
                "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-ar", "44100",
                "-t", f"{seg_dur:.2f}",
                str(seg_out),
            ]
        subprocess.run(cmd, check=True)
        segment_files.append(seg_out)
        seg_durations.append(seg_dur)

    # Assemble video + voice track first
    voice_video = work_dir / "assembled_voice.mp4"
    transition_times = []
    if use_xfade:
        transitions = ["zoomin", "smoothleft", "circleopen", "smoothright", "dissolve", "radial"]
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
        for sf in segment_files:
            cmd.extend(["-i", str(sf)])

        v_filters = []
        a_filters = []
        offset = seg_durations[0] - trans_dur
        prev_v = "0:v"
        prev_a = "0:a"
        for idx in range(1, len(segment_files)):
            transition_times.append(max(0.2, offset + trans_dur * 0.5))
            tr = transitions[(idx - 1) % len(transitions)]
            out_v = f"v{idx}"
            out_a = f"a{idx}"
            v_filters.append(f"[{prev_v}][{idx}:v]xfade=transition={tr}:duration={trans_dur:.2f}:offset={max(0.1, offset):.2f}[{out_v}]")
            a_filters.append(f"[{prev_a}][{idx}:a]acrossfade=d={trans_dur:.2f}:c1=tri:c2=tri[{out_a}]")
            prev_v = out_v
            prev_a = out_a
            offset += seg_durations[idx] - trans_dur

        filter_complex = ";".join(v_filters + a_filters) + f";[{prev_v}]format=yuv420p[vout]"
        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[vout]", "-map", f"[{prev_a}]",
            "-c:v", "libx264", "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p",
            "-preset", "veryfast", "-crf", "21", "-r", str(fps),
            "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-ar", "44100",
            str(voice_video),
        ])
        subprocess.run(cmd, check=True)
    else:
        t_acc = 0.0
        for sd in seg_durations[:-1]:
            t_acc += sd
            transition_times.append(t_acc)
        concat_list = work_dir / "concat.txt"
        concat_list.write_text("\n".join(f"file '{p}'" for p in segment_files), encoding="utf-8")
        subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "concat", "-safe", "0", "-i", str(concat_list),
                "-c", "copy",
                str(voice_video),
            ],
            check=True,
        )

    # Mix mood-matched cinematic soundtrack + subtle transition whoosh SFX under voiceover
    final_mp4 = work_dir / "final_1080p.mp4"
    try:
        total_vid_dur = get_audio_duration(voice_video)
        bgm_wav = work_dir / "mood_bgm.wav"
        generate_mood_soundtrack(mood, total_vid_dur, transition_times, bgm_wav)
        subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(voice_video),
                "-i", str(bgm_wav),
                "-filter_complex",
                "[0:a]volume=1.08[v_a];[1:a]volume=0.14[bg_a];[v_a][bg_a]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[aout]",
                "-map", "0:v", "-map", "[aout]",
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", "160k", "-ac", "2", "-ar", "44100",
                "-movflags", "+faststart",
                str(final_mp4),
            ],
            check=True,
        )
        return final_mp4
    except Exception as exc:
        print(f"[WARN] Mood soundtrack mix skipped, using clean voice track: {exc}", flush=True)
        subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(voice_video), "-c", "copy", "-movflags", "+faststart", str(final_mp4),
            ],
            check=True,
        )
        return final_mp4


# ==============================================================================
# Step 5: Supabase Storage MP4 Upload + YouTube OAuth 2.0 Resumable Upload
# ==============================================================================
def upload_mp4_to_storage(mp4_path: Path, job_id: str) -> str:
    """Upload rendered 1080p MP4 to Supabase Storage public bucket (videos) for direct client download."""
    try:
        requests.post(
            f"{SUPABASE_URL}/storage/v1/bucket",
            headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"},
            json={"id": "videos", "name": "videos", "public": True},
            timeout=15,
        )
        obj_path = f"{job_id}.mp4"
        with open(mp4_path, "rb") as fh:
            up = requests.post(
                f"{SUPABASE_URL}/storage/v1/object/videos/{obj_path}",
                headers={
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "Content-Type": "video/mp4",
                    "x-upsert": "true",
                },
                data=fh,
                timeout=300,
            )
        if up.ok:
            return f"{SUPABASE_URL}/storage/v1/object/public/videos/{obj_path}"
    except Exception as exc:
        print(f"[WARN] Storage MP4 upload skipped: {exc}", flush=True)
    return ""


def refresh_youtube_access_token(refresh_token: str) -> str:
    r = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    data = r.json()
    if not r.ok or not data.get("access_token"):
        raise RuntimeError(f"YouTube OAuth refresh failed: {data.get('error_description') or data}")
    return data["access_token"]


def upload_to_youtube(mp4_path: Path, access_token: str, title: str, description: str, tags: list) -> str:
    file_size = mp4_path.stat().st_size
    init_resp = requests.post(
        "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(file_size),
            "X-Upload-Content-Type": "video/mp4",
        },
        json={
            "snippet": {
                "title": title[:95],
                "description": description[:4500],
                "tags": [str(t)[:30] for t in (tags or [])][:10],
                "categoryId": "24",
            },
            "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
        },
        timeout=45,
    )
    if not init_resp.ok or not init_resp.headers.get("Location"):
        raise RuntimeError(f"YouTube upload init failed ({init_resp.status_code}): {init_resp.text[:300]}")

    upload_url = init_resp.headers["Location"]
    with open(mp4_path, "rb") as fh:
        up_resp = requests.put(
            upload_url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "video/mp4",
                "Content-Length": str(file_size),
            },
            data=fh,
            timeout=600,
        )
    if not up_resp.ok:
        raise RuntimeError(f"YouTube video upload failed ({up_resp.status_code}): {up_resp.text[:300]}")
    vid_id = up_resp.json().get("id")
    if not vid_id:
        raise RuntimeError("YouTube did not return a video ID")
    return vid_id


# ==============================================================================
# Main Pipeline
# ==============================================================================
def main():
    if not JOB_ID:
        raise RuntimeError("Missing JOB_ID environment variable")
    if not RUNWARE_API_KEY:
        raise RuntimeError("Missing RUNWARE_API_KEY secret in GitHub Actions")
    if not SUPABASE_KEY:
        raise RuntimeError("Missing SUPABASE_SERVICE_ROLE_KEY secret in GitHub Actions")

    job = get_job()
    channel = get_channel(job["user_email"], int(job.get("slot_number") or 1))
    refresh_token = channel.get("youtube_refresh_token") or ""
    if not refresh_token:
        raise RuntimeError("القناة غير مربوطة بيوتيوب (لا يوجد Refresh Token)")

    niche = job.get("niche") or "Stories"
    style = job.get("visual_style") or "3D Pixar & Disney Animation"
    language = job.get("video_language") or "العربية (مصر)"
    voice_locale = job.get("voice_locale") or "ar-EG"
    voice_gender = job.get("voice_gender") or "male"
    duration_sec = int(job.get("duration_sec") or 30)
    is_vertical = "16:9" not in str(job.get("orientation") or "")
    show_subtitles = bool(job.get("show_subtitles", True))
    motion_mode = str(job.get("motion_mode") or channel.get("motion_mode") or "cinematic_1080p").strip().lower()
    is_ai_motion = motion_mode == "ai_motion"
    if is_ai_motion:
        duration_sec = max(5, min(30, duration_sec))
    scene_count = 2 if is_ai_motion else compute_scene_count(duration_sec)

    update_job({
        "status": "scripting",
        "progress_pct": 12,
        "scene_count": scene_count,
        "step_label": f"جاري كتابة القصة والسيناريو ({scene_count} مشهد)...",
    })

    story = generate_story_package(niche, style, language, voice_locale, duration_sec, scene_count, is_vertical)
    job["video_title"] = story["title"]
    mood = story.get("mood") or detect_story_mood(niche, story["title"])

    update_job({
        "status": "imaging",
        "progress_pct": 20,
        "video_title": story["title"],
        "video_desc": story["description"],
        "step_label": f"جاري رسم المشاهد بالتوازي ({scene_count} مشهد 1080p)...",
    })

    with tempfile.TemporaryDirectory() as tmp:
        work_dir = Path(tmp)

        ai_motion_succeeded = False
        if is_ai_motion:
            final_mp4 = work_dir / "heygen_native_audio.mp4"
            try:
                generate_heygen_video_clip(
                    niche=niche,
                    style=style,
                    language=language,
                    voice_locale=voice_locale,
                    duration_sec=duration_sec,
                    is_vertical=is_vertical,
                    story=story,
                    out_mp4=final_mp4,
                )
                ai_motion_succeeded = True
            except Exception as ai_err:
                print(f"[WARN] AI Motion unavailable ({ai_err}) — auto-falling back to 1080p Cinematic Studio so scheduled publish succeeds!", flush=True)
                story = generate_story_package(niche, style, language, voice_locale, duration_sec, compute_scene_count(duration_sec), is_vertical)
                mood = story.get("mood") or detect_story_mood(niche, story["title"])

        if not ai_motion_succeeded:
            img_paths, _ = generate_all_scenes(story["scenes"], style, is_vertical, work_dir, niche=niche)

            update_job({
                "status": "voicing",
                "progress_pct": 62,
                "step_label": f"جاري تسجيل التعليق الصوتي والمؤثرات ({language})...",
            })
            voice_name = pick_voice(voice_locale, voice_gender)
            audio_paths = []
            durations = []
            for idx, sc in enumerate(story["scenes"]):
                mp3_p = work_dir / f"aud_{idx:04d}.mp3"
                asyncio.run(synth_scene_audio(sc["narration"], voice_name, mp3_p))
                audio_paths.append(mp3_p)
                min_per_scene = max(3.5, duration_sec / max(1, len(story["scenes"])))
                durations.append(max(min_per_scene, get_audio_duration(mp3_p) + 0.3))

            update_job({
                "status": "rendering",
                "progress_pct": 76,
                "step_label": "جاري مونتاج الفيديو السينمائي 1080p مع الموسيقى والمؤثرات...",
            })
            final_mp4 = build_1080p_video(
                story["scenes"], img_paths, audio_paths, durations, is_vertical, show_subtitles, mood, work_dir
            )

        update_job({
            "status": "uploading",
            "progress_pct": 90,
            "step_label": "جاري رفع الفيديو 1080p على قناتك في يوتيوب...",
        })
        download_url = upload_mp4_to_storage(final_mp4, JOB_ID)
        access_token = refresh_youtube_access_token(refresh_token)
        vid_id = upload_to_youtube(final_mp4, access_token, story["title"], story["description"], story["tags"])
        yt_url = f"https://www.youtube.com/watch?v={vid_id}"

        deduct_user_minutes_and_log(job, vid_id, yt_url)
        update_job({
            "status": "completed",
            "progress_pct": 100,
            "step_label": "تم التوليد والنشر بنجاح على يوتيوب بدقة 1080p ✓",
            "youtube_video_id": vid_id,
            "youtube_url": yt_url,
            "download_url": download_url,
            "error_message": "",
        })
        print(f"[SUCCESS] Published 1080p video: {yt_url}", flush=True)


def sanitize_customer_error(err_text: str) -> str:
    raw = str(err_text or "")
    low = raw.lower()
    if "غير مربوطة" in raw or "refresh token" in low:
        return "القناة غير مربوطة بيوتيوب — يرجى إعادة ربط القناة من صفحة القنوات."
    if "youtube" in low and ("upload" in low or "quota" in low or "oauth" in low):
        return "تعذّر رفع الفيديو على يوتيوب مؤقتاً — يرجى التأكد من ربط القناة والمحاولة مرة أخرى (لم يتم خصم أي رصيد)."
    return "الخدمة السحابية مشغولة مؤقتاً — لم يتم خصم أي رصيد من حسابك، يرجى المحاولة مرة أخرى بعد قليل."


if __name__ == "__main__":
    try:
        main()
    except Exception as err:
        print(f"[ERROR] {err}", file=sys.stderr, flush=True)
        update_job({
            "status": "failed",
            "progress_pct": 100,
            "step_label": "تعذّر إكمال التوليد — لم يتم خصم أي رصيد",
            "error_message": sanitize_customer_error(str(err)),
        })
        sys.exit(1)
