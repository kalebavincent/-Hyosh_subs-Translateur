import os
import re
import time
import whisper
import requests
import asyncio
import threading
import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pyrogram import Client, filters
from pyrogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery
)
from dotenv import load_dotenv

load_dotenv()

WHISPER_MODEL = "tiny"
MODEL_LOAD_TIMES = {
    "tiny": 0.5,
    "base": 1,
    "small": 2,
    "medium": 4,
    "large": 8
}

# Configuration DeepL
DEEPL_API_URL = "https://api-free.deepl.com/v2/translate"
SOURCE_LANG = "JA"
TARGET_LANG = "FR"

# Configuration Pyrogram
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
DEEPL_API_KEY = os.getenv("DEEPL_API_KEY")

# Configuration sécurité
ALLOWED_USERS = os.getenv("ALLOWED_USERS", "")
# Convertit en liste d'entiers
if ALLOWED_USERS:
    ALLOWED_USERS = [int(uid.strip()) for uid in ALLOWED_USERS.split(",") if uid.strip().isdigit()]
else:
    ALLOWED_USERS = []

HEALTH_SERVER_PORT = 8080
HEALTH_SERVER_ADDRESS = '0.0.0.0'

user_models = {}
user_status = {}

app = Client(
    "transcription_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'OK')
        elif self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b'<html><body><h1>Transcription Bot</h1><p>Status: <a href="/health">/health</a></p></body></html>')
        else:
            self.send_response(404)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Not Found')
    
    def do_HEAD(self):
        if self.path == '/health' or self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

def run_health_server():
    server = HTTPServer((HEALTH_SERVER_ADDRESS, HEALTH_SERVER_PORT), HealthCheckHandler)
    print(f"✅ Serveur de santé démarré sur le port {HEALTH_SERVER_PORT}")
    server.serve_forever()

def format_timestamp(seconds):
    millis = int((seconds - int(seconds)) * 1000)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"

def progress_bar(percentage, length=20):
    filled = int(percentage / 100 * length)
    return "[" + "=" * filled + " " * (length - filled) + "]"

async def transcribe_audio(file_path: str, model_name: str, status_msg: Message, user_id: int):
    user_status[user_id] = {"cancelled": False}

    print(f"Chargement du modèle Whisper '{model_name}'...")
    try:
        await status_msg.edit_text(
            f"🔠 **Chargement du modèle {model_name.upper()}**\n"
            f"⏱ Temps estimé: {MODEL_LOAD_TIMES.get(model_name, 2)} min"
        )
    except Exception:
        pass

    model = whisper.load_model(model_name)

    if user_status.get(user_id, {}).get("cancelled"):
        return None

    print(f"Début de la transcription de : {file_path}")
    start_time = time.time()
    
    # Dernière mise à jour pour éviter le flood
    last_progress_update = time.time()
    
    # Callback pour la progression
    def progress_callback(progress):
        nonlocal last_progress_update
        
        if user_status.get(user_id, {}).get("cancelled"):
            return True
            
        current_time = time.time()
        # Mettre à jour max toutes les 5 secondes
        if current_time - last_progress_update > 5 or progress == 1:
            elapsed = time.time() - start_time
            total_est = elapsed / progress if progress > 0 else 0
            remaining = max(0, total_est - elapsed)
            
            try:
                app.loop.create_task(
                    status_msg.edit_text(
                        f"🔠 **Transcription en cours**\n"
                        f"{progress_bar(progress*100)} {progress*100:.1f}%\n"
                        f"⏱ Temps écoulé: {elapsed:.0f}s\n"
                        f"⏳ Temps restant: ~{remaining:.0f}s\n\n"
                        f"Modèle: {model_name.upper()}",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("❌ Annuler", callback_data="cancel_operation")]
                        ])
                    )
                )
            except Exception:
                pass
            last_progress_update = current_time
    
    result = model.transcribe(
        file_path,
        verbose=True,
        task="transcribe",
        progress_callback=progress_callback
    )

    if user_status.get(user_id, {}).get("cancelled"):
        return None

    elapsed = time.time() - start_time
    print(f"Transcription terminée en {elapsed:.2f}s")

    srt_content = ""
    for i, segment in enumerate(result["segments"], start=1):
        if user_status.get(user_id, {}).get("cancelled"):
            return None

        start = format_timestamp(segment["start"])
        end = format_timestamp(segment["end"])
        text = segment["text"].strip()
        srt_content += f"{i}\n{start} --> {end}\n{text}\n\n"

    return srt_content

