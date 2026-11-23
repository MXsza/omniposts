#!/usr/bin/env python3
"""
Omniposts.online — 24/7 1080p Cloud Video Worker
Pipeline:
  1. Load job & YouTube channel credentials from Supabase (render_jobs + channels)
  2. Generate localized viral story script + scene prompts + title/description via Runware Chat Completions
  3. Generate N scene images in parallel via Runware imageInference (runware:100@1 FLUX.1 schnell)
     and push live preview image URLs to Supabase render_jobs so the user watches scenes appear live!
  4. Synthesize natural voiceover in any world language/dialect (Male/Female) via Edge TTS (free)
  5. Assemble Full HD 1080p MP4 with smooth Ken Burns zoom/pan + crisp multilingual/RTL subtitles via FFmpeg
  6. Upload to YouTube via OAuth 2.0 Resumable Upload, deduct exact minutes from profiles.ai_provider ONLY on success,
     and update render_jobs + publish_logs.
"""

import asyncio
import datetime
import json
import math
import os
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
from PIL import Image, ImageDraw, ImageFont

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

    # Deduct minutes from profiles.ai_provider (skipped for owner admin)
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

    # Log to public.publish_logs using exact live columns
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
                "video_title": job.get("video_title") or job.get("niche") or "AI Video",
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
# Step 1: Story Script & Scene Prompt Generator (Runware Chat Completions)
# ==============================================================================
def compute_scene_count(duration_sec: int) -> int:
    duration_sec = max(5, min(3600, int(duration_sec)))
    if duration_sec <= 60:
        return max(2, math.ceil(duration_sec / 5))
    return max(12, min(260, math.ceil(duration_sec / 14)))


def generate_story_package(niche: str, style: str, language: str, duration_sec: int, scene_count: int, is_vertical: bool) -> dict:
    approx_words = max(18, min(7500, int(duration_sec * 2.2)))
    short_tag = " #Shorts" if (is_vertical and duration_sec <= 60) else ""

    system_prompt = (
        "You are an elite viral YouTube scriptwriter and visual director. "
        "Return ONLY valid JSON with no markdown code fences. "
        "NEVER mention any AI tool, website name, or 'Generated automatically' in the title, description, or narration."
    )
    user_prompt = (
        f"Create a captivating, original story about: '{niche}'.\n"
        f"Visual style: '{style}'.\n"
        f"Language/Dialect for title, description, and narration: '{language}'.\n"
        f"Target duration: {duration_sec} seconds (~{approx_words} words total).\n"
        f"Divide the story into EXACTLY {scene_count} sequential scenes.\n"
        "Return strict JSON matching this schema:\n"
        "{\n"
        '  "title": "Catchy viral YouTube title in the requested language (max 85 chars)",\n'
        '  "description": "Natural engaging YouTube description in the requested language with 4 relevant hashtags",\n'
        '  "tags": ["tag1", "tag2", "tag3", "tag4"],\n'
        '  "scenes": [\n'
        '    {"narration": "Spoken sentence(s) in the exact requested language/dialect", "image_prompt": "Rich English visual prompt matching the style, no text in image"}\n'
        "  ]\n"
        "}"
    )

    llm_models = ["openai:gpt@6-luna", "minimax:m3@0", "openai:gpt@5.4-mini"]
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
            if resp.ok:
                raw = resp.json()["choices"][0]["message"]["content"].strip()
                raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
                parsed = json.loads(raw)
                scenes = parsed.get("scenes") or []
                if len(scenes) >= 2:
                    while len(scenes) < scene_count:
                        scenes.append(scenes[-1])
                    scenes = scenes[:scene_count]
                    title = str(parsed.get("title") or niche).strip()[:90]
                    if short_tag and "#shorts" not in title.lower():
                        title = f"{title}{short_tag}"[:95]
                    return {
                        "title": title,
                        "description": str(parsed.get("description") or title).strip(),
                        "tags": parsed.get("tags") or [niche[:25], "Shorts"],
                        "scenes": scenes,
                    }
        except Exception as exc:
            print(f"[WARN] Runware LLM {model_id} fallback: {exc}", flush=True)

    is_ar = ("عرب" in language) or ("ar-" in language.lower()) or ("arab" in language.lower())
    scenes = []
    for idx in range(scene_count):
        nar = (
            f"في المشهد رقم {idx + 1} من حكاية {niche}، تتصاعد الأحداث بشكل غير متوقع تماماً."
            if is_ar
            else f"In chapter {idx + 1} of {niche}, an unexpected turn changes everything."
        )
        scenes.append({
            "narration": nar,
            "image_prompt": f"{style}, cinematic scene {idx + 1} depicting {niche}, ultra detailed, dramatic lighting, vivid colors, no text",
        })
    title = (f"{niche} — شاهد النهاية غير المتوقعة!{short_tag}" if is_ar else f"{niche} — Wait for the ending!{short_tag}")[:95]
    desc = (
        f"قصة مشوقة عن {niche}. اشترك في القناة لمتابعة الجديد يومياً!{short_tag} #قصص #حكايات"
        if is_ar
        else f"An unforgettable story about {niche}. Subscribe for new stories every day!{short_tag} #Storytime"
    )
    return {"title": title, "description": desc, "tags": [niche[:25], "Story"], "scenes": scenes}


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
        prompt = f"{style}, {scenes[i]['image_prompt']}, cinematic 8K lighting, no text, no watermark"
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
    comm = edge_tts.Communicate(text=text, voice=voice, rate="+4%")
    await comm.save(str(out_mp3))


