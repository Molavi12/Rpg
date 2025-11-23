#!/usr/bin/env python3
import os
import logging
import asyncio
import re
import datetime
import signal
import sys
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import yt_dlp
from config import *

# تنظیمات لاگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ایجاد دایرکتوری دانلود
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# فونت یونیکد برای اعداد
UNICODE_NUMBERS = {
    '0': '𝟬', '1': '𝟭', '2': '𝟮', '3': '𝟯', '4': '𝟰',
    '5': '𝟱', '6': '𝟲', '7': '𝟳', '8': '𝟴', '9': '𝟵'
}

# متغیرهای جهانی برای مدیریت وضعیت
bot_application = None
update_task = None

def convert_to_unicode_font(text):
    """تبدیل اعداد به فونت یونیکد"""
    return ''.join(UNICODE_NUMBERS.get(char, char) for char in text)

def get_new_year_countdown():
    """محاسبه ثانیه‌های باقیمانده تا سال جدید میلادی"""
    now = datetime.datetime.utcnow()
    next_year = now.year + 1
    new_year = datetime.datetime(next_year, 1, 1, 0, 0, 0)
    time_left = new_year - now
    seconds_left = int(time_left.total_seconds())
    
    # تبدیل به روز، ساعت، دقیقه و ثانیه
    days = seconds_left // (24 * 3600)
    seconds_left %= (24 * 3600)
    hours = seconds_left // 3600
    seconds_left %= 3600
    minutes = seconds_left // 60
    seconds = seconds_left % 60
    
    return days, hours, minutes, seconds

def get_current_time_unicode():
    """دریافت زمان جاری با فونت یونیکد"""
    now = datetime.datetime.utcnow()
    time_str = now.strftime("%H:%M:%S")
    return convert_to_unicode_font(time_str)

def get_bot_name_with_clock():
    """نام بات به همراه ساعت زنده"""
    base_name = "🎬 YouTube Downloader"
    current_time = get_current_time_unicode()
    return f"{base_name} ⏰ {current_time}"

def get_bio_text():
    """متن بیو بات با شمارش معکوس سال جدید"""
    days, hours, minutes, seconds = get_new_year_countdown()
    
    countdown_text = f"⏳ {days}d {hours:02d}:{minutes:02d}:{seconds:02d}"
    new_year_text = "تا سال جدید میلادی"
    
    return f"{countdown_text} {new_year_text}"

async def update_bot_info_manually(application):
    """بروزرسانی دستی نام و بیو بات"""
    try:
        # بروزرسانی نام بات با ساعت
        new_name = get_bot_name_with_clock()
        await application.bot.set_my_name(new_name)
        
        # بروزرسانی بیو بات با شمارش معکوس
        new_bio = get_bio_text()
        await application.bot.set_my_description(new_bio)
        
        logger.info("Bot name and bio updated successfully")
        return True
    except Exception as e:
        logger.error(f"Error updating bot info: {e}")
        return False

async def background_updater(application):
    """بروزرسانی پس‌زمینه نام و بیو بات"""
    logger.info("Background updater started")
    while True:
        try:
            success = await update_bot_info_manually(application)
            if not success:
                logger.warning("Failed to update bot info, will retry in 60 seconds")
            await asyncio.sleep(60)  # هر 60 ثانیه
        except asyncio.CancelledError:
            logger.info("Background updater cancelled")
            break
        except Exception as e:
            logger.error(f"Background updater error: {e}")
            await asyncio.sleep(60)

async def is_user_member(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """بررسی عضویت کاربر در کانال"""
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Error checking membership: {e}")
        return False

def get_available_formats(url):
    """دریافت لیست فرمت‌های موجود برای ویدیو"""
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'listformats': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(url, download=False)
            return result.get('formats', [])
    except Exception as e:
        logger.error(f"Error getting available formats: {e}")
        return []

def get_video_info(url):
    """دریافت اطلاعات ویدیو"""
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web'],
                    'player_skip': ['configs', 'webpage']
                }
            },
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return {
                'title': info.get('title', 'Unknown'),
                'duration': info.get('duration', 0),
                'uploader': info.get('uploader', 'Unknown'),
                'thumbnail': info.get('thumbnail', None),
                'formats': info.get('formats', [])
            }
    except Exception as e:
        logger.error(f"Error getting video info: {e}")
        return None