def translate_text(text: str, context: str = "") -> str:
    if not text.strip():
        return ""

    try:
        data = {
            "auth_key": DEEPL_API_KEY,
            "text": text,
            "source_lang": SOURCE_LANG,
            "target_lang": TARGET_LANG,
            "preserve_formatting": "1",
            "split_sentences": "0",
            "context": context[:5000]
        }
        response = requests.post(DEEPL_API_URL, data=data, timeout=30)
        response.raise_for_status()
        return response.json()["translations"][0]["text"]
    except Exception as e:
        print(f"Erreur traduction: {e}")
        return text

async def translate_srt_content(srt_content: str, status_msg: Message, user_id: int):
    user_status[user_id] = {"cancelled": False}

    entries = []
    blocks = re.split(r'\n{2,}', srt_content.strip())

    for block in blocks:
        lines = block.split('\n')
        if len(lines) < 3:
            continue

        num = lines[0].strip()
        timecode_match = re.match(
            r'(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})',
            lines[1].strip()
        )

        if timecode_match:
            timecode = lines[1].strip()
            text = '\n'.join(lines[2:]).strip()
            entries.append((num, timecode, text))

    translated_content = ""
    context_buffer = []
    total_segments = len(entries)
    processed = 0

    if not total_segments:
        return ""

    start_time = time.time()
    segment_times = []
    last_update = 0

    for idx, (num, timecode, text) in enumerate(entries, start=1):
        if user_status.get(user_id, {}).get("cancelled"):
            return None

        context = " ".join(context_buffer[-2:]) if context_buffer else ""

        if text.strip():
            progress = int(idx * 100 / total_segments)
            segment_start = time.time()

            translated = translate_text(text, context)
            translated = re.sub(r'\n{2,}', '\n', translated).strip()

            segment_time = time.time() - segment_start
            segment_times.append(segment_time)
            avg_time = sum(segment_times) / len(segment_times) if segment_times else 0
            remaining = (total_segments - idx) * avg_time

            # Mise à jour max toutes les 5 secondes
            current_time = time.time()
            if current_time - last_update > 5 or idx == total_segments:
                try:
                    await status_msg.edit_text(
                        f"🌍 **Traduction en cours**\n"
                        f"{progress_bar(progress)} {progress}%\n"
                        f"⏱ Temps restant: ~{remaining:.0f}s\n"
                        f"📊 Segments: {idx}/{total_segments}\n\n"
                        f"`{translated[:100]}{'...' if len(translated) > 100 else ''}`",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("❌ Annuler", callback_data="cancel_operation")]
                        ])
                    )
                except Exception:
                    pass
                last_update = current_time
        else:
            translated = text

        context_buffer.append(text)
        translated_content += f"{num}\n{timecode}\n{translated}\n\n"
        processed += 1

        # Pause courte pour permettre les annulations
        if idx % 5 == 0:
            await asyncio.sleep(0.1)

    return translated_content

@app.on_callback_query(filters.regex(r"^cancel_operation$"))
async def cancel_operation(_, query: CallbackQuery):
    user_id = query.from_user.id
    user_status[user_id] = {"cancelled": True}
    await query.answer("Opération annulée!")
    try:
        await query.message.edit_text("❌ Opération annulée par l'utilisateur")
    except Exception:
        pass