def get_audio_duration(audio_path: Path) -> float:
    out = subprocess.check_output(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path),
        ],
        text=True,
    ).strip()
    return max(1.5, float(out or 4.0))


# ==============================================================================
# Step 4: Crisp RTL/Multilingual Subtitle Overlay + FFmpeg 1080p Ken Burns
# ==============================================================================
def find_font_path() -> str:
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return ""


def shape_caption_text(text: str) -> str:
    if re.search(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]", text):
        return get_display(arabic_reshaper.reshape(text))
    return text


def render_subtitle_png(text: str, out_png: Path, width: int, height: int):
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font_size = 54 if width <= 1080 else 46
    font_path = find_font_path()
    font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()

    words = text.strip().split()
    lines = []
    cur = []
    max_chars = 26 if width <= 1080 else 46
    for w in words:
        if sum(len(x) + 1 for x in cur) + len(w) > max_chars and cur:
            lines.append(" ".join(cur))
            cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(" ".join(cur))
    lines = lines[:3]

    shaped_lines = [shape_caption_text(ln) for ln in lines]
    line_heights = []
    line_widths = []
    for sl in shaped_lines:
        bbox = draw.textbbox((0, 0), sl, font=font)
        line_widths.append(bbox[2] - bbox[0])
        line_heights.append(bbox[3] - bbox[1])

    pad_x, pad_y = 28, 18
    gap = 12
    box_w = min(width - 60, max(line_widths, default=200) + pad_x * 2)
    box_h = sum(line_heights) + gap * max(0, len(shaped_lines) - 1) + pad_y * 2
    box_x = (width - box_w) // 2
    box_y = int(height * 0.76) - box_h // 2

    draw.rounded_rectangle(
        [box_x, box_y, box_x + box_w, box_y + box_h],
        radius=22,
        fill=(8, 12, 24, 195),
        outline=(99, 102, 241, 210),
        width=3,
    )

    y = box_y + pad_y
    for sl, lw, lh in zip(shaped_lines, line_widths, line_heights):
        x = (width - lw) // 2
        draw.text((x + 2, y + 2), sl, font=font, fill=(0, 0, 0, 230))
        draw.text((x, y), sl, font=font, fill=(255, 255, 255, 255))
        y += lh + gap

    img.save(str(out_png), "PNG")


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
    segment_files = []

    for i, (scene, img_p, aud_p, dur) in enumerate(zip(scenes, img_paths, audio_paths, durations)):
        seg_out = work_dir / f"seg_{i:04d}.mp4"
        frames = max(30, int(math.ceil(dur * fps)))
        z_expr = "min(zoom+0.0008,1.12)" if i % 2 == 0 else "if(lte(zoom,1.0),1.12,max(1.0,zoom-0.0008))"

        vf_base = (
            f"scale={W*2}:{H*2}:force_original_aspect_ratio=increase,"
            f"crop={W*2}:{H*2},"
            f"zoompan=z='{z_expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps={fps},"
            f"format=yuv420p"
        )

        if show_subtitles and scene.get("narration"):
            sub_png = work_dir / f"sub_{i:04d}.png"
            render_subtitle_png(scene["narration"], sub_png, W, H)
            cmd = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-loop", "1", "-i", str(img_p),
                "-i", str(sub_png),
                "-i", str(aud_p),
                "-filter_complex", f"[0:v]{vf_base}[bg];[bg][1:v]overlay=0:0:shortest=1[v]",
                "-map", "[v]", "-map", "2:a",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
                "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
                "-t", f"{dur:.2f}", "-shortest",
                str(seg_out),
            ]
        else:
            cmd = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-loop", "1", "-i", str(img_p),
                "-i", str(aud_p),
                "-vf", vf_base,
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
                "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
                "-t", f"{dur:.2f}", "-shortest",
                str(seg_out),
            ]
        subprocess.run(cmd, check=True)
        segment_files.append(seg_out)

    concat_list = work_dir / "concat.txt"
    concat_list.write_text("\n".join(f"file '{p}'" for p in segment_files), encoding="utf-8")
    final_mp4 = work_dir / "final_1080p.mp4"
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
# Step 5: YouTube OAuth 2.0 Resumable Upload
# ==============================================================================

def upload_mp4_to_storage(mp4_path: Path, job_id: str) -> str:
    """Upload rendered 1080p MP4 to Supabase Storage public bucket (videos) for direct client download."""
    try:
        # Ensure public bucket exists (idempotent)
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

    story = generate_story_package(niche, style, language, duration_sec, scene_count, is_vertical)
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
            durations.append(get_audio_duration(mp3_p))

        update_job({
            "status": "rendering",
            "progress_pct": 76,
            "step_label": "جاري مونتاج الفيديو بدقة Full HD 1080p وحركة الكاميرا...",
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