def get_best_available_format(url, preferred_quality):
    """پیدا کردن بهترین فرمت موجود بر اساس کیفیت مورد نظر"""
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web'],
                    'player_skip': ['configs', 'webpage']
                }
            },
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = info.get('formats', [])
            
            # فیلتر کردن فرمت‌های ویدیویی
            video_formats = [f for f in formats if f.get('vcodec') != 'none' and f.get('acodec') != 'none']
            audio_formats = [f for f in formats if f.get('vcodec') == 'none' and f.get('acodec') != 'none']
            
            # اگر کاربر صدا خواست
            if preferred_quality == 'audio':
                best_audio = None
                for fmt in audio_formats:
                    if fmt.get('filesize') and fmt.get('filesize') < MAX_FILE_SIZE * 1024 * 1024:
                        if not best_audio or fmt.get('abr', 0) > best_audio.get('abr', 0):
                            best_audio = fmt
                if best_audio:
                    return best_audio['format_id']
                # اگر فرمت صوتی با محدودیت حجم پیدا نشد، بهترین فرمت صوتی را برمی‌گرداند
                if audio_formats:
                    return audio_formats[0]['format_id']
                return None
            
            # برای ویدیوها
            quality_priority = []
            if preferred_quality == '144':
                quality_priority = ['144', '240', '360', '480', '720', 'best']
            elif preferred_quality == '240':
                quality_priority = ['240', '144', '360', '480', '720', 'best']
            elif preferred_quality == '360':
                quality_priority = ['360', '480', '240', '720', '144', 'best']
            elif preferred_quality == '480':
                quality_priority = ['480', '360', '720', '240', 'best', '144']
            elif preferred_quality == '720':
                quality_priority = ['720', '480', 'best', '360', '240', '144']
            elif preferred_quality == 'best':
                quality_priority = ['best', '720', '480', '360', '240', '144']
            
            # جستجو برای پیدا کردن بهترین فرمت موجود
            for quality in quality_priority:
                if quality == 'best':
                    # پیدا کردن بهترین کیفیت با محدودیت حجم
                    best_format = None
                    for fmt in video_formats:
                        if fmt.get('filesize') and fmt.get('filesize') < MAX_FILE_SIZE * 1024 * 1024:
                            if not best_format or fmt.get('height', 0) > best_format.get('height', 0):
                                best_format = fmt
                    if best_format:
                        return best_format['format_id']
                else:
                    target_height = int(quality.replace('p', ''))
                    # پیدا کردن فرمت با ارتفاع مورد نظر
                    for fmt in video_formats:
                        if fmt.get('height') == target_height:
                            if fmt.get('filesize') and fmt.get('filesize') < MAX_FILE_SIZE * 1024 * 1024:
                                return fmt['format_id']
            
            # اگر هیچ فرمتی با محدودیت حجم پیدا نشد، بهترین فرمت بدون محدودیت حجم
            if video_formats:
                return video_formats[0]['format_id']
            
            return None
            
    except Exception as e:
        logger.error(f"Error finding best format: {e}")
        return None

