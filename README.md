# هژیر وی‌پی‌ان | Hazhir VPN Bot

ربات تلگرام فارسی برای فروش اشتراک VPN با پنل **3x-ui** — پلن، کیف پول، پرداخت کارت‌به‌کارت، رفرال، اکانت تست، هشدار انقضا و اتمام حجم.

A Persian Telegram bot for selling VPN subscriptions via a **3x-ui** panel — plans, wallet, card-to-card payments, referrals, trial accounts, expiry & volume warnings.

> تحت لایسنس **AGPL-3.0** منتشر می‌شود. هیچ کدی از پروژه‌ی مرجع کپی نشده است.
> Released under **AGPL-3.0**. No code was copied from the reference project.

> ⚠️ **توکن ربات، آیدی عددی تلگرام، توکن پنل و شماره کارت را هرگز در کد یا گیت‌هاب ننویسید** — فقط در متغیر محیطی (فایل `.env` روی سرور یا تب Environment در Botkeep). اگر لو رفت، توکن ربات را در BotFather با `/revoke` و توکن پنل را از Settings ← API پنل باطل کنید.
> ⚠️ **Never put your bot token, Telegram ID, panel token or card number in code or on GitHub** — environment variables only (`.env` on your server, or the Environment tab on Botkeep).

- [فارسی](#فارسی)
- [English](#english)

---

## فارسی

### امکانات

**مشتری:** خرید سرویس (انتخاب سرور با اسم، کیف پول / کارت‌به‌کارت با تأیید مدیر / ارز دیجیتال اختیاری) ← تحویل خودکار لینک اشتراک + QR · سرویس‌های من (حجم و روزهای باقی‌مانده، زنده از پنل) · کیف پول · اکانت تست (یک بار، بدون تأیید مدیر) · دعوت دوستان (با اولین خرید دعوت‌شده، یک سرویس هدیه) · آموزش اتصال اندروید / آیفون / ویندوز · پشتیبانی.

**مدیر (دکمه 🛠 مدیریت در منوی پایین — نه دستور):** گزارش‌ها · پرداخت‌های در انتظار با تأیید/رد و تشخیص فیش تکراری · مدیریت پنل (نام سرور، آدرس، توکن، ساب، سقف فروش، تست اتصال) · اینباندها (با مرجع از روی کانفیگ) · پلن‌ها · کارت‌ها · کاربران · آموزش‌ها · پیام همگانی · تنظیمات گروه‌بندی‌شده (شامل 🔒 قفل کانال) · **📖 آموزش راه‌اندازی** — ویزارد قدم‌به‌قدم برای تنظیم اولیه.

**خودکار:** هر ساعت هشدار انقضا و اتمام حجم (پیش‌فرض ۸۰٪ مصرف) + غیرفعال‌سازی سرویس‌های منقضی · روزانه ۰۹:۰۰ تهران گزارش فروش · هر ۳ دقیقه بررسی پرداخت کریپتو (فقط وقتی فعال باشد).

### راه‌اندازی

> **پنل 3x-ui روی یک سرور مجازی نصب می‌شود. خود ربات فقط روی یکی از این دو جا اجرا می‌شود — یا Botkeep (رایگان، بدون سرور) یا سرور مجازی. هر دو با هم لازم نیست.**

#### قدم ۱ — توکن ربات

در تلگرام به [@BotFather](https://t.me/BotFather) برو، `/newbot` بفرست، نام و یوزرنیم (ختم‌شونده به `bot`) بده. توکن رو نگه دار — فقط در متغیر محیطی می‌ره.

#### قدم ۲ — آیدی عددی خودت

به [@userinfobot](https://t.me/userinfobot) برو و `/start` بزن — عدد «Your ID» همون `ADMIN_IDS` است.

#### قدم ۳ — پنل 3x-ui (روی سرور مجازی Ubuntu)

```bash
bash <(curl -Ls https://raw.githubusercontent.com/MHSanaei/3x-ui/master/install.sh)
```

بعد از نصب: یک اینباند بساز (آیدی عددیش رو بردار، مثلاً `1`) · از Settings ← API یک توکن با دسترسی **admin** بساز · سرویس Subscription را فعال کن و لینک ساب را بردار (مثلاً `https://host:2096/hard/`).

#### قدم ۴ — اجرای ربات (یکی را انتخاب کن)

**الف) Botkeep — بدون سرور، رایگان**

1. در [botkeep.cloud](https://botkeep.cloud) حساب بساز؛ بات جدید با نوع **Python 3.13**.
2. از همین صفحه‌ی گیت‌هاب، Code ← Download ZIP و در تب Files آپلود و Unarchive کن (باید `main.py` در ریشه باشد).
3. در تب Environment فقط این دو را ست کن (بقیه بعداً از داخل ربات ست می‌شوند — قدم ۵):
   ```
   BOT_TOKEN=...
   ADMIN_IDS=...
   ```
4. Start command **باید** این باشد (وگرنه ربات کرش می‌کند):
   ```
   set -a; . ./.env; set +a; exec python main.py
   ```
5. Redeploy کن و لاگ Console را چک کن.

**ب) سرور مجازی — با یک دستور**

```bash
curl -fsSL https://raw.githubusercontent.com/hazhirplus/hazhir_bot/main/install.sh | bash
```

نصب‌کننده پیش‌نیازها را نصب می‌کند، کد را می‌گیرد، توکن ربات و آیدی عددی را ازت می‌پرسد و ربات را به‌صورت سرویس systemd بالا می‌آورد. بقیه‌ی تنظیمات از داخل ربات انجام می‌شود — قدم ۵.

> روش دستی هم کار می‌کند (کلون + venv + `.env` + systemd)؛ دستوراتش توی `install.sh` هست. ربات با polling کار می‌کند — برای خود ربات نیازی به پورت، دامنه یا SSL نیست.

#### قدم ۵ — اولین ورود و راه‌اندازی از داخل ربات

1. به رباتت `/start` بزن، بعد دکمه‌ی **🛠 مدیریت** در منوی پایین.
2. دکمه‌ی **📖 آموزش راه‌اندازی** را بزن — قدم‌به‌قدم اسم سرور، آدرس پنل، توکن، بیس ساب، اینباندها و کارت را ازت می‌گیرد و آخرش اتصال به پنل را تست می‌کند. هر قدم را می‌توانی رد کنی.
3. از «📦 پلن‌ها» قیمت ۴ پلن پیش‌فرض (۱۰ / ۳۰ / ۵۰ / ۸۰ گیگ، ۳۰ روزه) را به قیمت خودت عوض کن.
4. یک خرید آزمایشی با یک اکانت تلگرام دیگر بگیر.

### متغیرهای محیطی

| نام | توضیح |
|---|---|
| `BOT_TOKEN` | ✅ ضروری — توکن ربات از BotFather |
| `ADMIN_IDS` | ✅ ضروری — آیدی عددی مدیرها، با کاما |
| `PANEL_URL` / `PANEL_TOKEN` / `SUB_BASE` / `INBOUNDS` | 🌱 آدرس پنل، توکن API (admin)، بیس ساب، آیدی اینباندها |
| `CARD_NUMBER` / `CARD_HOLDER` | 🌱 شماره کارت و نام صاحب کارت |
| `EVM_ADDRESS` / `ETHERSCAN_API_KEY` | ارز دیجیتال (اختیاری) |
| `DB_PATH` | مسیر دیتابیس (پیش‌فرض `data/hozhir.db`) |

موارد 🌱 فقط برای مقداردهی اولیه در اولین اجرا استفاده می‌شوند؛ بعد از آن همه‌چیز از داخل ربات قابل تغییر است.

### عیب‌یابی

| مشکل | راه‌حل |
|---|---|
| `Missing required environment variable` | همه‌ی متغیرها را در `.env` یا Environment چک کن؛ در Botkeep استارت‌کامند باید `.env` را سورس کند (قدم ۴ الف) |
| تست اتصال `401` | توکن API اشتباه است یا دسترسی admin ندارد |
| تست اتصال `404` | آدرس پنل اشتباه است |
| ربات جواب نمی‌دهد / `Conflict: terminated by other getUpdates request` | دو نسخه با یک توکن در حال اجراست — نسخه‌ی قدیمی را خاموش کن؛ فقط یک اینستنس |
| پرداخت کارت‌به‌کارت ثبت نمی‌شود | شماره کارت در «💳 کارت‌ها» خالی است |
| لینک ساب کار نمی‌کند | `SUB_BASE` اشتباه است یا Subscription در پنل فعال نیست |

### تست‌ها

```bash
BOT_TOKEN=dummy ADMIN_IDS=1 PANEL_URL=http://127.0.0.1:1 PANEL_TOKEN=dummy \
SUB_BASE=http://127.0.0.1:1/ INBOUNDS=1 CARD_NUMBER=1 CARD_HOLDER=x \
python -m pytest tests/ -q
```

فقط با دیتابیس موقت SQLite؛ به پنل یا تلگرام واقعی وصل نمی‌شود.

### امنیت

همه‌ی کوئری‌ها پارامتری؛ توکن پنل هرگز لاگ نمی‌شود (فقط ۴ رقم آخر نمایش داده می‌شود)؛ اتصال به پنل با `TLS verify=True`؛ رسید فقط به‌صورت `file_id` ذخیره می‌شود؛ همه‌ی هندلرهای مدیریتی با `admin_only` محافظت شده‌اند؛ ضد اسپم: ۳۰ پیام در ۶۰ ثانیه (مدیر ۱۲۰).

### ☕ حمایت مالی

اگر به کارت اومد، با ارز دیجیتال دونیت کن — ETH و USDC روی اتریوم / Base / آربیتروم / اپتیمیزم:
`0x92A8F1fe99D30b11D602e3f8A8078d125a158f7E`

### لایسنس

AGPL-3.0 — فایل `LICENSE` را ببینید.

---

## English

### Features

**Customers:** buy a service (wallet / card-to-card with admin approval / optional crypto) → automatic subscription link + QR delivery · My services (live remaining volume and days from the panel) · wallet · trial account (once, no approval) · referrals (first purchase of an invitee creates a gift service) · Android / iPhone / Windows connection guides · support.

**Admins (🛠 management button in the bottom menu — never a command):** reports · pending payments with approve/reject and duplicate-receipt warnings · panel management (server name, address, token, sub-link, sales cap, connection test) · inbounds (with a reference client) · plans · cards · users · tutorials · broadcast · grouped settings (including 🔒 channel lock) · **📖 setup guide** — a step-by-step wizard for the first setup.

**Automatic:** hourly expiry and volume warnings (default at 80% used) + disabling expired services · daily 09:00 Tehran sales report · crypto payment checks every 3 minutes (only when enabled).

### Setup

> **The 3x-ui panel runs on a VPS. The bot itself runs on only one of these two — either Botkeep (free, no server) or a VPS. You do not need both.**

#### Step 1 — Bot token

In Telegram, open [@BotFather](https://t.me/BotFather), send `/newbot`, pick a name and a username ending in `bot`. Keep the token — it goes only in an environment variable.

#### Step 2 — Your numeric Telegram ID

Open [@userinfobot](https://t.me/userinfobot) and send `/start` — the "Your ID" number is your `ADMIN_IDS` value.

#### Step 3 — 3x-ui panel (on an Ubuntu VPS)

```bash
bash <(curl -Ls https://raw.githubusercontent.com/MHSanaei/3x-ui/master/install.sh)
```

After installing: create an inbound (note its numeric ID, e.g. `1`) · in Settings ← API create a token with **admin** scope · enable the Subscription service and note the sub-link (e.g. `https://host:2096/hard/`).

#### Step 4 — Run the bot (pick one)

**A) Botkeep — no server, free**

1. Create an account at [botkeep.cloud](https://botkeep.cloud); create a bot of type **Python 3.13**.
2. From this GitHub page, Code → Download ZIP, upload it in the Files tab and Unarchive ( `main.py` must be at the root).
3. In the Environment tab set only these two (the rest is configured inside the bot — step 5):
   ```
   BOT_TOKEN=...
   ADMIN_IDS=...
   ```
4. The start command **must** be (otherwise the bot crashes):
   ```
   set -a; . ./.env; set +a; exec python main.py
   ```
5. Redeploy and check the Console log.

**B) VPS — one command**

```bash
curl -fsSL https://raw.githubusercontent.com/hazhirplus/hazhir_bot/main/install.sh | bash
```

The installer installs the prerequisites, fetches the code, asks for the bot token and your numeric ID, and starts the bot as a systemd service. Everything else is configured inside the bot — step 5.

> The manual way (clone + venv + `.env` + systemd) also works; the commands are in `install.sh`. The bot uses polling — it needs no port, domain or SSL of its own.

#### Step 5 — First login and setup inside the bot

1. Send `/start` to your bot, then tap the **🛠 management** button in the bottom menu.
2. Tap **📖 setup guide** — it walks you through the panel address, token, sub-link base, inbounds and card, then tests the panel connection. You can skip any step.
3. In "📦 Plans", change the prices of the 4 seeded plans (10 / 30 / 50 / 80 GB, 30 days).
4. Make a test purchase from a second Telegram account.

### Environment variables

| Name | Description |
|---|---|
| `BOT_TOKEN` | ✅ Required — bot token from BotFather |
| `ADMIN_IDS` | ✅ Required — numeric admin IDs, comma-separated |
| `PANEL_URL` / `PANEL_TOKEN` / `SUB_BASE` / `INBOUNDS` | 🌱 Panel address, API token (admin), sub-link base, inbound IDs |
| `CARD_NUMBER` / `CARD_HOLDER` | 🌱 Card number and holder name |
| `EVM_ADDRESS` / `ETHERSCAN_API_KEY` | Crypto (optional) |
| `DB_PATH` | Database path (default `data/hozhir.db`) |

🌱 items are only used for first-run seeding; afterwards everything is editable from inside the bot.

### Troubleshooting

| Problem | Fix |
|---|---|
| `Missing required environment variable` | Check all variables in `.env` or Environment; on Botkeep the start command must source `.env` (step 4A) |
| Connection test returns `401` | API token is wrong or lacks admin scope |
| Connection test returns `404` | Panel address is wrong |
| Bot does not respond / `Conflict: terminated by other getUpdates request` | Two instances are running with the same token — stop the old one; only one instance per token |
| Card-to-card payment is not recorded | Card number is empty in "💳 Cards" |
| Sub-link does not work | `SUB_BASE` is wrong or Subscription is disabled in the panel |

### Tests

```bash
BOT_TOKEN=dummy ADMIN_IDS=1 PANEL_URL=http://127.0.0.1:1 PANEL_TOKEN=dummy \
SUB_BASE=http://127.0.0.1:1/ INBOUNDS=1 CARD_NUMBER=1 CARD_HOLDER=x \
python -m pytest tests/ -q
```

Temporary SQLite databases only; never touches a real panel or Telegram.

### Security

All queries are parameterized; the panel token is never logged (only its last 4 chars are shown); panel connections use `TLS verify=True`; receipts are stored only as Telegram `file_id`; all admin handlers are protected by `admin_only`; anti-flood: 30 messages / 60s (admins 120).

### ☕ Buy me a coffee (Donate)

If this bot was useful to you, you can donate with crypto — ETH and USDC on Ethereum / Base / Arbitrum / Optimism:
`0x92A8F1fe99D30b11D602e3f8A8078d125a158f7E`

### License

AGPL-3.0 — see the `LICENSE` file.
