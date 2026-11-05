# هژیر وی‌پی‌ان | Hazhir VPN Bot

ربات تلگرام فارسی برای فروش اشتراک VPN با پنل **3x-ui** — پلن، کیف پول، پرداخت کارت‌به‌کارت، رفرال، اکانت تست، هشدار انقضا و اتمام حجم.

A Persian Telegram bot for selling VPN subscriptions via a **3x-ui** panel — plans, wallet, card-to-card payments, referrals, trial accounts, expiry & volume warnings.

> این پروژه از صفر با Python نوشته شده (clean-room) و تحت لایسنس **AGPL-3.0** منتشر می‌شود. هیچ کدی از پروژه‌ی مرجع کپی نشده است.
> Built from scratch in Python (clean-room) and released under **AGPL-3.0**. No code was copied from the reference project.

> ⚠️ **هرگز توکن ربات، آیدی عددی تلگرام، توکن پنل یا شماره کارت را در کد یا گیت‌هاب ننویسید.** همه‌ی این‌ها فقط در متغیر محیطی قرار می‌گیرند (فایل `.env` روی سرور یا تب Environment در Botkeep). اگر توکنی به‌اشتباه عمومی شد، فوراً باطلش کنید: توکن ربات را در BotFather با `/revoke`، و توکن پنل را از Settings ← API در پنل حذف و تازه بسازید.
> ⚠️ **Never put your bot token, numeric Telegram ID, panel token or card number in code or on GitHub.** They belong only in environment variables (a `.env` file on your server, or the Environment tab on Botkeep). If a token ever leaks, revoke it immediately: bot token via `/revoke` in BotFather, panel token by deleting it in the panel's Settings ← API and creating a new one.

