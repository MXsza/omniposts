#!/usr/bin/env python3
"""
Omniposts.online — 24/7 1080p Cloud Video Worker (Studio Edition)
Pipeline:
  1. Load job & YouTube channel credentials from Supabase (render_jobs + channels)
  2. Generate a real, gripping localized story script + scene prompts + viral title/description
     via Runware Chat Completions (with rich dialect-matched fallback stories)
  3. Generate N scene images in parallel via Runware imageInference (runware:100@1 FLUX.1 schnell)
     and push live preview image URLs to Supabase render_jobs
  4. Synthesize natural voiceover in any world language/dialect (Male/Female) via Edge TTS
  5. Assemble Full HD 1080p MP4 with varied Ken Burns camera motion, smooth xfade transitions,
     cinematic color grading, and crystal-clear RTL/multilingual subtitles via FFmpeg
  6. Upload MP4 to Supabase Storage (for instant download), upload to YouTube via OAuth 2.0,
     deduct exact minutes ONLY on success, and update render_jobs + publish_logs.
"""

import asyncio
import datetime
import json
import math
import os
import random
import re
import subprocess
import sys
import tempfile
import uuid
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
# Step 1: Real Viral Story Script & Scene Prompt Generator
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


def build_rich_fallback_story(niche: str, style: str, language: str, voice_locale: str, scene_count: int, short_tag: str) -> dict:
    """Rich, genuine storytelling fallback bank (100% localized, zero dummy lines or English leaks in Arabic)."""
    is_ar = is_arabic_language(language, voice_locale)
    is_eg = ("مصر" in str(language or "")) or str(voice_locale or "").lower() == "ar-eg"
    nl = str(niche or "").lower()

    if is_ar:
        ar_stories = {
            "islamic": [
                {
                    "title": "سر التاجر الفقير الذي أبكى الخليفة في منتصف الليل!",
                    "desc": "قصة تاريخية مؤثرة عن الأمانة والفرج بعد الشدة. شاهد النهاية التي غيرت حياة رجل كامل في ليلة واحدة!\n\n#قصص #حكم #قصص_تاريخية #عبرة",
                    "tags": ["قصص", "حكم", "قصص تاريخية", "عبرة"],
                    "beats": [
                        ("في ليلة شتوية قاسية، وقف تاجر فقير أمام باب المسجد وهو يحمل آخر رغيف خبز في بيته.", "Ancient Islamic market street at night, glowing lanterns, humble poor merchant holding bread, cinematic lighting"),
                        ("وفجأة، مر أمامه غريب يرتجف من البرد والجوع، فآثره بالرغيف الوحيد دون تردد.", "Merchant kindly giving warm bread to a shivering traveler under a stone archway, warm golden lantern light"),
                        ("في الصباح، طرق جنود الخليفة باب التاجر، وظن أن مصيبة كبرى قد حلت به.", "Royal guards knocking on a modest wooden door at dawn in an ancient Arabian city, dramatic sunrise shadows"),
                        ("لكن المفاجأة أن الغريب كان الخليفة نفسه، وكافأه بمتجر كبير لأن قلبه كان أغنى من الكنوز!", "Grand palace courtyard, grateful merchant receiving a royal scroll from the Caliph, golden sunbeams, inspiring mood"),
                    ],
                },
                {
                    "title": "الحكيم الذي أجاب بثلاث كلمات فقط فأذهل الملك!",
                    "desc": "حكمة خالدة من التراث العربي تعلمنا كيف نحول أصعب اللحظات إلى أعظم انتصار. اشترك للمزيد من القصص يومياً!\n\n#قصص #حكمة #تاريخ #تطوير_الذات",
                    "tags": ["قصص", "حكمة", "تراث", "تطوير الذات"],
                    "beats": [
                        ("جمع الملك أعظم حكماء مملكته وسألهم عن جملة واحدة تفرح الحزين وتُهدئ المغرور.", "Grand ancient throne room with towering marble pillars, king addressing wise scholars, dramatic shafts of light"),
                        ("سكت الجميع ساعات طويلة، حتى تقدم شيخ بسيط وكتب ثلاث كلمات على خاتم ذهبي.", "Elderly wise man engraving delicate Arabic calligraphy onto a glowing golden ring, close-up cinematic shot"),
                        ("عندما قرأ الملك الكلمات، سالت دموعه وأمر بتعليق الخاتم في قصره للأبد.", "King looking down at the golden ring in awe, emotional expression, warm royal candlelight"),
                        ("كانت الكلمات هي: هذا الوقت سيمضي... فلا تحزن على شدة، ولا تغتر بنعمة!", "Golden ring resting on velvet beside an hourglass with flowing sand, epic sunset glow through palace window"),
                    ],
                },
            ],
            "mystery": [
                {
                    "title": "سر الغرفة المغلقة التي لم يجرؤ أحد على فتحها منذ خمسين عاماً!",
                    "desc": "لغز غامض ومثير يخطف الأنفاس من اللحظة الأولى. ماذا وجد الشاب خلف الباب الحديدي القديم؟\n\n#قصص_غامضة #تشويق #ألغاز #حكايات",
                    "tags": ["قصص غامضة", "تشويق", "ألغاز", "حكايات"],
                    "beats": [
                        ("في بيت جده القديم، وجد شاب مفتاحاً نحاسياً مخبأ خلف ساعة حائط توقفت منذ خمسين عاماً." if not is_eg else "في بيت جده القديم، لقى شاب مفتاح نحاس مستخبي ورا ساعة حائط واقفة من خمسين سنة.", "Mysterious dimly lit antique hallway, young man discovering a dusty brass key behind an old stopped pendulum clock"),
                        ("مشى نحو الباب الحديدي في آخر الممر، وكان صوت خطواته هو الشيء الوحيد في الظلام." if not is_eg else "مشي ناحية الباب الحديد في آخر الممر، وقلبه بيدق بسرعة مع كل خطوة في الضلمة.", "Heavy rusty iron door at the end of a foggy dark corridor, flashlight beam cutting through dust"),
                        ("أول ما فتح الباب، لقى رسالة مكتوبة بخط جده بتقول: اللي هتلاقيه جوه هيغير مستقبلك للأبد." if is_eg else "عندما فتح الباب، وجد رسالة قديمة تقول: ما ستجده هنا سيغير حياتك إلى الأبد.", "Inside a secret hidden study filled with glowing old maps and an open handwritten letter on a wooden desk"),
                        ("كانت خريطة كنز عائلي قديم، لكن الكنز الحقيقي كان أسرار وتجارب جده اللي صنعت منه أسطورة!" if is_eg else "كانت خريطة لمشروع عمره، تركها له جده ليبدأ من حيث انتهى ويصنع مجداً جديداً!", "Dramatic glowing treasure chest and leather journals illuminated by moonlight through a tall window"),
                    ],
                },
            ],
            "space": [
                {
                    "title": "ماذا سيحدث لو اختفت الشمس لثماني دقائق فقط؟ الحقيقة صادمة!",
                    "desc": "رحلة سريعة ومذهلة في أسرار الفضاء والكون! اكتشف ماذا يحدث للأرض في اللحظة التي تنطفئ فيها الشمس.\n\n#فضاء #علوم #معلومات #الكون",
                    "tags": ["فضاء", "علوم", "معلومات", "الكون"],
                    "beats": [
                        ("تخيل لو الشمس اختفت فجأة في اللحظة دي... الغريب إننا مش هنحس بأي حاجة لمدة تمن دقايق كاملة!" if is_eg else "تخيل لو اختفت الشمس فجأة... الغريب أننا لن نشعر بأي شيء لمدة ثماني دقائق كاملة!", "Epic cinematic view of the Sun vanishing into darkness in deep space while Earth still glows brightly"),
                        ("السبب إن الضوء والجاذبية بياخدوا تمن دقايق عشان يوصلوا من الشمس لكوكب الأرض." if is_eg else "السبب أن الضوء والجاذبية يحتاجان ثماني دقائق كاملة للوصول من الشمس إلى الأرض.", "Glowing golden beam of light traveling across the dark cosmos from the Sun toward planet Earth"),
                        ("وبعد الدقيقة التامنة، السما هتتحول لضلمة كاحلة والنجوم هتظهر في عز الضهر!" if is_eg else "وبعد الدقيقة الثامنة، تتحول السماء إلى ظلام دامس وتظهر النجوم في وضح النهار!", "City skyline suddenly plunging into starry midnight darkness while street lights flicker on"),
                        ("وخلال أيام قليلة هتتجمد المحيطات، ووقتها بس هنعرف قد إيه الشمس أعظم معجزة في الكون!" if is_eg else "وخلال أيام ستتجمد المحيطات، لندرك أن الشمس هي أعظم معجزة تحفظ الحياة في الكون!", "Frozen glowing Earth drifting through a majestic purple nebula in space, ultra-detailed 8K"),
                    ],
                },
            ],
            "success": [
                {
                    "title": "القاعدة السرية التي حولت شاباً مفلساً إلى مليونير في ثلاث سنوات!",
                    "desc": "قصة ملهمة عن الانضباط والذكاء المالي ستغير طريقة تفكيرك في النجاح والثروة للأبد.\n\n#نجاح #تطوير_الذات #ثروة #تحفيز",
                    "tags": ["نجاح", "ثروة", "تطوير الذات", "تحفيز"],
                    "beats": [
                        ("في سن الخامسة والعشرين، كان حسابه البنكي صفر، وكل الناس حواليه قالوله استسلم." if is_eg else "في سن الخامسة والعشرين، كان رصيده صفراً، ونصحه الجميع بالاستسلام.", "Young determined entrepreneur sitting at a modest desk late at night with a single warm lamp, city rain outside"),
                        ("بدل ما يشتكي، قرر يطبق قاعدة بسيطة: ساعة كل يوم يتعلم فيها مهارة واحدة مطلوبة في العالم." if is_eg else "لكنه قرر تطبيق قاعدة واحدة: ساعة يومياً لإتقان مهارة عالية القيمة دون انقطاع.", "Close-up of focused hands writing strategic plans in a leather notebook beside a glowing laptop"),
                        ("بعد سنة واحدة، المهارة دي فتحتله أبواب ما كانش يحلم بيها، وبدأ أول مشروع خاص بيه." if is_eg else "بعد عام واحد فقط، فتحت له تلك المهارة أبواباً لم يحلم بها وأطلق مشروعه الأول.", "Modern luxury glass office overlooking a golden city skyline at sunrise, confident silhouette"),
                        ("الدرس الأهم: النجاح مش ضربة حظ... النجاح هو قرار صغير بتلتزم بيه كل يوم!" if is_eg else "الدرس الأهم: النجاح ليس ضربة حظ، بل قرار صغير تلتزم به كل يوم حتى يصنع الفارق!", "Cinematic wide shot of a person standing atop a mountain peak at golden hour sunrise, inspiring atmosphere"),
                    ],
                },
            ],
            "default": [
                {
                    "title": "القصة التي أذهلت الملايين... شاهد النهاية غير المتوقعة!",
                    "desc": "حكاية مشوقة ومليئة بالمفاجآت تأخذك في رحلة لا تُنسى من أول ثانية حتى اللحظة الأخيرة.\n\n#قصص #حكايات #تشويق #عبرة",
                    "tags": ["قصص", "حكايات", "تشويق", "مفاجأة"],
                    "beats": [
                        ("في يوم عادي جداً، حصل موقف صغير ما حدش كان يتوقع إنه هيقلب الموازين كلها!" if is_eg else "في يوم عادي تماماً، حدث موقف صغير لم يتوقع أحد أنه سيقلب الموازين كلها!", "Cinematic golden hour street with a dramatic lone figure noticing a mysterious glowing object"),
                        ("الكل كان فاكر إن الحكاية خلصت هنا، لكن الحقيقة كانت لسه بتبدأ من اللحظة دي." if is_eg else "ظن الجميع أن القصة انتهت هنا، لكن الحقيقة المذهلة كانت تبدأ في تلك اللحظة بالذات.", "Dramatic close-up shot with moody blue and gold lighting, intense sense of discovery and wonder"),
                        ("ومع كل خطوة، كانت التفاصيل بتتكشف بشكل يخلّي العقل يقف مش مصدق اللي بيحصل." if is_eg else "ومع كل خطوة، تتكشف تفاصيل مدهشة تجعل العقل عاجزاً عن تصديق ما يراه.", "Epic wide cinematic scene of a breathtaking hidden landscape illuminated by dramatic sunrays"),
                        ("وفي النهاية، اللي صبر وكمل الطريق للنهاية هو الوحيد اللي عرف السر الحقيقي!" if is_eg else "وفي النهاية، وحده من امتلك الشجاعة لإكمال الطريق عرف السر الحقيقي وراء كل شيء!", "Triumphant cinematic finale under a majestic starlit sky with warm glowing horizon"),
                    ],
                },
            ],
        }

        if any(k in nl for k in ["islam", "wisdom", "history", "ancient", "تاريخ", "إسلام", "حكم"]):
            bucket = ar_stories["islamic"]
        elif any(k in nl for k in ["mystery", "suspense", "night", "horror", "غموض", "رعب", "تشويق"]):
            bucket = ar_stories["mystery"]
        elif any(k in nl for k in ["space", "cosmic", "science", "ocean", "فضاء", "علم"]):
            bucket = ar_stories["space"]
        elif any(k in nl for k in ["success", "wealth", "stoic", "book", "نجاح", "ثروة", "مال"]):
            bucket = ar_stories["success"]
        else:
            bucket = ar_stories["default"]

        picked = random.choice(bucket)
        beats = picked["beats"]
        scenes = []
        for idx in range(scene_count):
            nar, img_p = beats[idx % len(beats)]
            scenes.append({
                "narration": nar,
                "image_prompt": f"{style}, {img_p}, ultra detailed 8K, dramatic cinematic lighting, no text, no watermark",
            })
        title = picked["title"]
        if short_tag and "#shorts" not in title.lower():
            title = f"{title}{short_tag}"[:95]
        return {
            "title": title,
            "description": picked["desc"],
            "tags": picked["tags"],
            "scenes": scenes,
        }

    # English fallback
    en_beats = [
        ("On an ordinary evening, a quiet discovery changed everything nobody thought was possible.", "Dramatic golden hour street, lone figure discovering a mysterious glowing artifact, cinematic 8K"),
        ("Everyone assumed the story ended right there—until one hidden clue rewrote the entire truth.", "Moody cinematic close-up with rich shadows and amber light, intense sense of mystery and wonder"),
        ("Step by step, a breathtaking secret unfolded that defied every expectation.", "Breathtaking hidden monumental chamber illuminated by dramatic shafts of sunlight, ultra detailed"),
        ("In the end, only the one who dared to keep going uncovered the real secret.", "Triumphant cinematic silhouette against a glowing sunrise horizon, epic film look"),
    ]
    scenes = []
    for idx in range(scene_count):
        nar, img_p = en_beats[idx % len(en_beats)]
        scenes.append({
            "narration": nar,
            "image_prompt": f"{style}, {img_p}, no text, no watermark",
        })
    title = f"The Untold Secret That Changed Everything{short_tag}"[:95]
    desc = f"A gripping short story you won't forget. Subscribe for new cinematic stories every day!{short_tag} #Storytime #Viral"
    return {"title": title, "description": desc, "tags": ["Storytime", "Viral", "Shorts"], "scenes": scenes}


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

    lang_rules = (
        f"CRITICAL LANGUAGE RULE: Write 'title', 'description', 'tags', and EVERY scene's 'narration' "
        f"100% in natural, authentic '{language}' (locale: {voice_locale}). "
        + (
            "ZERO English/Latin words allowed in title, description, or narration (except optional #Shorts at the end of description). "
            "Write a REAL, captivating story with a hook, dramatic plot, and surprising ending — NEVER say 'في المشهد رقم 1' or repeat sentences! "
            "The title MUST be a catchy Arabic viral story title about THIS specific story (NEVER copy the English niche name!)."
            if is_ar
            else "Write a REAL, gripping story with a strong hook, escalating plot, and memorable ending — NEVER write generic filler or repeat sentences! "
                 "The title MUST be a catchy viral story title about THIS specific story (not just the raw niche name)."
        )
    )

    system_prompt = (
        "You are an elite viral YouTube scriptwriter and cinematic director. "
        "Return ONLY valid JSON with no markdown fences and no extra commentary. "
        "NEVER mention any AI tool, website name, or 'Generated automatically' anywhere. "
        + lang_rules
    )
    user_prompt = (
        f"Create an original, gripping story inspired by the theme: '{niche}'.\n"
        f"Visual style: '{style}'.\n"
        f"Language & Dialect: '{language}' ({voice_locale}).\n"
        f"Target duration: {duration_sec} seconds (~{approx_words} words total across all scenes).\n"
        f"Divide the story into EXACTLY {scene_count} sequential scenes that flow smoothly as ONE continuous story.\n"
        f"Keep each scene's narration concise (8 to 16 words per scene for short videos) so subtitles look crisp and punchy.\n"
        "Return strict JSON matching this exact schema:\n"
        "{\n"
        '  "title": "Catchy viral YouTube title strictly in the requested language (max 82 chars)",\n'
        '  "description": "Engaging YouTube description strictly in the requested language with 4 relevant hashtags",\n'
        '  "tags": ["tag1", "tag2", "tag3", "tag4"],\n'
        '  "scenes": [\n'
        '    {"narration": "Spoken story line strictly in the requested language/dialect", "image_prompt": "Rich detailed English visual prompt matching the style, cinematic lighting, no text in image"}\n'
        "  ]\n"
        "}"
    )

    # Verified active Runware OpenAI-compatible models
    llm_models = [
        "minimax:m3@0",
        "anthropic:claude@haiku-5.5",
        "alibaba:qwen@4-max",
        "openai:gpt@6-luna",
        "openai:gpt@6.2-sol",
    ]
    for model_id in llm_models:
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
                timeout=60,
            )
            if not resp.ok:
                print(f"[WARN] Runware LLM {model_id} HTTP {resp.status_code}: {resp.text[:220]}", flush=True)
                continue
            data = resp.json()
            raw = data["choices"][0]["message"]["content"].strip()
            parsed = extract_json_object(raw)
            scenes = parsed.get("scenes") or []
            if len(scenes) >= 2:
                # Pad or trim cleanly
                while len(scenes) < scene_count:
                    scenes.append(scenes[-1])
                scenes = scenes[:scene_count]
                title = str(parsed.get("title") or "").strip()[:90]
                desc = str(parsed.get("description") or title).strip()
                # Guard against English title leak when Arabic was requested
                if is_ar and not re.search(r"[\u0600-\u06FF]", title):
                    print(f"[WARN] LLM {model_id} returned non-Arabic title, trying next model...", flush=True)
                    continue
                if short_tag and "#shorts" not in title.lower():
                    title = f"{title}{short_tag}"[:95]
                print(f"[OK] Generated story via Runware LLM ({model_id}): {title}", flush=True)
                return {
                    "title": title,
                    "description": desc,
                    "tags": parsed.get("tags") or (["قصص", "حكايات", "شورتس"] if is_ar else ["Storytime", "Shorts"]),
                    "scenes": scenes,
                }
        except Exception as exc:
            print(f"[WARN] Runware LLM {model_id} error: {exc}", flush=True)

    print("[INFO] Using rich localized story fallback bank.", flush=True)
    return build_rich_fallback_story(niche, style, language, voice_locale, scene_count, short_tag)