def download_video_robust(url, quality='best'):
    """دانلود قوی ویدیو با مدیریت خودکار فرمت‌ها"""
    try:
        # پیدا کردن بهترین فرمت موجود
        best_format = get_best_available_format(url, quality)
        
        if not best_format:
            logger.error("No suitable format found")
            return None

        # کپی تنظیمات پایه
        ydl_opts = YT_DLP_OPTIONS.copy()
        ydl_opts['outtmpl'] = f'{DOWNLOAD_DIR}/%(title).100s.%(ext)s'
        
        # استفاده از فرمت پیدا شده
        ydl_opts['format'] = best_format
        
        # تنظیمات postprocessor برای صدا
        if quality == 'audio':
            ydl_opts.update({
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            })
        
        logger.info(f"Downloading with format: {best_format} for quality: {quality}")
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            # برای فایل صوتی
            if quality == 'audio':
                base_name = os.path.splitext(filename)[0]
                filename = base_name + '.mp3'
                if not os.path.exists(filename):
                    for ext in ['.webm', '.m4a', '.opus', '.mp3']:
                        temp_file = base_name + ext
                        if os.path.exists(temp_file):
                            if ext != '.mp3':
                                os.rename(temp_file, filename)
                            break
            
            file_size = os.path.getsize(filename) if os.path.exists(filename) else 0
            
            return {
                'file_path': filename,
                'title': info.get('title', 'Unknown'),
                'file_size': file_size,
                'actual_quality': quality
            }
            
    except Exception as e:
        logger.error(f"Download error: {str(e)}")
        
        # تلاش با تنظیمات fallback
        try:
            logger.info("Trying fallback download...")
            ydl_opts_fallback = {
                'outtmpl': f'{DOWNLOAD_DIR}/%(title).100s.%(ext)s',
                'format': 'best[filesize<50M]/best',
                'quiet': False,
                'no_warnings': False,
            }
            
            if quality == 'audio':
                ydl_opts_fallback.update({
                    'format': 'bestaudio[filesize<50M]/bestaudio',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }],
                })
            
            with yt_dlp.YoutubeDL(ydl_opts_fallback) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                
                if quality == 'audio':
                    base_name = os.path.splitext(filename)[0]
                    filename = base_name + '.mp3'
                    if not os.path.exists(filename):
                        for ext in ['.webm', '.m4a', '.opus', '.mp3']:
                            temp_file = base_name + ext
                            if os.path.exists(temp_file):
                                if ext != '.mp3':
                                    os.rename(temp_file, filename)
                                break
                
                file_size = os.path.getsize(filename) if os.path.exists(filename) else 0
                
                return {
                    'file_path': filename,
                    'title': info.get('title', 'Unknown'),
                    'file_size': file_size,
                    'actual_quality': 'best_available'
                }
                
        except Exception as fallback_error:
            logger.error(f"Fallback download also failed: {fallback_error}")
            return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور شروع"""
    user_id = update.effective_user.id
    
    if not await is_user_member(user_id, context):
        message_text = "لطفاً اول در کانال ما عضو شوید سپس از ربات استفاده کنید! 🎯"
        keyboard = [
            [InlineKeyboardButton("📢 عضویت در کانال", url=CHANNEL_LINK)],
            [InlineKeyboardButton("✅ بررسی عضویت", callback_data="check_membership")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(message_text, reply_markup=reply_markup)
        return
    
    welcome_text = f"""
🎉 **به ربات دانلودر یوتیوب خوش آمدید!**

📥 برای دانلود ویدیو از یوتیوب، لینک ویدیو را ارسال کنید.

⚡ **قابلیت‌ها:**
• دانلود با کیفیت‌های مختلف (144p تا 720p)
• دانلود صدا (MP3)
• پشتیبانی از اکثر لینک‌های یوتیوب
• مدیریت خودکار فرمت‌های در دسترس
• دانلود سریع و پایدار

⚠️ **نکات مهم:**
• حداکثر حجم فایل: {MAX_FILE_SIZE}MB 
• پلی‌لیست پشتیبانی نمی‌شود
• در صورت عدم وجود کیفیت مورد نظر، بهترین کیفیت موجود دانلود می‌شود