- [فارسی](#فارسی)
- [English](#english)

---

## فارسی

### معرفی

هژیر وی‌پی‌ان یک ربات فروش VPN است که به پنل **3x-ui** روی سرور شما وصل می‌شود. مشتری پلن انتخاب می‌کند، پرداخت می‌کند (کارت‌به‌کارت با تأیید مدیر، یا از کیف پول)، و ربات به‌صورت خودکار در پنل سرویس می‌سازد و لینک اشتراک + QR تحویل می‌دهد. همه‌ی تنظیمات (پلن‌ها، کارت‌ها، آدرس پنل، متن‌ها، آموزش‌ها) از داخل خود ربات و بدون دست‌کاری کد قابل تغییر است.

### امکانات

**برای مشتری:**
- 🛒 **خرید سرویس:** انتخاب پلن ← پرداخت با کیف پول، کارت‌به‌کارت (ارسال فیش ← تأیید مدیر) یا ارز دیجیتال (اختیاری، پیش‌فرض خاموش) ← تحویل خودکار لینک اشتراک + QR
- 📦 **سرویس‌های من:** حجم باقی‌مانده، روزهای باقی‌مانده و وضعیت زنده از پنل + دکمه تمدید و دریافت دوباره لینک
- 👜 **کیف پول:** شارژ با کارت‌به‌کارت (فیش ← تأیید مدیر)؛ خرید و تمدید با یک کلیک از موجودی، بدون انتظار تأیید
- 🎁 **اکانت تست:** یک بار برای هر کاربر، بدون نیاز به تأیید مدیر (مدت و حجم از تنظیمات)
- 👥 **دعوت دوستان:** لینک اختصاصی (`t.me/<bot>?start=ref_<id>`)؛ با اولین خرید هر دعوت‌شده، یک سرویس هدیه به‌صورت خودکار برای دعوت‌کننده ساخته می‌شود
- 📚 **آموزش اتصال:** آموزش اندروید / آیفون / ویندوز + لینک دانلود برنامه‌ها (قابل ویرایش توسط مدیر)
- 💬 **پشتیبانی:** پیام مشتری ← فوروارد به مدیر ← جواب مدیر به مشتری

**برای مدیر (ورود با دکمه 🛠 مدیریت در منوی پایین ربات — نه با دستور):**
- منوی گروه‌بندی‌شده با زیرمنو و دکمه بازگشت؛ حداکثر ۲ دکمه در هر ردیف
- 📊 گزارش‌ها (روزانه / فروش / کاربران)
- 💳 پرداخت‌های در انتظار (خرید، تمدید، شارژ کیف پول) با شمارنده زنده؛ تأیید/رد با دکمه؛ تشخیص فیش تکراری با هشدار به مدیر
- 🖥 مدیریت پنل (آدرس، توکن، لینک ساب، تست اتصال) — توکن فقط ۴ رقم آخر نمایش داده می‌شود
- 📡 مدیریت اینباندها (افزودن/حذف)
- 📦 مدیریت پلن‌ها (ساخت/ویرایش/فعال‌غیرفعال/حذف)
- 💳 مدیریت کارت‌ها
- 👥 کاربران + فعال/غیرفعال/حذف سرویس در پنل + تغییر موجودی کیف پول هر کاربر
- 📚 آموزش‌ها (افزودن/ویرایش/حذف/فعال‌غیرفعال + عکس اختیاری)
- 📢 پیام همگانی (پیش‌نمایش ← تأیید ← ارسال به همه با گزارش موفق/ناموفق)
- ⚙️ تنظیمات گروه‌بندی‌شده: متن‌ها (خوش‌آمد/پشتیبانی/راهنمای خرید) · اکانت تست · رفرال · هشدارها · لینک ساب · لینک دانلود برنامه‌ها · ارز دیجیتال

**جاب‌های خودکار:**
- **هر ساعت:** هشدار انقضا + هشدار اتمام حجم (پیش‌فرض وقتی ۸۰٪ حجم مصرف شد، آستانه از تنظیمات قابل تغییر است) + غیرفعال‌سازی سرویس‌های منقضی در پنل. اگر ارسال هشدار ناموفق باشد، ساعت بعد دوباره تلاش می‌شود.
- **هر ۳ دقیقه:** بررسی پرداخت‌های ارز دیجیتال (فقط وقتی فعال باشد)
- **روزانه ۰۹:۰۰ به وقت تهران:** گزارش فروش به مدیرها

---

### راه‌اندازی قدم‌به‌قدم (۰ تا ۱۰۰)

#### قدم ۰ — چیزهایی که لازم داری

- یک **سرور مجازی (VPS) با Ubuntu** برای پنل 3x-ui (پنل و ربات می‌توانند روی یک سرور یا دو سرور جدا باشند)
- یک **حساب تلگرام** (برای ساخت ربات و مدیریت آن)
- یک جا برای اجرای ربات: **Botkeep** (رایگان، بدون سرور) یا همان VPS یا هر سرور لینوکسی
- یک **کارت بانکی** برای دریافت پرداخت کارت‌به‌کارت مشتری‌ها

#### قدم ۱ — ساخت ربات در BotFather و گرفتن توکن

1. در تلگرام به **[@BotFather](https://t.me/BotFather)** برو و دستور `/newbot` را بفرست.
2. یک **نام** برای ربات انتخاب کن (مثلاً «هژیر وی‌پی‌ان»).
3. یک **یوزرنیم** بده که به `bot` ختم شود (مثلاً `hazhirvpnbot`).
4. BotFather یک **توکن** می‌دهد شبیه این:
   `123456789:AAEhBOweik6ad9r_QXMENQjcrGbqCrK7gI`
   این توکن «رمز عبور» ربات توست — هرگز آن را برای کسی نفرست و در هیچ فایل عمومی (مثل گیت‌هاب) ننویس. اگر لو رفت، در BotFather با `/revoke` باطلش کن و توکن تازه بگیر.
5. توکن را نگه دار؛ در قدم ۴ یا ۵ آن را در متغیر محیطی `BOT_TOKEN` می‌گذاری.

#### قدم ۲ — پیدا کردن آیدی عددی تلگرامت

1. در تلگرام به **[@userinfobot](https://t.me/userinfobot)** برو و `/start` را بزن.
2. عددی که با «Your ID» نشان می‌دهد (مثلاً `123456789`) آیدی عددی توست — همین مقدار `ADMIN_IDS` است.
3. اگر چند مدیر داری، آیدی‌ها را با کاما جدا کن: `123456789,987654321`

> آیدی عددی را هم در کد عمومی ننویس؛ فقط در متغیر محیطی.

#### قدم ۳ — آماده‌سازی پنل 3x-ui

1. **نصب پنل روی VPS** (Ubuntu) — با اسکریپت رسمی نصب:
   ```bash
   bash <(curl -Ls https://raw.githubusercontent.com/MHSanaei/3x-ui/master/install.sh)
   ```
   بعد از نصب، پنل آدرس، پورت، نام کاربری و رمز ورود را نشان می‌دهد — آن‌ها را نگه دار.
2. **ساخت اینباند:** وارد پنل شو، به Inbounds برو و یک اینباند بساز (مثلاً VLESS با پورت دلخواه). **آیدی عددی** اینباند را از لیست بردار (مثلاً `1`). اگر چند اینباند داری، آیدی‌ها را با کاما بنویس: `1,9,11` — همین مقدار `INBOUNDS` است.
3. **توکن API:** در پنل به **Settings ← API** برو و یک توکن با دسترسی **admin** بساز. توکن را کپی کن — فقط همین یک بار کامل نشان داده می‌شود. این مقدار `PANEL_TOKEN` است.
4. **لینک اشتراک:** سرویس **Subscription** را در پنل فعال کن و مسیر لینک ساب را بردار؛ مثلاً اگر لینک ساب تو `https://host:2096/hard/` است، همین مقدار `SUB_BASE` می‌شود.
5. **آدرس پنل (`PANEL_URL`):** مثلاً `https://host:port/webBasePath` — اگر مسیر پایه نداری، فقط `https://host:port`.

> ربات با مسیر `PANEL_URL + /panel/api/` به پنل وصل می‌شود و با `Authorization: Bearer <API_TOKEN>` احراز هویت می‌کند. اگر توکن اشتباه باشد پنل `401` و اگر توکن نفرستید `404` برمی‌گرداند (رفتار عمدی پنل برای مخفی ماندن).

#### قدم ۴ — دیپلوی روی Botkeep (بدون سرور، رایگان)

1. در **[botkeep.cloud](https://botkeep.cloud)** حساب بساز و وارد شو.
2. یک بات جدید بساز: نوع **Python 3.13** را انتخاب کن.
3. کد ربات را بگیر: از صفحه‌ی گیت‌هاب پروژه، دکمه‌ی **Code ← Download ZIP** را بزن و فایل ZIP را دانلود کن. (یا همین ریپو را کلون کن و خودت ZIP بگیر.)
4. در پنل Botkeep، در تب **Files** فایل ZIP را آپلود و **Unarchive** کن. مطمئن شو فایل ورودی **`main.py`** در ریشه باشد.
5. در تب **Environment** سکرت‌ها را ست کن — هر سطر یک متغیر (مقدارها را با اطلاعات خودت جایگزین کن):
   ```
   BOT_TOKEN=123456789:AAE...
   ADMIN_IDS=123456789
   PANEL_URL=https://your-panel-host:port/webBasePath
   PANEL_TOKEN=paste-your-panel-api-token-here
   SUB_BASE=https://your-panel-host:2096/hard/
   INBOUNDS=1
   CARD_NUMBER=6037991122334455
   CARD_HOLDER=نام صاحب کارت
   ```
6. ⚠️ **مهم:** مقادیر Environment در Botkeep فقط به‌صورت فایل `.env` داخل کانتینر تحویل داده می‌شوند و خودکار وارد `os.environ` نمی‌شوند. پس **Start command** باید این باشد:
   ```
   set -a; . ./.env; set +a; exec python main.py
   ```
   (بدون این، ربات با خطای `Missing required environment variable` کرش می‌کند.)
7. **Redeploy** کن و در **Console** دنبال لاگ شروع باش. اگر خطایی نبود، ربات بالاست.

#### قدم ۵ — دیپلوی روی سرور مجازی (VPS با Ubuntu)

1. **نصب Python و git** (روی Ubuntu 24.04 پایتون ۳٫۱۲ از پیش نصب است؛ روی 22.04 اول پایتون ۳٫۱۲ را از PPA deadsnakes نصب کن):
   ```bash
   sudo apt update
   sudo apt install -y python3 python3-venv git
   python3 --version   # باید 3.11 یا جدیدتر باشد
   ```
2. **کلون کردن کد:**
   ```bash
   git clone https://github.com/hazhirplus/hazhir_bot.git
   cd hazhir_bot
   ```
3. **ساخت محیط مجازی و نصب وابستگی‌ها:**
   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```
4. **ساخت فایل `.env`** با اطلاعات خودت (این فایل **هرگز** به گیت‌هاب نمی‌رود — در `.gitignore` است):
   ```bash
   nano .env
   ```
   ```env
   BOT_TOKEN=123456789:AAE...
   ADMIN_IDS=123456789
   PANEL_URL=https://your-panel-host:port/webBasePath
   PANEL_TOKEN=paste-your-panel-api-token-here
   SUB_BASE=https://your-panel-host:2096/hard/
   INBOUNDS=1
   CARD_NUMBER=6037991122334455
   CARD_HOLDER=نام صاحب کارت
   ```
   با `Ctrl+O` ذخیره و با `Ctrl+X` خارج شو.
5. **تست اجرای دستی** (برای اینکه مطمئن شوی همه‌چیز درست است):
   ```bash
   set -a; . ./.env; set +a; .venv/bin/python main.py
   ```
   اگر خطایی نبود و ربات به تلگرام وصل شد، با `Ctrl+C` خاموشش کن و برو قدم بعد.
6. **سرویس دائمی با systemd** تا ربات همیشه روشن بماند و با ری‌استارت سرور دوباره بالا بیاید:
   ```bash
   sudo nano /etc/systemd/system/hazhir_bot.service
   ```
   ```ini
   [Unit]
   Description=Hazhir VPN Bot
   After=network.target

   [Service]
   Type=simple
   WorkingDirectory=/opt/hazhir_bot
   EnvironmentFile=/opt/hazhir_bot/.env
   ExecStart=/opt/hazhir_bot/.venv/bin/python main.py
   Restart=always

   [Install]
   WantedBy=multi-user.target
   ```
   > اگر کد را در مسیر دیگری کلون کردی (مثلاً `/root/hazhir_bot`)، هر سه مسیر `WorkingDirectory`، `EnvironmentFile` و `ExecStart` را به همان مسیر عوض کن.
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable hazhir_bot
   sudo systemctl start hazhir_bot
   ```
7. **دیدن لاگ‌ها:**
   ```bash
   sudo journalctl -u hazhir_bot -f
   ```

> ربات با **polling** کار می‌کند (بدون وبهوک) — پس **نیازی به باز کردن پورت، دامنه یا گواهی SSL برای خود ربات نداری.** فقط پنل 3x-ui باید از اینترنت در دسترس ربات باشد.

#### قدم ۶ — دیپلوی روی هر سرور دیگری

هر سرور لینوکسی (یا حتی مک/ویندوز) که **Python 3.11+** داشته باشد کافی است:
1. کد را کلون کن، `venv` بساز و `pip install -r requirements.txt` را بزن (مثل قدم ۵).
2. فایل `.env` را با همان متغیرهای قدم ۵ بساز.
3. اجرا کن:
   ```bash
   set -a; . ./.env; set +a; .venv/bin/python main.py
   ```
4. برای اجرای دائمی، از **systemd** (قدم ۵)، یا **screen/tmux** استفاده کن:
   ```bash
   tmux new -s hazhir
   set -a; . ./.env; set +a; .venv/bin/python main.py
   # با Ctrl+B بعد D از سشن خارج شو؛ ربات روشن می‌ماند
   ```

#### قدم ۷ — اولین ورود و بررسی سلامت

1. در تلگرام رباتت را `/start` بزن — منوی مشتری را می‌بینی.
2. دکمه‌ی **🛠 مدیریت** را در منوی پایین بزن — پنل مدیریت باز می‌شود.
3. به «🖥 پنل‌ها» ← «🔌 تست اتصال» برو — باید ✅ بدهد. اگر ❌ داد، جدول عیب‌یابی پایین را ببین.
4. در اولین اجرا ۴ پلن پیش‌فرض سید می‌شود (۱۰ / ۳۰ / ۵۰ / ۸۰ گیگ، ۳۰ روزه) — از «📦 مدیریت پلن‌ها» قیمت و حجمشان را به قیمت خودت عوض کن.
5. شماره کارتت را در «💳 مدیریت کارت‌ها» چک کن.
6. یک خرید آزمایشی با یک اکانت تلگرام دیگر انجام بده و مطمئن شو سرویس در پنل ساخته و لینک ساب تحویل داده می‌شود.

#### هر سکرت را از کجا بیاوری و کجا بذاری

| متغیر | از کجا به دستش می‌آوری؟ | کجا می‌گذاری؟ |
|---|---|---|
| `BOT_TOKEN` | قدم ۱ — BotFather (`/newbot`) | `.env` یا تب Environment در Botkeep |
| `ADMIN_IDS` | قدم ۲ — @userinfobot | `.env` یا تب Environment در Botkeep |
| `PANEL_URL` | قدم ۳ — آدرس پنلی که نصب کردی | `.env` یا تب Environment در Botkeep |
| `PANEL_TOKEN` | قدم ۳ — پنل، Settings ← API | `.env` یا تب Environment در Botkeep |
| `SUB_BASE` | قدم ۳ — لینک ساب پنل | `.env` یا تب Environment در Botkeep |
| `INBOUNDS` | قدم ۳ — آیدی اینباندها از لیست پنل | `.env` یا تب Environment در Botkeep |
| `CARD_NUMBER` / `CARD_HOLDER` | شماره و نام صاحب کارت بانکی خودت | `.env` یا تب Environment در Botkeep |

> **قانون طلایی:** سکرت‌ها فقط در `.env` یا Environment می‌روند. **هرگز** در کد، در گیت، در چت عمومی یا در فایل README نوشته نمی‌شوند.

#### عیب‌یابی

| مشکل | علت احتمالی | راه‌حل |
|---|---|---|
| `Missing required environment variable` | یک متغیر محیطی ست نشده | همه‌ی متغیرهای ضروری را در `.env` یا Environment چک کن؛ در Botkeep استارت‌کامند باید `.env` را سورس کند (قدم ۴) |
| تست اتصال پنل `401` می‌دهد | توکن API اشتباه است یا دسترسی admin ندارد | در پنل یک توکن تازه با دسترسی **admin** بساز و در `PANEL_TOKEN` بگذار |
| تست اتصال پنل `404` می‌دهد | آدرس پنل اشتباه است | `PANEL_URL` را چک کن — باید دقیقاً به صفحه‌ی ورود پنل برسد |
| ربات جواب نمی‌دهد | دو نسخه ربات با یک توکن در حال اجراست (تداخل polling) | نسخه‌ی قدیمی را خاموش کن؛ فقط **یک** اینستنس باید با هر توکن کار کند |
| `Conflict: terminated by other getUpdates request` | همان مشکل بالا | همان راه‌حل بالا |
| پرداخت کارت‌به‌کارت ثبت نمی‌شود | شماره کارت در تنظیمات خالی است | در پنل مدیریت، «💳 مدیریت کارت‌ها» را چک کن |
| لینک ساب کار نمی‌کند | `SUB_BASE` اشتباه است یا Subscription در پنل فعال نیست | `SUB_BASE` را با لینک ساب واقعی پنل مقایسه کن و Subscription را فعال کن |

### متغیرهای محیطی (مرجع کامل)

همه‌ی سکرت‌ها فقط از متغیر محیطی خوانده می‌شوند — **هرگز در کد یا دیتابیس نوشته نمی‌شوند.**

| نام | ضروری | توضیح |
|---|---|---|
| `BOT_TOKEN` | ✅ | توکن ربات از BotFather |
| `ADMIN_IDS` | ✅ | آیدی عددی مدیرها با کاما: `123456789,987654321` |
| `PANEL_URL` | 🌱 | آدرس پنل، مثل `https://host:port/webBasePath` |
| `PANEL_TOKEN` | 🌱 | توکن API پنل با دسترسی **admin** (از Settings ← API) |
| `SUB_BASE` | 🌱 | بیس لینک ساب، مثل `https://host:2096/hard/` |
| `INBOUNDS` | 🌱 | آیدی اینباندها با کاما، مثل `1,9,11` |
| `CARD_NUMBER` | 🌱 | شماره کارت پیش‌فرض برای پرداخت کارت‌به‌کارت |
| `CARD_HOLDER` | 🌱 | نام صاحب کارت |
| `EVM_ADDRESS` | — | آدرس عمومی EVM برای دریافت ارز دیجیتال (اختیاری؛ پیش‌فرض خالی است — کلید خصوصی هرگز) |
| `ETHERSCAN_API_KEY` | — | کلید رایگان Etherscan (از etherscan.io) برای راستی‌آزمایی پرداخت‌های ارز دیجیتال |
| `DB_PATH` | — | مسیر دیتابیس (پیش‌فرض `data/hozhir.db`) |

موارد 🌱 فقط در **اولین اجرا** برای مقداردهی اولیه استفاده می‌شوند؛ بعد از آن همه از داخل بخش مدیریت ربات قابل تغییرند.

### پرداخت ارز دیجیتال (اختیاری، پیش‌فرض خاموش)

ماژول `chainwatch.py` پرداخت **ETH و USDC** در شبکه‌های **Base ،Arbitrum و Optimism** را با تطبیق مقدار یکتا راستی‌آزمایی می‌کند (بک‌اند Etherscan با کلید رایگان، یا RPC عمومی بدون کلید). برای فعال‌کردن، در تنظیمات مدیر `crypto_enabled` را روشن کنید و `EVM_ADDRESS` و `ETHERSCAN_API_KEY` را ست کنید. وقتی خاموش است، هیچ کدی از این مسیر اجرا نمی‌شود.

### تست‌ها

```bash
BOT_TOKEN=dummy ADMIN_IDS=1 PANEL_URL=http://127.0.0.1:1 PANEL_TOKEN=dummy \
SUB_BASE=http://127.0.0.1:1/ INBOUNDS=1 CARD_NUMBER=1 CARD_HOLDER=x \
python -m pytest tests/ -q
```

تست‌ها فقط با دیتابیس موقت SQLite کار می‌کنند و به پنل یا تلگرام واقعی وصل نمی‌شوند. (۸۲ تست سبز، ۳ اسکیپ.)

### امنیت

- همه‌ی کوئری‌های دیتابیس پارامتری؛ هیچ `exec`/`eval`؛ اعتبارسنجی ورودی‌های عددی
- توکن پنل هرگز لاگ نمی‌شود؛ در نمایش فقط ۴ رقم آخر
- اتصال به پنل با `TLS verify=True`
- رسید فقط به صورت `file_id` تلگرام ذخیره می‌شود؛ فیش تکراری به مدیر هشدار داده می‌شود
- همه‌ی هندلرهای مدیریتی با دکوراتور `admin_only` محافظت شده‌اند
- ضد اسپم: محدودیت پیام (پیش‌فرض ۳۰ پیام در ۶۰ ثانیه برای کاربر عادی، ۱۲۰ برای مدیر) با یک هشدار مؤدبانه
- **هیچ سکرتی در این ریپو نیست:** توکن ربات، توکن پنل، آدرس پنل، شماره کارت و آیدی تلگرام همه فقط از متغیر محیطی خوانده می‌شوند و در کد وجود ندارند

### ساختار پروژه

| فایل | توضیح |
|---|---|
| `main.py` | نقطه ورود؛ ساخت اپلیکیشن، ثبت هندلرها و جاب‌ها |
| `config.py` | خواندن تنظیمات فقط از متغیر محیطی |
| `db.py` | SQLite (aiosqlite)؛ کاربران، فاکتورها، پلن‌ها، تنظیمات |
| `panel.py` | کلاینت API پنل 3x-ui (ساخت/حذف/ترافیک/لینک ساب) |
| `handlers_user.py` | فلوهای مشتری: خرید، کیف پول، سرویس‌ها، تست، رفرال |
| `handlers_admin.py` | پنل مدیریت + تنظیمات |
| `jobs.py` | جاب‌های ساعتی/روزانه (هشدار، گزارش) + بررسی کریپتو |
| `chainwatch.py` | راستی‌آزمایی پرداخت ارز دیجیتال روی زنجیره (اختیاری) |
| `throttle.py` | محدودیت نرخ پیام (ضد اسپم) |
| `keyboards.py` / `text.py` / `helpers.py` | منوها، متن‌ها و ابزارهای مشترک |

### لایسنس

AGPL-3.0 — فایل `LICENSE` را ببینید.

---

## English

### Overview

Hazhir VPN Bot is a Telegram bot that sells VPN subscriptions through your **3x-ui** panel. A customer picks a plan, pays (card-to-card approved by an admin, or from their wallet), and the bot automatically creates the service in the panel and delivers the subscription link + QR code. Every setting (plans, cards, panel address, texts, tutorials) can be changed from inside the bot, without touching code.

### Features

**For customers:**
- 🛒 **Buy a service:** pick a plan → pay with wallet, card-to-card (send receipt → admin approval), or crypto (optional, off by default) → automatic delivery of subscription link + QR
- 📦 **My services:** remaining volume, remaining days and live status from the panel + renew and re-fetch link buttons
- 👜 **Wallet:** top up with card-to-card (receipt → admin approval); one-click purchase and renewal from balance, no approval wait
- 🎁 **Trial account:** once per user, no admin approval needed (duration/volume from settings)
- 👥 **Referrals:** personal link (`t.me/<bot>?start=ref_<id>`); when an invitee makes their first purchase, a gift service is automatically created for the inviter
- 📚 **Connection tutorials:** Android / iPhone / Windows guides + app download links (editable by the admin)
- 💬 **Support:** customer message → forwarded to admin → admin reply back to customer

**For admins (via the 🛠 management button in the bot's bottom menu — never a command):**
- Grouped menus with submenus and a back button; max 2 buttons per row
- 📊 Reports (daily / sales / users)
- 💳 Pending payments (purchase, renewal, wallet top-up) with live counter; approve/reject with buttons; duplicate receipts trigger an admin warning
- 🖥 Panel management (address, token, sub-link, connection test) — token shown as last 4 chars only
- 📡 Inbound management (add/remove)
- 📦 Plan management (create/edit/enable-disable/delete)
- 💳 Card management
- 👥 Users + enable/disable/delete service in panel + adjust any user's wallet balance
- 📚 Tutorials (add/edit/delete/enable-disable + optional photo)
- 📢 Broadcast (preview → confirm → send to all, with success/failure report)
- ⚙️ Grouped settings: texts (welcome/support/purchase guide) · trial account · referrals · warnings · sub-link · app download links · crypto

**Scheduled jobs:**
- **Hourly:** expiry warnings + volume warnings (default at 80% used, threshold adjustable in settings) + disabling expired services in the panel. A failed warning send is retried the next hour.
- **Every 3 minutes:** crypto payment checks (only when enabled)
- **Daily 09:00 Tehran time:** sales report to admins

---

### Step-by-step setup (0 to 100)

#### Step 0 — What you need

- A **VPS with Ubuntu** for the 3x-ui panel (panel and bot can run on the same server or two separate ones)
- A **Telegram account** (to create and manage the bot)
- Somewhere to run the bot: **Botkeep** (free, no server needed), the same VPS, or any Linux server
- A **bank card** to receive card-to-card payments from customers

#### Step 1 — Create the bot in BotFather and get the token

1. In Telegram, open **[@BotFather](https://t.me/BotFather)** and send `/newbot`.
2. Pick a **name** for the bot (e.g. "Hazhir VPN").
3. Pick a **username** ending in `bot` (e.g. `hazhirvpnbot`).
4. BotFather gives you a **token** that looks like this:
   `123456789:AAEhBOweik6ad9r_QXMENQjcrGbqCrK7gI`
   This token is your bot's password — never send it to anyone and never write it in any public file (like GitHub). If it leaks, revoke it in BotFather with `/revoke` and get a new one.
5. Keep the token; you will put it in the `BOT_TOKEN` environment variable in step 4 or 5.

#### Step 2 — Find your numeric Telegram ID

1. In Telegram, open **[@userinfobot](https://t.me/userinfobot)** and send `/start`.
2. The number shown as "Your ID" (e.g. `123456789`) is your numeric ID — that is your `ADMIN_IDS` value.
3. For multiple admins, separate IDs with commas: `123456789,987654321`

> Never write your numeric ID in public code either; environment variable only.

#### Step 3 — Prepare the 3x-ui panel

1. **Install the panel on your VPS** (Ubuntu) with the official install script:
   ```bash
   bash <(curl -Ls https://raw.githubusercontent.com/MHSanaei/3x-ui/master/install.sh)
   ```
   After installation, the panel shows its address, port, username and password — keep them.
2. **Create an inbound:** log into the panel, go to Inbounds and add one (e.g. VLESS on any port). Note its **numeric ID** from the list (e.g. `1`). With several inbounds, write them comma-separated: `1,9,11` — that is your `INBOUNDS` value.
3. **API token:** in the panel go to **Settings → API** and create a token with **admin** scope. Copy it — it is shown in full only once. That is your `PANEL_TOKEN`.
4. **Subscription link:** enable the **Subscription** service in the panel and note the sub-link path; e.g. if your sub-link is `https://host:2096/hard/`, that value becomes `SUB_BASE`.
5. **Panel address (`PANEL_URL`):** e.g. `https://host:port/webBasePath` — or just `https://host:port` if you have no base path.

> The bot talks to the panel at `PANEL_URL + /panel/api/` with `Authorization: Bearer <API_TOKEN>`. A wrong token returns `401`; no token returns `404` (the panel's deliberate stealth behavior).

#### Step 4 — Deploy on Botkeep (no server, free)

1. Create an account at **[botkeep.cloud](https://botkeep.cloud)** and sign in.
2. Create a new bot: choose **Python 3.13**.
3. Get the code: on this project's GitHub page, click **Code → Download ZIP** and download it. (Or clone the repo and zip it yourself.)
4. In the Botkeep panel, in the **Files** tab, upload the ZIP and **Unarchive** it. Make sure **`main.py`** is at the root.
5. In the **Environment** tab, set the secrets — one variable per line (replace the values with your own):
   ```
   BOT_TOKEN=123456789:AAE...
   ADMIN_IDS=123456789
   PANEL_URL=https://your-panel-host:port/webBasePath
   PANEL_TOKEN=paste-your-panel-api-token-here
   SUB_BASE=https://your-panel-host:2096/hard/
   INBOUNDS=1
   CARD_NUMBER=6037991122334455
   CARD_HOLDER=Card holder name
   ```
6. ⚠️ **Important:** on Botkeep, Environment values are only delivered as a `.env` file inside the container and are not automatically exported to `os.environ`. So the **start command** must be:
   ```
   set -a; . ./.env; set +a; exec python main.py
   ```
   (Without this, the bot crashes with `Missing required environment variable`.)
7. **Redeploy** and watch the **Console** for the startup log. If there is no error, the bot is up.

#### Step 5 — Deploy on a VPS (Ubuntu)

1. **Install Python and git** (Ubuntu 24.04 ships Python 3.12; on 22.04 install Python 3.12 from the deadsnakes PPA first):
   ```bash
   sudo apt update
   sudo apt install -y python3 python3-venv git
   python3 --version   # should be 3.11 or newer
   ```
2. **Clone the code:**
   ```bash
   git clone https://github.com/hazhirplus/hazhir_bot.git
   cd hazhir_bot
   ```
3. **Create a virtual environment and install dependencies:**
   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```
4. **Create the `.env` file** with your own values (this file **never** goes to GitHub — it is in `.gitignore`):
   ```bash
   nano .env
   ```
   ```env
   BOT_TOKEN=123456789:AAE...
   ADMIN_IDS=123456789
   PANEL_URL=https://your-panel-host:port/webBasePath
   PANEL_TOKEN=paste-your-panel-api-token-here
   SUB_BASE=https://your-panel-host:2096/hard/
   INBOUNDS=1
   CARD_NUMBER=6037991122334455
   CARD_HOLDER=Card holder name
   ```
   Save with `Ctrl+O`, exit with `Ctrl+X`.
5. **Test-run it manually** (to make sure everything is correct):
   ```bash
   set -a; . ./.env; set +a; .venv/bin/python main.py
   ```
   If there is no error and the bot connects to Telegram, stop it with `Ctrl+C` and continue.
6. **Make it permanent with systemd** so the bot stays up and restarts with the server:
   ```bash
   sudo nano /etc/systemd/system/hazhir_bot.service
   ```
   ```ini
   [Unit]
   Description=Hazhir VPN Bot
   After=network.target

   [Service]
   Type=simple
   WorkingDirectory=/opt/hazhir_bot
   EnvironmentFile=/opt/hazhir_bot/.env
   ExecStart=/opt/hazhir_bot/.venv/bin/python main.py
   Restart=always

   [Install]
   WantedBy=multi-user.target
   ```
   > If you cloned the code elsewhere (e.g. `/root/hazhir_bot`), change all three paths (`WorkingDirectory`, `EnvironmentFile`, `ExecStart`) to match.
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable hazhir_bot
   sudo systemctl start hazhir_bot
   ```
7. **View the logs:**
   ```bash
   sudo journalctl -u hazhir_bot -f
   ```

> The bot uses **polling** (no webhook) — so you do **not** need to open any port, domain or SSL certificate for the bot itself. Only the 3x-ui panel needs to be reachable by the bot over the internet.

#### Step 6 — Deploy anywhere else

Any Linux server (or even macOS/Windows) with **Python 3.11+** is enough:
1. Clone the code, create a `venv` and run `pip install -r requirements.txt` (as in step 5).
2. Create the `.env` file with the same variables as step 5.
3. Run it:
   ```bash
   set -a; . ./.env; set +a; .venv/bin/python main.py
   ```
4. For a permanent run, use **systemd** (step 5) or **screen/tmux**:
   ```bash
   tmux new -s hazhir
   set -a; . ./.env; set +a; .venv/bin/python main.py
   # Detach with Ctrl+B then D; the bot keeps running
   ```

#### Step 7 — First login and health check

1. Send `/start` to your bot in Telegram — you see the customer menu.
2. Tap the **🛠 management** button in the bottom menu — the admin panel opens.
3. Go to "🖥 Panels" → "🔌 Test connection" — it should return ✅. If it returns ❌, see the troubleshooting table below.
4. On first run, 4 default plans are seeded (10 / 30 / 50 / 80 GB, 30 days) — in "📦 Manage plans", change their price and volume to yours.
5. Check your card number in "💳 Manage cards".
6. Make a test purchase from a second Telegram account and confirm the service is created in the panel and the sub-link is delivered.

#### Where each secret comes from, and where it goes

| Variable | Where do you get it? | Where do you put it? |
|---|---|---|
| `BOT_TOKEN` | Step 1 — BotFather (`/newbot`) | `.env` or the Environment tab on Botkeep |
| `ADMIN_IDS` | Step 2 — @userinfobot | `.env` or the Environment tab on Botkeep |
| `PANEL_URL` | Step 3 — address of the panel you installed | `.env` or the Environment tab on Botkeep |
| `PANEL_TOKEN` | Step 3 — panel, Settings ← API | `.env` or the Environment tab on Botkeep |
| `SUB_BASE` | Step 3 — panel sub-link | `.env` or the Environment tab on Botkeep |
| `INBOUNDS` | Step 3 — inbound IDs from the panel list | `.env` or the Environment tab on Botkeep |
| `CARD_NUMBER` / `CARD_HOLDER` | Your own bank card number and holder name | `.env` or the Environment tab on Botkeep |

> **Golden rule:** secrets go only in `.env` or Environment. **Never** in code, in git, in a public chat, or in a README file.

#### Troubleshooting

| Problem | Likely cause | Fix |
|---|---|---|
| `Missing required environment variable` | An environment variable is not set | Check all required variables in `.env` or Environment; on Botkeep the start command must source `.env` (step 4) |
| Panel connection test returns `401` | API token is wrong or lacks admin scope | Create a fresh token with **admin** scope in the panel and put it in `PANEL_TOKEN` |
| Panel connection test returns `404` | Panel address is wrong | Check `PANEL_URL` — it must point exactly at the panel login page |
| Bot does not respond | Two bot instances are running with the same token (polling conflict) | Stop the old instance; only **one** instance may run per token |
| `Conflict: terminated by other getUpdates request` | Same as above | Same fix as above |
| Card-to-card payment is not recorded | Card number is empty in settings | Check "💳 Manage cards" in the admin panel |
| Sub-link does not work | `SUB_BASE` is wrong or Subscription is disabled in the panel | Compare `SUB_BASE` with the panel's real sub-link and enable Subscription |

### Environment variables (complete reference)

All secrets are read only from environment variables — **never written in code or the database.**

| Name | Required | Description |
|---|---|---|
| `BOT_TOKEN` | ✅ | Bot token from BotFather |
| `ADMIN_IDS` | ✅ | Numeric admin IDs, comma-separated: `123456789,987654321` |
| `PANEL_URL` | 🌱 | Panel address, e.g. `https://host:port/webBasePath` |
| `PANEL_TOKEN` | 🌱 | Panel API token with **admin** scope (Settings → API) |
| `SUB_BASE` | 🌱 | Subscription link base, e.g. `https://host:2096/hard/` |
| `INBOUNDS` | 🌱 | Inbound IDs, comma-separated, e.g. `1,9,11` |
| `CARD_NUMBER` | 🌱 | Default card number for card-to-card payments |
| `CARD_HOLDER` | 🌱 | Card holder name |
| `EVM_ADDRESS` | — | Public EVM address for receiving crypto (optional; empty by default — never a private key) |
| `ETHERSCAN_API_KEY` | — | Free Etherscan key (from etherscan.io) for verifying crypto payments |
| `DB_PATH` | — | Database path (default `data/hozhir.db`) |

🌱 items are only used for **first-run seeding**; afterwards everything is editable from inside the bot's admin panel.

### Crypto payments (optional, off by default)

The `chainwatch.py` module verifies **ETH and USDC** payments on **Base, Arbitrum and Optimism** by matching unique amounts (Etherscan keyed backend, or keyless public RPC fallback). To enable it, turn on `crypto_enabled` in the admin settings and set `EVM_ADDRESS` and `ETHERSCAN_API_KEY`. When disabled, none of this code path runs.

### Tests

```bash
BOT_TOKEN=dummy ADMIN_IDS=1 PANEL_URL=http://127.0.0.1:1 PANEL_TOKEN=dummy \
SUB_BASE=http://127.0.0.1:1/ INBOUNDS=1 CARD_NUMBER=1 CARD_HOLDER=x \
python -m pytest tests/ -q
```

Tests use only temporary SQLite databases and never touch a real panel or Telegram. (82 tests passing, 3 skipped.)

### Security

- All database queries are parameterized; no `exec`/`eval`; numeric inputs validated
- The panel token is never logged; only its last 4 chars are shown
- Panel connections use `TLS verify=True`
- Receipts are stored only as Telegram `file_id`; duplicate receipts warn the admin
- All admin handlers are protected by the `admin_only` decorator
- Anti-flood: rate limiting (default 30 messages / 60s for regular users, 120 for admins) with one polite warning
- **No secrets in this repo:** bot token, panel token, panel address, card number and Telegram IDs are all read only from environment variables and do not exist in the code

### Project structure

| File | Description |
|---|---|
| `main.py` | Entry point; builds the app, registers handlers and jobs |
| `config.py` | Configuration read only from environment variables |
| `db.py` | SQLite (aiosqlite); users, invoices, plans, settings |
| `panel.py` | 3x-ui panel API client (create/delete/traffic/sub-links) |
| `handlers_user.py` | Customer flows: purchase, wallet, services, trial, referral |
| `handlers_admin.py` | Admin panel + settings |
| `jobs.py` | Hourly/daily jobs (warnings, reports) + crypto checks |
| `chainwatch.py` | On-chain crypto payment verification (optional) |
| `throttle.py` | Message rate limiting (anti-flood) |
| `keyboards.py` / `text.py` / `helpers.py` | Menus, texts and shared helpers |

### License

AGPL-3.0 — see the `LICENSE` file.