@app.on_message(filters.command(["start", "help"]))
async def start_command(client: Client, message: Message):
    if ALLOWED_USERS and message.from_user.id not in ALLOWED_USERS:
        await message.reply_text("❌ Accès non autorisé, contacter l'administrateur. (@Hyoshdesign)")
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎧 Transcrire audio", callback_data="transcribe_help")],
        [InlineKeyboardButton("🌍 Traduire SRT", callback_data="translate_help")],
        [InlineKeyboardButton("⚙️ Choisir modèle", callback_data="select_model")]
    ])

    help_text = (
        "🤖 **Bot de Transcription et Traduction**\n\n"
        "Envoyez un fichier audio/vidéo ou un fichier SRT à traduire\n\n"
        "**Commandes disponibles:**\n"
        "/transcribe - Transcription seule\n"
        "/translate - Traduction seule (répondez à un SRT)\n"
        "/model - Changer le modèle Whisper\n\n"
        f"🟢 Port santé: {HEALTH_SERVER_PORT}"
    )
    await message.reply_text(help_text, reply_markup=keyboard)

@app.on_callback_query(filters.regex(r"^select_model$"))
async def select_model(_, query: CallbackQuery):
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Tiny ⚡", callback_data="model_tiny"),
            InlineKeyboardButton("Base 🚀", callback_data="model_base")
        ],
        [
            InlineKeyboardButton("Small 🐇", callback_data="model_small"),
            InlineKeyboardButton("Medium 🐢", callback_data="model_medium")
        ],
        [InlineKeyboardButton("Large 🐘", callback_data="model_large")]
    ])

    current_model = user_models.get(query.from_user.id, WHISPER_MODEL)
    await query.message.edit_text(
        f"🔧 **Sélectionnez un modèle Whisper**\n"
        f"Modèle actuel: **{current_model.upper()}**\n\n"
        "⚖️ **Précision / Vitesse:**\n"
        "Tiny: Très rapide, précision faible\n"
        "Base: Rapide, précision moyenne\n"
        "Small: Équilibré\n"
        "Medium: Lent, bonne précision\n"
        "Large: Très lent, meilleure précision",
        reply_markup=keyboard
    )

@app.on_callback_query(filters.regex(r"^model_(tiny|base|small|medium|large)$"))
async def set_model(_, query: CallbackQuery):
    model = query.data.split("_")[1]
    user_models[query.from_user.id] = model
    await query.answer(f"Modèle défini: {model.capitalize()}")
    await query.message.edit_text(f"✅ Modèle Whisper défini sur: **{model.upper()}**")

@app.on_message(filters.command("model"))
async def model_command(client: Client, message: Message):
    current_model = user_models.get(message.from_user.id, WHISPER_MODEL)
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Tiny ⚡", callback_data="model_tiny"),
            InlineKeyboardButton("Base 🚀", callback_data="model_base")
        ],
        [
            InlineKeyboardButton("Small 🐇", callback_data="model_small"),
            InlineKeyboardButton("Medium 🐢", callback_data="model_medium")
        ],
        [InlineKeyboardButton("Large 🐘", callback_data="model_large")]
    ])

    await message.reply_text(
        f"🔧 **Sélectionnez un modèle Whisper**\n"
        f"Modèle actuel: **{current_model.upper()}**\n\n"
        "⚖️ **Précision / Vitesse:**\n"
        "Tiny: Très rapide, précision faible\n"
        "Base: Rapide, précision moyenne\n"
        "Small: Équilibré\n"
        "Medium: Lent, bonne précision\n"
        "Large: Très lent, meilleure précision",
        reply_markup=keyboard
    )

