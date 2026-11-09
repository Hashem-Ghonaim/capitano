"""
Abo-Eyad ERP/CRM - Daily Automated Backup Runner & Telegram Bot Notification
===========================================================================
- Runs the full backup service (SQLAlchemy reflection -> SQLite + Incremental images sync + ZIP).
- Sends instant notifications (success or failure) to Telegram Bot API.
- Attaches the backup ZIP file as a document if size <= 49.5 MB.
- If full ZIP exceeds 50MB (due to hundreds of high-res images), creates and sends a compact database-only ZIP (~2.5 MB)
  directly to Telegram so the user always receives a daily restorable database document in chat, while the full archive
  is securely preserved in GitHub Artifacts.
- Designed to run seamlessly in GitHub Actions (Cloud-to-Cloud) or locally.
"""

import os
import sys
import time
import zipfile
import logging
from datetime import datetime
import requests
from dotenv import load_dotenv

from backend.backup_service import BackupService

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("DailyBackupRunner")


def send_telegram_message(bot_token, chat_id, text_message):
    """Sends a text message via Telegram Bot API"""
    if not bot_token or not chat_id:
        logger.warning("Telegram Bot Token or Chat ID not provided. Skipping message.")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text_message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        resp = requests.post(url, json=payload, timeout=20)
        if resp.status_code == 200:
            logger.info("✅ Telegram notification message sent successfully.")
            return True
        else:
            logger.error(f"❌ Telegram sendMessage failed with HTTP {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        logger.error(f"❌ Telegram connection error: {e}")
        return False


def send_telegram_document(bot_token, chat_id, file_path, caption=""):
    """Sends a file document via Telegram Bot API"""
    if not bot_token or not chat_id:
        logger.warning("Telegram Bot Token or Chat ID not provided. Skipping document upload.")
        return False

    if not os.path.exists(file_path):
        logger.error(f"File not found: {file_path}")
        return False

    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    # Telegram Bot API file upload limit is 50MB
    if file_size_mb > 49.5:
        logger.warning(f"File size ({file_size_mb:.2f} MB) exceeds Telegram bot 50MB limit.")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    logger.info(f"Uploading {os.path.basename(file_path)} ({file_size_mb:.2f} MB) to Telegram...")
    try:
        with open(file_path, "rb") as doc_file:
            files = {
                "document": (os.path.basename(file_path), doc_file, "application/zip")
            }
            data = {
                "chat_id": chat_id,
                "caption": caption[:1024],  # Telegram max caption length
                "parse_mode": "HTML"
            }
            resp = requests.post(url, data=data, files=files, timeout=180)
            if resp.status_code == 200:
                logger.info("✅ Telegram document uploaded successfully!")
                return True
            else:
                logger.error(f"❌ Telegram sendDocument failed with HTTP {resp.status_code}: {resp.text}")
                return False
    except Exception as e:
        logger.error(f"❌ Error uploading file to Telegram: {e}")
        return False


def run_backup():
    load_dotenv()

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    logger.info("==================================================")
    logger.info("   Starting Automated Daily Backup Pipeline       ")
    logger.info("==================================================")

    backup_service = BackupService()
    result = backup_service.create_full_backup()

    now_cairo = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")

    if result.get("success"):
        manifest = result.get("manifest", {})
        db_info = manifest.get("database", {})
        img_info = manifest.get("images", {})
        zip_size_mb = result.get("zip_size_mb", 0)
        zip_path = result.get("zip_path")
        zip_name = result.get("zip_filename")
        elapsed = result.get("elapsed_seconds", 0)

        deleted_backups = result.get("deleted_old_backups", [])
        retention_note = ""
        if deleted_backups:
            retention_note = f"\n🧹 <b>تم تنظيف نسخ قديمة (&gt;30 يوم):</b> {len(deleted_backups)} ملف"

        success_message = (
            f"📦 <b>تقرير النسخ الاحتياطي اليومي - Daily Cloud Backup</b>\n\n"
            f"✅ <b>الحالة:</b> اكتملت العملية بنجاح 100%\n"
            f"🕒 <b>التوقيت:</b> {now_cairo} (بتوقيت القاهرة)\n"
            f"🗄️ <b>عدد الجداول:</b> {db_info.get('tables_count', 0)} جدول\n"
            f"📊 <b>إجمالي السجلات:</b> {db_info.get('total_records', 0):,} سجل\n"
            f"🖼️ <b>إحصائيات الصور:</b>\n"
            f"   • الإجمالي المرجعي: {img_info.get('total_referenced', 0):,} صورة\n"
            f"   • في الكاش مسبقاً: {img_info.get('already_cached', 0):,} صورة\n"
            f"   • تم تحميلها حديثاً: {img_info.get('newly_downloaded', 0):,} صورة\n"
            f"   • الإجمالي المحفوظ بالأرشيف: {img_info.get('total_cached_files', 0):,} صورة\n"
            f"💾 <b>حجم ملف الأرشيف الكامل (ZIP):</b> {zip_size_mb:.2f} MB\n"
            f"⏱️ <b>مدة التنفيذ:</b> {elapsed} ثانية"
            f"{retention_note}\n\n"
            f"🛡️ <i>تم إنشاء نسخة احتياطية مستقلة SQLite وتحديث الكاش بنجاح.</i>"
        )

        # 1. Send telegram text summary
        send_telegram_message(bot_token, chat_id, success_message)

        # 2. Attach document
        if zip_size_mb <= 49.5:
            caption = f"🗃️ <b>نسخة احتياطية كاملة:</b> <code>{zip_name}</code> ({zip_size_mb:.2f} MB)"
            send_telegram_document(bot_token, chat_id, zip_path, caption=caption)
        else:
            # When full zip exceeds 50MB, package a compact DB+manifest ZIP so user still receives the database in Telegram
            compact_zip_name = zip_name.replace("_full.zip", "_db.zip")
            compact_zip_path = os.path.join(backup_service.backups_dir, compact_zip_name)
            try:
                # Extract erp_crm.db and manifest.json from full zip into compact zip
                with zipfile.ZipFile(zip_path, 'r') as full_z:
                    with zipfile.ZipFile(compact_zip_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as db_z:
                        if "erp_crm.db" in full_z.namelist():
                            db_z.writestr("erp_crm.db", full_z.read("erp_crm.db"))
                        if "manifest.json" in full_z.namelist():
                            db_z.writestr("manifest.json", full_z.read("manifest.json"))

                compact_size_mb = os.path.getsize(compact_zip_path) / (1024 * 1024)
                caption = (
                    f"🗄️ <b>قاعدة البيانات المستقلة (SQLite):</b> <code>{compact_zip_name}</code> ({compact_size_mb:.2f} MB)\n"
                    f"⚠️ <i>ملاحظة: حجم الأرشيف الكامل شامل الصور ({zip_size_mb:.2f} MB) يتجاوز حد التليجرام (50 MB)، ومحفوظ كاملاً كـ Artifact في GitHub Actions.</i>"
                )
                send_telegram_document(bot_token, chat_id, compact_zip_path, caption=caption)
            except Exception as e:
                logger.error(f"Failed to create compact db zip: {e}")
                size_notice = (
                    f"⚠️ <b>تنبيه حجم الملف:</b>\n"
                    f"حجم النسخة الاحتياطية ({zip_size_mb:.2f} MB) يتجاوز الحد الأقصى المسموح لبوت التليجرام (50 MB).\n"
                    f"الملف محفوظ ومتاح للتنزيل بأمان داخل <b>GitHub Actions Artifacts</b> لمدة 14 يوماً."
                )
                send_telegram_message(bot_token, chat_id, size_notice)

        logger.info("Daily backup finished with SUCCESS.")
        return 0

    else:
        # Failure handling
        error_msg = result.get("error", "Unknown error")
        elapsed = result.get("elapsed_seconds", 0)

        failure_message = (
            f"🚨 <b>تحذير: فشلت عملية النسخ الاحتياطي اليومي!</b>\n\n"
            f"❌ <b>الخطأ:</b> <code>{error_msg}</code>\n"
            f"🕒 <b>التوقيت:</b> {now_cairo}\n"
            f"⏱️ <b>المدة قبل الفشل:</b> {elapsed} ثانية\n\n"
            f"⚠️ <i>يرجى فحص السجلات أو الاتصال بمسؤول النظام فوراً.</i>"
        )
        send_telegram_message(bot_token, chat_id, failure_message)
        logger.error(f"Daily backup finished with FAILURE: {error_msg}")
        return 1


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Abo-Eyad ERP Daily Backup & Telegram Integration")
    parser.add_argument("--test-telegram", action="store_true", help="Send a test ping message to Telegram without backing up")
    args = parser.parse_args()

    if args.test_telegram:
        load_dotenv()
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        chat = os.environ.get("TELEGRAM_CHAT_ID")
        now_str = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
        print(f"Testing Telegram connection with token: {'SET' if token else 'NOT SET'}, chat_id: {'SET' if chat else 'NOT SET'}")
        if not token or not chat:
            print("❌ Error: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in .env or environment.")
            sys.exit(1)
        test_msg = (
            f"🔔 <b>تجربة اتصال بوت التليجرام - Abo-Eyad ERP</b>\n\n"
            f"✅ تم الاتصال بنجاح مع سيرفرات التليجرام!\n"
            f"🕒 التوقيت: {now_str}\n"
            f"البوت جاهز لإرسال النسخ الاحتياطية اليومية تلقائياً."
        )
        ok = send_telegram_message(token, chat, test_msg)
        sys.exit(0 if ok else 1)

    exit_code = run_backup()
    sys.exit(exit_code)