🔧 **کیفیت‌های موجود:**
- 144p (سریع‌ترین)
- 240p (متوسط)
- 360p (خوب)
- 480p (عالی)
- 720p (HD)
- صدا (MP3)
    """
    
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def handle_youtube_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش لینک یوتیوب"""
    user_id = update.effective_user.id
    
    if not await is_user_member(user_id, context):
        message_text = "لطفاً اول در کانال ما عضو شوید! 🎯"
        keyboard = [
            [InlineKeyboardButton("📢 عضویت در کانال", url=CHANNEL_LINK)],
            [InlineKeyboardButton("✅ بررسی عضویت", callback_data="check_membership")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(message_text, reply_markup=reply_markup)
        return
    
    url = update.message.text.strip()
    
    # بررسی معتبر بودن لینک
    youtube_pattern = r'(https?://)?(www\.)?(youtube|youtu)\.(com|be)/(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})'
    if not re.match(youtube_pattern, url):
        await update.message.reply_text("❌ لطفاً یک لینک معتبر یوتیوب ارسال کنید.")
        return
    
    processing_msg = await update.message.reply_text("🔍 در حال دریافت اطلاعات ویدیو...")
    
    video_info = get_video_info(url)
    if not video_info:
        await processing_msg.edit_text("❌ خطا در دریافت اطلاعات ویدیو. لطفاً از معتبر بودن لینک اطمینان حاصل کنید.")
        return
    
    # بررسی مدت زمان ویدیو
    duration_min = video_info['duration'] // 60
    duration_sec = video_info['duration'] % 60
    
    info_text = f"""
🎬 **{video_info['title'][:80]}**

👤 **آپلود کننده:** {video_info['uploader']}
⏱ **مدت زمان:** {duration_min}:{duration_sec:02d}

📥 **لطفاً کیفیت مورد نظر را انتخاب کنید:**
💡 *در صورت عدم وجود کیفیت مورد نظر، بهترین کیفیت موجود دانلود می‌شود*
    """
    
    keyboard = [
        [InlineKeyboardButton("144p (سریع)", callback_data=f"144_{url}")],
        [InlineKeyboardButton("240p (متوسط)", callback_data=f"240_{url}")],
        [InlineKeyboardButton("360p (خوب)", callback_data=f"360_{url}")],
        [InlineKeyboardButton("480p (عالی)", callback_data=f"480_{url}")],
        [InlineKeyboardButton("720p (HD)", callback_data=f"720_{url}")],
        [InlineKeyboardButton("🎵 صدا (MP3)", callback_data=f"audio_{url}")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await processing_msg.edit_text(info_text, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_quality_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش انتخاب کیفیت"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if not await is_user_member(user_id, context):
        message_text = "لطفاً اول در کانال ما عضو شوید! 🎯"
        await query.message.edit_text(message_text)
        return
    
    if query.data == "check_membership":
        if await is_user_member(user_id, context):
            await query.message.edit_text("✅ شما در کانال عضو هستید! لطفا دوباره /start را ارسال کنید.")
        else:
            await query.message.edit_text("❌ شما هنوز در کانال عضو نشده‌اید. لطفاً ابتدا در کانال عضو شوید.")
        return
    
    parts = query.data.split('_', 1)
    if len(parts) != 2:
        await query.message.edit_text("❌ خطا در پردازش درخواست.")
        return
    
    quality, url = parts
    
    quality_names = {
        '144': '144p', '240': '240p', '360': '360p', 
        '480': '480p', '720': '720p', 'audio': 'صدا (MP3)'
    }
    
    quality_name = quality_names.get(quality, 'نامشخص')
    
    await query.message.edit_text(f"⏳ در حال بررسی فرمت‌های موجود برای کیفیت {quality_name}...")
    
    # بررسی فرمت‌های موجود
    best_format = get_best_available_format(url, quality)
    if not best_format:
        await query.message.edit_text("❌ متأسفانه هیچ فرمت مناسبی برای این ویدیو پیدا نشد. لطفاً ویدیوی دیگری را امتحان کنید.")
        return
    
    await query.message.edit_text(f"⏳ در حال دانلود با بهترین کیفیت موجود...")
    
    # دانلود فایل
    download_result = download_video_robust(url, quality)
    
    if not download_result:
        await query.message.edit_text("❌ خطا در دانلود ویدیو. لطفاً دوباره تلاش کنید یا ویدیوی دیگری را امتحان کنید.")
        return
    
    if not os.path.exists(download_result['file_path']):
        await query.message.edit_text("❌ فایل دانلود شده یافت نشد.")
        return
    
    file_size_mb = download_result['file_size'] / 1024 / 1024
    
    # محدودیت حجم به 50MB
    if file_size_mb > MAX_FILE_SIZE:
        try:
            os.remove(download_result['file_path'])
        except:
            pass
        await query.message.edit_text(
            f"❌ حجم فایل ({file_size_mb:.1f}MB) بیش از حد مجاز ({MAX_FILE_SIZE}MB) است.\n"
            "لطفاً کیفیت پایین‌تری انتخاب کنید."
        )
        return
    
    # ارسال فایل با timeout افزایش یافته
    try:
        actual_quality = download_result.get('actual_quality', quality)
        quality_display = quality_names.get(actual_quality, actual_quality)
        
        await query.message.edit_text(f"📤 در حال آپلود فایل ({file_size_mb:.1f}MB) با کیفیت {quality_display}...")
        
        if quality == 'audio':
            await query.message.reply_audio(
                audio=open(download_result['file_path'], 'rb'),
                caption=f"🎵 {download_result['title'][:60]}",
                title=download_result['title'][:30],
                read_timeout=UPLOAD_TIMEOUT,
                write_timeout=UPLOAD_TIMEOUT,
                connect_timeout=UPLOAD_TIMEOUT,
                pool_timeout=UPLOAD_TIMEOUT
            )
        else:
            await query.message.reply_video(
                video=open(download_result['file_path'], 'rb'),
                caption=f"🎬 {download_result['title'][:60]}",
                supports_streaming=True,
                read_timeout=UPLOAD_TIMEOUT,
                write_timeout=UPLOAD_TIMEOUT,
                connect_timeout=UPLOAD_TIMEOUT,
                pool_timeout=UPLOAD_TIMEOUT
            )
        
        success_message = f"✅ دانلود با موفقیت انجام شد!\n📁 حجم فایل: {file_size_mb:.1f}MB"
        if actual_quality != quality:
            success_message += f"\n🎯 کیفیت واقعی: {quality_display} (بهترین کیفیت موجود)"
        
        await query.message.edit_text(success_message)
        
    except asyncio.TimeoutError:
        await query.message.edit_text("⏰ زمان آپلود به پایان رسید. لطفاً کیفیت پایین‌تری انتخاب کنید.")
    except Exception as e:
        logger.error(f"Error sending file: {str(e)}")
        await query.message.edit_text("❌ خطا در ارسال فایل. لطفاً دوباره تلاش کنید.")
    
    # حذف فایل موقت
    try:
        if os.path.exists(download_result['file_path']):
            os.remove(download_result['file_path'])
    except Exception as e:
        logger.error(f"Error deleting temp file: {str(e)}")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت خطاها"""
    logger.error(f"Error: {context.error}")
    try:
        if update and update.effective_message:
            await update.effective_message.reply_text("❌ خطایی رخ داد. لطفاً دوباره تلاش کنید.")
    except:
        pass

async def shutdown(signal, loop):
    """خاموش کردن برنامه"""
    logger.info(f"Received exit signal {signal.name}...")
    
    global update_task, bot_application
    
    # توقف بروزرسانی پس‌زمینه
    if update_task:
        update_task.cancel()
        try:
            await update_task
        except asyncio.CancelledError:
            pass
    
    # توقف بات
    if bot_application:
        await bot_application.stop()
        await bot_application.shutdown()
    
    # توقف لوپ
    loop.stop()
    logger.info("Bot shutdown completed.")

async def initialize_bot(application):
    """مقداردهی اولیه بات"""
    global update_task
    
    try:
        # بروزرسانی اولیه نام و بیو
        await update_bot_info_manually(application)
        logger.info("Initial bot info set successfully")
        
        # شروع بروزرسانی پس‌زمینه
        update_task = asyncio.create_task(background_updater(application))
        logger.info("Background updater started")
    except Exception as e:
        logger.error(f"Error initializing bot: {e}")

def main():
    """تابع اصلی"""
    global bot_application
    
    try:
        # تنظیم signal handlers برای خاموش کردن مناسب
        loop = asyncio.get_event_loop()
        signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)
        for s in signals:
            loop.add_signal_handler(
                s, lambda s=s: asyncio.create_task(shutdown(s, loop))
            )
        
        application = Application.builder().token(BOT_TOKEN).build()
        bot_application = application
        
        # اضافه کردن هندلرها
        application.add_handler(CommandHandler("start", start))
        application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, 
            handle_youtube_url
        ))
        application.add_handler(CallbackQueryHandler(handle_quality_selection))
        application.add_error_handler(error_handler)
        
        print("🤖 ربات YouTube Downloader در حال اجرا است...")
        print(f"📍 حداکثر حجم مجاز: {MAX_FILE_SIZE}MB")
        print("📍 سیستم مدیریت خودکار فرمت‌ها فعال است")
        print("📍 سیستم ساعت زنده و شمارش معکوس فعال است")
        print("📍 برای متوقف کردن: Ctrl+C")
        print("📍 لاگ‌ها در فایل bot.log ذخیره می‌شوند")
        
        # راه‌اندازی بات و شروع بروزرسانی
        loop.create_task(initialize_bot(application))
        
        application.run_polling()
        
    except Exception as e:
        logger.error(f"Fatal error: {e}")
    finally:
        logger.info("Bot stopped")

if __name__ == "__main__":
    main()