# ==============================================================================
# Step 2: Parallel Scene Image Generation (Runware FLUX.1 schnell)
# ==============================================================================
def generate_single_image(prompt: str, width: int, height: int, out_path: Path) -> str:
    payload = [
        {
            "taskType": "imageInference",
            "taskUUID": str(uuid.uuid4()),
            "model": "runware:100@1",
            "positivePrompt": prompt[:900],
            "width": width,
            "height": height,
            "steps": 4,
            "numberResults": 1,
            "outputType": "URL",
            "outputFormat": "JPEG",
            "includeCost": True,
        }
    ]
    for attempt in range(3):
        try:
            r = requests.post(
                "https://api.runware.ai/v1",
                headers={
                    "Authorization": f"Bearer {RUNWARE_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=45,
            )
            r.raise_for_status()
            data = r.json().get("data") or []
            if data and data[0].get("imageURL"):
                img_url = data[0]["imageURL"]
                img_bytes = requests.get(img_url, timeout=30).content
                out_path.write_bytes(img_bytes)
                return img_url
        except Exception as exc:
            print(f"[WARN] Image attempt {attempt+1} failed: {exc}", flush=True)
    raise RuntimeError("Runware image generation failed after 3 retries")


def generate_all_scenes(scenes: list, style: str, is_vertical: bool, work_dir: Path) -> tuple[list[Path], list[str]]:
    w, h = (768, 1344) if is_vertical else (1344, 768)
    total = len(scenes)
    paths: list[Path | None] = [None] * total
    urls: list[str] = []

    def _worker(i: int):
        p = work_dir / f"scene_{i:04d}.jpg"
        prompt = f"{style}, {scenes[i]['image_prompt']}, cinematic 8K lighting, vivid composition, no text, no watermark"
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


async def synth_scene_audio(text: str, voice: str, out_mp3: Path):
    comm = edge_tts.Communicate(text=text, voice=voice, rate="+5%")
    await comm.save(str(out_mp3))


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
# Step 4: Crystal-Clear RTL/Multilingual Subtitles + Pro 1080p FFmpeg Montage
# ==============================================================================
def find_font_path(has_arabic: bool = True, has_latin: bool = False) -> str:
    # If text mixes Arabic + Latin, DejaVuSans-Bold has BOTH Arabic and Latin glyphs (no □□□ boxes!)
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
    """
    CRITICAL FIX:
    - When Pillow is built with libraqm (Ubuntu / GitHub Actions), Pillow natively shapes & reorders RTL.
      Passing arabic_reshaper + get_display into libraqm DOUBLE-REVERSES Arabic!
      So when HAS_RAQM is True, pass raw logical Unicode text with direction='rtl'.
    - When HAS_RAQM is False, apply arabic_reshaper + get_display and omit direction='rtl'.
    """
    cleaned = re.sub(r"[\U00010000-\U0010ffff\u2600-\u27BF]", "", str(line or "")).strip()
    if is_rtl:
        if HAS_RAQM:
            return cleaned, {"direction": "rtl"}
        return get_display(arabic_reshaper.reshape(cleaned)), {}
    return cleaned, {}


def render_subtitle_png(text: str, out_png: Path, width: int, height: int):
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    raw_clean = re.sub(r"[\U00010000-\U0010ffff\u2600-\u27BF]", "", str(text or "")).strip()
    has_ar = bool(re.search(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]", raw_clean))
    has_lat = bool(re.search(r"[A-Za-z]", raw_clean))

    # Strip stray Latin words if the caption is predominantly Arabic so NotoSansArabic never shows □□□
    if has_ar and has_lat:
        ar_chars = len(re.findall(r"[\u0600-\u06FF]", raw_clean))
        lat_chars = len(re.findall(r"[A-Za-z]", raw_clean))
        if ar_chars > lat_chars:
            raw_clean = re.sub(r"\s*[A-Za-z0-9_#\-]+\s*", " ", raw_clean).strip()
            has_lat = False

    font_size = 56 if width <= 1080 else 48
    font_path = find_font_path(has_arabic=has_ar, has_latin=has_lat)
    font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()

    words = raw_clean.split()
    lines = []
    cur = []
    max_chars = 24 if width <= 1080 else 44
    for w in words:
        if sum(len(x) + 1 for x in cur) + len(w) > max_chars and cur:
            lines.append(" ".join(cur))
            cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(" ".join(cur))
    lines = lines[:3]

    prepared = [prepare_caption_line(ln, is_rtl=has_ar) for ln in lines]
    metrics = []
    for txt_ln, kwargs in prepared:
        bbox = draw.textbbox((0, 0), txt_ln, font=font, stroke_width=3, **kwargs)
        metrics.append((bbox[2] - bbox[0], bbox[3] - bbox[1], bbox[0], bbox[1]))

    pad_x, pad_y = 34, 22
    gap = 16
    max_lw = max((m[0] for m in metrics), default=200)
    box_w = min(width - 70, max_lw + pad_x * 2)
    box_h = sum(m[1] for m in metrics) + gap * max(0, len(prepared) - 1) + pad_y * 2
    box_x = (width - box_w) // 2
    box_y = int(height * 0.77) - box_h // 2

    # Modern dark cinema subtitle pill
    draw.rounded_rectangle(
        [box_x, box_y, box_x + box_w, box_y + box_h],
        radius=26,
        fill=(6, 10, 22, 205),
        outline=(250, 204, 21, 185),
        width=3,
    )

    y = box_y + pad_y
    for (txt_ln, kwargs), (lw, lh, bx0, by0) in zip(prepared, metrics):
        x = (width - lw) // 2 - bx0
        draw.text(
            (x, y - by0),
            txt_ln,
            font=font,
            fill=(255, 255, 255, 255),
            stroke_width=3,
            stroke_fill=(0, 0, 0, 245),
            **kwargs,
        )
        y += lh + gap

    img.save(str(out_png), "PNG")


def get_ken_burns_expr(scene_idx: int, frames: int, W: int, H: int, fps: int) -> str:
    """Varied smooth cinematic camera motions: Zoom-In, Zoom-Out, Pan-Right, Pan-Left."""
    mode = scene_idx % 4
    if mode == 0:
        # Smooth slow zoom-in centered
        z = "min(1.0+0.0009*on,1.15)"
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"
    elif mode == 1:
        # Smooth slow zoom-out centered
        z = "max(1.15-0.0009*on,1.0)"
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"
    elif mode == 2:
        # Cinematic pan left-to-right with gentle zoom
        z = "1.12"
        x = f"(iw-iw/zoom)*on/{max(1, frames)}"
        y = "ih/2-(ih/zoom/2)"
    else:
        # Cinematic pan right-to-left with gentle zoom
        z = "1.12"
        x = f"(iw-iw/zoom)*(1-on/{max(1, frames)})"
        y = "ih/2-(ih/zoom/2)"

    return (
        f"scale={W*2}:{H*2}:force_original_aspect_ratio=increase,"
        f"crop={W*2}:{H*2},"
        f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={W}x{H}:fps={fps},"
        f"eq=contrast=1.06:saturation=1.14:brightness=0.01,"
        f"vignette=PI/6,"
        f"setsar=1"
    )


def build_1080p_video(
    scenes: list,
    img_paths: list[Path],
    audio_paths: list[Path],
    durations: list[float],
    is_vertical: bool,
    show_subtitles: bool,
    work_dir: Path,
) -> Path:
    W, H = (1080, 1920) if is_vertical else (1920, 1080)
    fps = 30
    use_xfade = 2 <= len(scenes) <= 24
    trans_dur = 0.45 if use_xfade else 0.0
    segment_files = []
    seg_durations = []

    for i, (scene, img_p, aud_p, dur) in enumerate(zip(scenes, img_paths, audio_paths, durations)):
        seg_out = work_dir / f"seg_{i:04d}.mp4"
        # Add small tail buffer for crossfade overlap on all scenes except last
        seg_dur = max(3.2, float(dur)) + (trans_dur if (use_xfade and i < len(scenes) - 1) else 0.0)
        frames = max(96, int(math.ceil(seg_dur * fps)))
        vf_base = get_ken_burns_expr(i, frames, W, H, fps)

        # Gentle fade-in on first scene, fade-out on last scene
        fade_parts = []
        if i == 0:
            fade_parts.append("fade=t=in:st=0:d=0.35")
        if i == len(scenes) - 1:
            fade_parts.append(f"fade=t=out:st={max(0.5, seg_dur - 0.45):.2f}:d=0.45")
        fade_str = ("," + ",".join(fade_parts)) if fade_parts else ""

        if show_subtitles and scene.get("narration"):
            sub_png = work_dir / f"sub_{i:04d}.png"
            render_subtitle_png(scene["narration"], sub_png, W, H)
            cmd = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(img_p),
                "-loop", "1", "-t", f"{seg_dur:.2f}", "-i", str(sub_png),
                "-i", str(aud_p),
                "-filter_complex",
                f"[0:v]{vf_base}[bg];[bg][1:v]overlay=0:0:eof_action=repeat{fade_str},format=yuv420p[v];"
                f"[2:a]apad=whole_dur={seg_dur:.2f}[a]",
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
                "-i", str(img_p),
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

    final_mp4 = work_dir / "final_1080p.mp4"

    # Smooth cinematic xfade transitions between scenes (for 2..24 scenes)
    if use_xfade:
        transitions = ["fade", "smoothleft", "dissolve", "smoothright", "wipeleft", "fadeblack"]
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
        for sf in segment_files:
            cmd.extend(["-i", str(sf)])

        v_filters = []
        a_filters = []
        offset = seg_durations[0] - trans_dur
        prev_v = "0:v"
        prev_a = "0:a"
        for idx in range(1, len(segment_files)):
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
            "-movflags", "+faststart",
            str(final_mp4),
        ])
        subprocess.run(cmd, check=True)
        return final_mp4

    # Fast zero-overhead concat for 1-scene or long-form (>24 scenes) videos
    concat_list = work_dir / "concat.txt"
    concat_list.write_text("\n".join(f"file '{p}'" for p in segment_files), encoding="utf-8")
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(concat_list),
            "-c", "copy", "-movflags", "+faststart",
            str(final_mp4),
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
    scene_count = compute_scene_count(duration_sec)

    update_job({
        "status": "scripting",
        "progress_pct": 12,
        "scene_count": scene_count,
        "step_label": f"جاري كتابة القصة والسيناريو ({scene_count} مشهد)...",
    })

    story = generate_story_package(niche, style, language, voice_locale, duration_sec, scene_count, is_vertical)
    job["video_title"] = story["title"]
    update_job({
        "status": "imaging",
        "progress_pct": 20,
        "video_title": story["title"],
        "video_desc": story["description"],
        "step_label": f"جاري رسم المشاهد بالتوازي ({scene_count} مشهد 1080p)...",
    })

    with tempfile.TemporaryDirectory() as tmp:
        work_dir = Path(tmp)

        img_paths, _ = generate_all_scenes(story["scenes"], style, is_vertical, work_dir)

        update_job({
            "status": "voicing",
            "progress_pct": 62,
            "step_label": f"جاري تسجيل التعليق الصوتي ({language})...",
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
            "step_label": "جاري مونتاج الفيديو السينمائي 1080p والانتقالات...",
        })
        final_mp4 = build_1080p_video(
            story["scenes"], img_paths, audio_paths, durations, is_vertical, show_subtitles, work_dir
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


if __name__ == "__main__":
    try:
        main()
    except Exception as err:
        print(f"[ERROR] {err}", file=sys.stderr, flush=True)
        update_job({
            "status": "failed",
            "progress_pct": 100,
            "step_label": "تعذّر إكمال التوليد — لم يتم خصم أي رصيد",
            "error_message": str(err)[:450],
        })
        sys.exit(1)