async def process_media(client: Client, message: Message, translate=True):
    if ALLOWED_USERS and message.from_user.id not in ALLOWED_USERS:
        await message.reply_text("❌ Accès non autorisé, contacter l'administrateur. (@Hyoshdesign)")
        return

    is_srt = (message.document and
              message.document.file_name and
              message.document.file_name.endswith('.srt'))

    if is_srt:
        await handle_translation(client, message)
        return

    if message.document and not message.document.mime_type.startswith(('audio/', 'video/')):
        await message.reply_text("❌ Format de fichier non supporté.")
        return

    model_name = user_models.get(message.from_user.id, WHISPER_MODEL)
    user_id = message.from_user.id

    if message.audio:
        file_size = message.audio.file_size
    elif message.document:
        file_size = message.document.file_size
    else:
        await message.reply_text("❌ Format de fichier non supporté.")
        return

    size_mb = file_size / (1024 * 1024)

    status_msg = await message.reply_text(
        f"⏳ **Téléchargement**\n"
        f"📦 Taille: {size_mb:.1f} MB\n"
        f"🔠 Modèle: {model_name.upper()}\n\n"
        "0% " + progress_bar(0),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Annuler", callback_data="cancel_operation")]
        ])
    )

    # Dernière mise à jour pour éviter le flood
    last_progress = 0
    last_update = time.time()
    
    def download_progress(current, total):
        nonlocal last_progress, last_update
        
        progress = current / total * 100
        current_time = time.time()
        
        # Mettre à jour max toutes les 3 secondes ou si progression > 5%
        if current_time - last_update > 3 or progress - last_progress > 5 or progress == 100:
            try:
                # Utiliser create_task pour éviter les problèmes de boucle d'événements
                app.loop.create_task(
                    update_download_status(status_msg, current, total, size_mb, model_name, progress)
                )
            except Exception:
                pass
            last_progress = progress
            last_update = current_time

    try:
        file_path = await message.download(progress=download_progress)
    except Exception as e:
        try:
            await status_msg.edit_text(f"❌ **Erreur téléchargement**\n`{str(e)}`")
        except Exception:
            pass
        return

    try:
        await status_msg.edit_text(
            "✅ **Fichier téléchargé!**\n"
            "🔠 Démarrage de la transcription...\n\n"
            "0% " + progress_bar(0),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Annuler", callback_data="cancel_operation")]
            ])
    except Exception as e:
        pass

    try:
        srt_content = await transcribe_audio(file_path, model_name, status_msg, user_id)
        if srt_content is None:
            try:
                os.remove(file_path)
            except Exception:
                pass
            return
    except Exception as e:
        try:
            await status_msg.edit_text(f"❌ **Erreur transcription**\n`{str(e)}`")
        except Exception:
            pass
        try:
            os.remove(file_path)
        except Exception:
            pass
        return

    original_srt = file_path + ".original.srt"
    try:
        with open(original_srt, "w", encoding="utf-8") as f:
            f.write(srt_content)
    except Exception as e:
        try:
            await status_msg.edit_text(f"❌ **Erreur création fichier**\n`{str(e)}`")
        except Exception:
            pass
        try:
            os.remove(file_path)
        except Exception:
            pass
        return

    if translate:
        try:
            await status_msg.edit_text(
                "✅ **Transcription terminée!**\n"
                "🌍 Démarrage de la traduction...\n\n"
                "0% " + progress_bar(0),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("❌ Annuler", callback_data="cancel_operation")]
                ])
        except Exception:
            pass

        try:
            translated_content = await translate_srt_content(srt_content, status_msg, user_id)
            if translated_content is None:
                try:
                    os.remove(file_path)
                    os.remove(original_srt)
                except Exception:
                    pass
                return

            translated_srt = file_path + ".translated.srt"
            with open(translated_srt, "w", encoding="utf-8") as f:
                f.write(translated_content)
        except Exception as e:
            try:
                await status_msg.edit_text(f"❌ **Erreur traduction**\n`{str(e)}`")
            except Exception:
                pass
            try:
                os.remove(file_path)
                os.remove(original_srt)
            except Exception:
                pass
            return

    try:
        await status_msg.edit_text("✅ **Traitement terminé!**\nEnvoi des fichiers...")
    except Exception:
        pass

    caption = f"🔠 Transcription ({model_name.upper()})"
    try:
        await message.reply_document(
            document=original_srt,
            caption=caption
        )

        if translate:
            await message.reply_document(
                document=translated_srt,
                caption="🌍 Traduction FR"
            )
    except Exception as e:
        try:
            await status_msg.edit_text(f"❌ **Erreur envoi fichier**\n`{str(e)}`")
        except Exception:
            pass

    # Nettoyage des fichiers temporaires
    try:
        os.remove(file_path)
        os.remove(original_srt)
        if translate:
            os.remove(translated_srt)
    except Exception:
        pass

    try:
        await status_msg.delete()
    except Exception:
        pass

