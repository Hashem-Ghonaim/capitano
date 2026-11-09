# دليل نظام النسخ الاحتياطي السحابي التلقائي (Automated Cloud Backup)
### نظام Abo-Eyad ERP / CRM

نظام نسخ احتياطي يومي سحابي متكامل (Cloud-to-Cloud)، يعمل تلقائياً وبشكل مستقل بدون الحاجة لتشغيل أي جهاز كمبيوتر، مع إمكانية التشغيل والاسترجاع اليدوي بنقرة واحدة.

---

## 🏗️ مكونات النظام (Architecture)

1. **محرك النسخ الاحتياطي (`backend/backup_service.py`):**
   - **انعكاس كامل لقاعدة البيانات (SQLAlchemy Reflection):** قراءة كل الجداول وسحب كافة السجلات (أكثر من 99,700 سجل) وترحيلها إلى قاعدة بيانات SQLite محلية ومستقلة (`erp_crm.db`).
   - **مزامنة الصور التزايدية (Incremental Sync):** فحص الصور المرفوعة للمنتجات والقصص وسحبها بالتوازي عبر خيوط معالجة متعددة (`ThreadPoolExecutor`) مع حفظها في كاش محلي (`backups/cache/images/`) لعدم تحميلها مجدداً.
   - **ضغط وتجميع الأرشيف:** تجميع الداتا بيز (`erp_crm.db`) ومجلد الصور ومستند الفحص (`manifest.json`) وضغطهم في ملف ZIP مؤرخ: `backup_YYYY-MM-DD_HH-MM-SS_full.zip`.
   - **سياسة الحفظ (Retention Policy):** حذف النسخ الأقدم من 30 يوماً تلقائياً للحفاظ على المساحة.

2. **التكامل مع التليجرام (`run_daily_backup.py`):**
   - إرسال إشعار فوري بعد كل عملية بنجاح أو فشل عبر **Telegram Bot API**.
   - إرفاق ملف الـ ZIP مباشرة كـ Document في الشات.
   - إذا كان حجم الأرشيف الكامل أكبر من 50 ميجا (بسبب جودة صور المنتجات العالية)، يقوم النظام بإرفاق ملف قاعدة البيانات المضغوط (`_db.zip` بحجم ~2 ميجا) مباشرة عبر التليجرام مع تنبيه بأن الأرشيف الكامل متوفر في GitHub Artifacts.

3. **الأتمتة السحابية (GitHub Actions Workflow):**
   - مسار الملف: `.github/workflows/daily_backup.yml`.
   - يعمل يومياً مجدولاً بتوقيت القاهرة في الساعة **03:00 ص** (`cron: '0 1 * * *'`).
   - يدعم التشغيل اليدوي بنقرة زر (`workflow_dispatch`).
   - يحفظ ملف النسخة كـ **GitHub Artifact** لمدة **14 يوماً**.

4. **التشغيل والاسترجاع المحلي (Manual & Disaster Recovery):**
   - **ملف تشغيل فوري (`run_backup.bat`):** للمدير لأخذ نسخة فورية بنقرة واحدة من اللابتوب.
   - **سكريبت الاسترجاع للكوارث (`restore_from_backup.py`):** لفك أي ملف ZIP وإعادة كتابة قاعدة البيانات والصور تلقائياً.

---

## 🚀 كيفية الاستخدام والتشغيل

### 1. تشغيل نسخة احتياطية فورية من اللابتوب
- انقر نقراً مزدوجاً على ملف:
  ```bash
  run_backup.bat
  ```
- أو عبر التيرمينال:
  ```bash
  python run_daily_backup.py
  ```

### 2. اختبار اتصال بوت التليجرام
لتجربة البوت والتأكد من صحة التوكن والـ Chat ID دون تشغيل نسخ احتياطي كامل:
```bash
python run_daily_backup.py --test-telegram
```

### 3. استرجاع البيانات عند الطوارئ (Disaster Recovery)
- **استرجاع إلى قاعدة بيانات SQLite المحلية:**
  ```bash
  python restore_from_backup.py --target sqlite
  ```
- **استرجاع إلى قاعدة بيانات PostgreSQL (Supabase / Production):**
  ```bash
  python restore_from_backup.py --target postgres
  ```
- **استرجاع ملف ZIP محدد بدون أسئلة تأكيدية:**
  ```bash
  python restore_from_backup.py backups/backup_2026-11-09_19-38-40_full.zip --yes
  ```

---

## 🔐 إعداد المفاتيح السرية على GitHub (Cloud-to-Cloud)

لكي يعمل الـ GitHub Workflow يومياً تلقائياً، أضف المفاتيح التالية في مستودع GitHub الخاص بك تحت:
`Settings` ➔ `Secrets and variables` ➔ `Actions` ➔ `New repository secret`

| اسم المتغير (Secret Name) | الوصف |
| :--- | :--- |
| `DATABASE_URL` | رابط اتصال قاعدة البيانات (PostgreSQL / Supabase) |
| `TELEGRAM_BOT_TOKEN` | توكن البوت من `@BotFather` |
| `TELEGRAM_CHAT_ID` | معرف المحادثة أو القناة المستلمة للنسخ |
| `CLOUDINARY_CLOUD_NAME` | اسم الحساب في كلاوديناري |
| `CLOUDINARY_API_KEY` | مفتاح API |
| `CLOUDINARY_API_SECRET` | المفتاح السري لـ API |