async def update_download_status(status_msg, current, total, size_mb, model_name, progress):
    try:
        await status_msg.edit_text(
            f"⏳ **Téléchargement**\n"
            f"📦 Taille: {size_mb:.1f} MB\n"
            f"🔠 Modèle: {model_name.upper()}\n\n"
            f"{progress:.1f}% " + progress_bar(progress),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Annuler", callback_data="cancel_operation")]
            ])
    except Exception:
        # Le message a peut-être été supprimé, ignorer l'erreur
        pass

async def handle_translation(client: Client, message: Message):
    if not message.reply_to_message or not message.reply_to_message.document:
        await message.reply_text("🔍 Répondez à un fichier SRT avec /translate")
        return

    status_msg = await message.reply_text(
        "⏳ **Démarrage de la traduction**\n\n"
        "0% " + progress_bar(0),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Annuler", callback_data="cancel_operation")]
        ])
    )

    user_id = message.from_user.id

    try:
        srt_path = await message.reply_to_message.download()
    except Exception as e:
        try:
            await status_msg.edit_text(f"❌ **Erreur téléchargement**\n`{str(e)}`")
        except Exception:
            pass
        return

    try:
        with open(srt_path, "r", encoding="utf-8") as f:
            srt_content = f.read()
    except Exception as e:
        try:
            await status_msg.edit_text(f"❌ **Erreur lecture fichier**\n`{str(e)}`")
        except Exception:
            pass
        try:
            os.remove(srt_path)
        except Exception:
            pass
        return

    try:
        translated_content = await translate_srt_content(srt_content, status_msg, user_id)
        if translated_content is None:
            try:
                os.remove(srt_path)
            except Exception:
                pass
            return

        translated_srt = srt_path + ".translated.srt"
        with open(translated_srt, "w", encoding="utf-8") as f:
            f.write(translated_content)
    except Exception as e:
        try:
            await status_msg.edit_text(f"❌ **Erreur traduction**\n`{str(e)}`")
        except Exception:
            pass
        try:
            os.remove(srt_path)
        except Exception:
            pass
        return

    try:
        await message.reply_document(
            document=translated_srt,
            caption="🌍 Traduction FR"
        )
    except Exception as e:
        try:
            await status_msg.edit_text(f"❌ **Erreur envoi fichier**\n`{str(e)}`")
        except Exception:
            pass

    # Nettoyage des fichiers temporaires
    try:
        os.remove(srt_path)
        os.remove(translated_srt)
    except Exception:
        pass
    
    try:
        await status_msg.delete()
    except Exception:
        pass

@app.on_message(filters.command("transcribe"))
async def transcribe_command(client: Client, message: Message):
    await process_media(client, message, translate=False)

@app.on_message(filters.command("translate"))
async def translate_command(client: Client, message: Message):
    if message.reply_to_message and message.reply_to_message.document:
        if message.reply_to_message.document.file_name and message.reply_to_message.document.file_name.endswith('.srt'):
            await handle_translation(client, message)
            return
    await message.reply_text("🔍 Répondez à un fichier SRT avec /translate")

@app.on_message(filters.audio | filters.video | filters.voice | filters.document)
async def handle_media(client: Client, message: Message):
    await process_media(client, message, translate=True)

def start_health_server():
    def run():
        server = HTTPServer((HEALTH_SERVER_ADDRESS, HEALTH_SERVER_PORT), HealthCheckHandler)
        print(f"✅ Serveur de santé démarré sur http://{HEALTH_SERVER_ADDRESS}:{HEALTH_SERVER_PORT}/health")
        server.serve_forever()

    thread = threading.Thread(target=run)
    thread.daemon = True
    thread.start()

if __name__ == "__main__":
    start_health_server()
    print("Démarrage du bot de transcription...")
    print(f"🟢 Bot démarré à {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    app.run()