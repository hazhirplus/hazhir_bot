#!/usr/bin/env bash
# هژیر وی‌پی‌ان — نصب با یک دستور (Ubuntu / Debian)
#
#   curl -fsSL https://raw.githubusercontent.com/hazhirplus/hazhir_bot/main/install.sh | bash
#   یا از داخل ریپو:
#   bash install.sh
#
# کاری که می‌کند:
#   ۱. پیش‌نیازها را نصب می‌کند (Python 3.11+ ،venv ،git)
#   ۲. کد را می‌گیرد (کلون یا به‌روزرسانی)
#   ۳. محیط مجازی می‌سازد و وابستگی‌ها را نصب می‌کند
#   ۴. توکن ربات و آیدی عددی مدیر را همان‌جا در ترمینال از شما می‌گیرد
#      و فقط همین دو مقدار را در فایل .env می‌نویسد
#   ۵. ربات را به‌صورت سرویس systemd بالا می‌آورد
#
# بقیه‌ی تنظیمات (آدرس پنل 3x-ui، توکن API، لینک ساب، اینباندها، کارت بانکی،
# پلن‌ها) بعد از بالا آمدن ربات، از داخل خود ربات انجام می‌شود:
# دکمه‌ی 🛠 مدیریت ← 🖥 مدیریت پنل ← ➕ افزودن پنل
#
# نکته‌ی امنیتی: توکن و آیدی فقط در فایل .env می‌روند — هرگز در کد یا گیت‌هاب.
set -euo pipefail

REPO_URL="https://github.com/hazhirplus/hazhir_bot.git"
SERVICE_NAME="${HAZHIR_SERVICE:-hazhir_bot}"
INSTALL_DIR="${INSTALL_DIR:-}"

say()  { printf '\n==> %s\n' "$*"; }
ok()   { printf '    ✓ %s\n' "$*"; }
warn() { printf '    ! %s\n' "$*"; }
die()  { printf '\n✗ %s\n' "$*" >&2; exit 1; }

# --- ورودی گرفتن: اول از ترمینال (/dev/tty) تا وقتی اسکریپت با curl|bash
#     اجرا می‌شود، خواندن ورودی اسکریپت را نخورد؛ اگر tty نبود، از stdin.
read_answer() { # $1=var $2=prompt $3=silent(0/1)
    local -n _out="$1"
    local _prompt="$2" _silent="${3:-0}" _val=""
    if : 2>/dev/null < /dev/tty; then
        printf '%s ' "$_prompt" > /dev/tty
        if [ "$_silent" = 1 ]; then IFS= read -rs _val < /dev/tty; printf '\n' > /dev/tty;
        else IFS= read -r _val < /dev/tty; fi
    else
        printf '%s ' "$_prompt"
        if [ "$_silent" = 1 ]; then IFS= read -rs _val; printf '\n';
        else IFS= read -r _val; fi
    fi
    _out="$_val"
}

ask_yes_no() { # $1=prompt $2=default(y/n) → returns 0 for yes
    local _prompt="$1" _def="${2:-y}" _ans=""
    if [ "$_def" = y ]; then _prompt="$_prompt [Y/n]: ";
    else _prompt="$_prompt [y/N]: "; fi
    read_answer _ans "$_prompt" 0
    _ans="${_ans:-$_def}"
    case "$_ans" in [Yy]*) return 0 ;; *) return 1 ;; esac
}

is_root() { [ "$(id -u)" = 0 ]; }
SUDO=""
if ! is_root; then
    if command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
        SUDO="sudo"
    elif command -v sudo >/dev/null 2>&1; then
        SUDO="sudo"  # ممکن است رمز بخواهد؛ همان‌جا پرسیده می‌شود
    fi
fi
SERVICE_USER="${SUDO_USER:-${USER:-root}}"

# --- مسیر نصب ---
if [ -z "$INSTALL_DIR" ]; then
    if [ -f ./main.py ] && [ -f ./requirements.txt ]; then
        INSTALL_DIR="$PWD"  # از داخل ریپو اجرا شده
    elif is_root; then
        INSTALL_DIR="/opt/hazhir_bot"
    else
        INSTALL_DIR="$HOME/hazhir_bot"
    fi
fi

say "هژیر وی‌پی‌ان — نصب ربات فروش VPN"
echo "    مسیر نصب: $INSTALL_DIR"
echo "    سرویس:    $SERVICE_NAME"

# --- ۱. پیش‌نیازها ---
say "۱) بررسی پیش‌نیازها"
if command -v apt-get >/dev/null 2>&1; then
    if ! command -v python3 >/dev/null 2>&1 \
        || ! python3 -c 'import ensurepip' 2>/dev/null \
        || ! command -v git >/dev/null 2>&1; then
        echo "    نصب python3 و git ..."
        $SUDO apt-get update -qq
        $SUDO apt-get install -y -qq python3 python3-venv git
    fi
else
    command -v python3 >/dev/null 2>&1 || die "python3 پیدا نشد — اول Python 3.11+ را نصب کنید."
    command -v git >/dev/null 2>&1 || die "git پیدا نشد — اول git را نصب کنید."
fi
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
    || die "Python 3.11 یا جدیدتر لازم است (نسخه‌ی فعلی: $(python3 --version 2>&1)). روی Ubuntu 22.04 از PPA deadsnakes نصب کنید: sudo add-apt-repository ppa:deadsnakes/ppa && sudo apt install -y python3.12 python3.12-venv"
ok "Python $(python3 --version 2>&1 | cut -d' ' -f2) و git آماده‌اند"

# --- ۲. گرفتن کد ---
say "۲) گرفتن کد ربات"
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "    ریپو موجود است — به‌روزرسانی ..."
    git -C "$INSTALL_DIR" pull --ff-only || warn "به‌روزرسانی از گیت‌هاب انجام نشد؛ با همین نسخه ادامه می‌دهم."
elif [ -f "$INSTALL_DIR/main.py" ]; then
    ok "کد در $INSTALL_DIR موجود است"
else
    $SUDO mkdir -p "$(dirname "$INSTALL_DIR")"
    git clone "$REPO_URL" "$INSTALL_DIR"
fi
if is_root && [ "$SERVICE_USER" != "root" ]; then
    chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR" || true
fi

# --- ۳. محیط مجازی + وابستگی‌ها ---
say "۳) ساخت محیط مجازی و نصب وابستگی‌ها"
if [ ! -x "$INSTALL_DIR/.venv/bin/python" ]; then
    python3 -m venv "$INSTALL_DIR/.venv"
fi
"$INSTALL_DIR/.venv/bin/pip" install -q --upgrade pip
"$INSTALL_DIR/.venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt"
ok "وابستگی‌ها نصب شدند"

# --- ۴. توکن و آیدی مدیر (فقط همین دو مقدار، در ترمینال) ---
say "۴) توکن ربات و آیدی مدیر"
echo "    توکن را از BotFather می‌گیرید: در تلگرام به @BotFather بروید و /newbot بزنید."
echo "    آیدی عددی را از @userinfobot می‌گیرید: /start بزنید و عدد Your ID را بردارید."
BOT_TOKEN="${BOT_TOKEN:-}"
ADMIN_IDS="${ADMIN_IDS:-}"
NEED_WRITE=0
[ -n "$BOT_TOKEN" ] || [ -n "$ADMIN_IDS" ] && NEED_WRITE=1
[ ! -f "$INSTALL_DIR/.env" ] && NEED_WRITE=1
if [ -f "$INSTALL_DIR/.env" ] && [ -z "$BOT_TOKEN" ] && [ -z "$ADMIN_IDS" ]; then
    if ! ask_yes_no "فایل .env از قبل هست؛ توکن و آیدی را دوباره وارد می‌کنید؟" n; then
        # shellcheck disable=SC1091
        set -a; . "$INSTALL_DIR/.env"; set +a
        BOT_TOKEN="${BOT_TOKEN:-}"
        ADMIN_IDS="${ADMIN_IDS:-}"
        NEED_WRITE=0
        ok "تنظیمات قبلی (.env) حفظ شد"
    else
        NEED_WRITE=1
    fi
fi
tries=0
while [ -z "$BOT_TOKEN" ]; do
    read_answer BOT_TOKEN "توکن ربات (BOT_TOKEN):" 1
    BOT_TOKEN="$(printf '%s' "$BOT_TOKEN" | tr -d '[:space:]')"
    if ! printf '%s' "$BOT_TOKEN" | grep -Eq '^[0-9]+:[A-Za-z0-9_-]{30,}$'; then
        warn "توکن درست به نظر نمی‌رسد (شکل درست: 123456789:AAE... با ۳۵ کاراکتر بعد از دونقطه). دوباره وارد کنید."
        BOT_TOKEN=""
    fi
    tries=$((tries + 1))
    [ "$tries" -ge 3 ] && die "سه بار توکن نامعتبر وارد شد. توکن را از @BotFather بگیرید و دوباره اجرا کنید."
done
while [ -z "$ADMIN_IDS" ]; do
    read_answer ADMIN_IDS "آیدی عددی تلگرام شما (ADMIN_IDS؛ چندتا با کاما):" 0
    ADMIN_IDS="$(printf '%s' "$ADMIN_IDS" | tr -d '[:space:]')"
    if ! printf '%s' "$ADMIN_IDS" | grep -Eq '^[0-9]+(,[0-9]+)*$'; then
        warn "آیدی باید فقط عدد باشد (مثلاً 123456789 یا 123456789,987654321). دوباره وارد کنید."
        ADMIN_IDS=""
    fi
done
if [ "$NEED_WRITE" = 1 ]; then
    {
        printf 'BOT_TOKEN=%s\n' "$BOT_TOKEN"
        printf 'ADMIN_IDS=%s\n' "$ADMIN_IDS"
    } > "$INSTALL_DIR/.env"
    chmod 600 "$INSTALL_DIR/.env"
    if is_root && [ "$SERVICE_USER" != "root" ]; then
        chown "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/.env" || true
    fi
    ok "توکن و آیدی در $INSTALL_DIR/.env ذخیره شد (فقط همین دو مقدار)"
fi

# --- ۵. سرویس systemd + بالا آوردن ---
say "۵) بالا آوردن ربات"
USE_SYSTEMD=0
if command -v systemctl >/dev/null 2>&1 && [ "$(ps -p 1 -o comm= 2>/dev/null)" = "systemd" ]; then
    USE_SYSTEMD=1
fi
if [ "$USE_SYSTEMD" = 1 ]; then
    UNIT="/etc/systemd/system/${SERVICE_NAME}.service"
    $SUDO tee "$UNIT" > /dev/null <<EOF
[Unit]
Description=Hazhir VPN Bot
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=$INSTALL_DIR/.env
ExecStart=$INSTALL_DIR/.venv/bin/python main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    $SUDO systemctl daemon-reload
    $SUDO systemctl enable -q "$SERVICE_NAME"
    START_TS="$(date '+%Y-%m-%d %H:%M:%S')"
    $SUDO systemctl restart "$SERVICE_NAME"
    # تا ۲۰ ثانیه صبر کن تا سرویس active شود
    UP=0
    for _ in $(seq 1 20); do
        if $SUDO systemctl is-active --quiet "$SERVICE_NAME"; then UP=1; break; fi
        $SUDO systemctl is-failed --quiet "$SERVICE_NAME" && break
        sleep 1
    done
    # active بودن لحظه‌ای کافی نیست: سرویس در حلقه‌ی کرش هم لحظه‌ای active است.
    # چند ثانیه صبر کن، دوباره چک کن و لاگ همین اجرا را برای علت خطا بگرد.
    FAIL_KIND=""
    if [ "$UP" = 1 ]; then
        sleep 5
        $SUDO systemctl is-active --quiet "$SERVICE_NAME" || UP=0
    fi
    RUN_LOGS="$($SUDO journalctl -u "$SERVICE_NAME" --since "$START_TS" --no-pager 2>/dev/null || true)"
    if printf '%s' "$RUN_LOGS" | grep -q "Unauthorized"; then
        UP=0; FAIL_KIND="unauthorized"
    elif printf '%s' "$RUN_LOGS" | grep -qE "NetworkError|ConnectError"; then
        UP=0; FAIL_KIND="network"
    fi
    if [ "$UP" = 1 ]; then
        ok "ربات بالاست و دارد کار می‌کند ✅"
    else
        warn "سرویس بالا نیامد — لاگ:"
        LOGS="$($SUDO journalctl -u "$SERVICE_NAME" -n 30 --no-pager 2>/dev/null || true)"
        printf '%s\n' "$LOGS"
        case "$FAIL_KIND" in
            unauthorized)
                die "تلگرام توکن را قبول نکرد (Unauthorized). توکن درست را از @BotFather بگیرید و با bash install.sh دوباره وارد کنید."
                ;;
            network)
                die "ربات به تلگرام وصل نشد (خطای شبکه). اینترنت سرور و دسترسی به api.telegram.org را چک کنید، بعد سرویس را ری‌استارت کنید: sudo systemctl restart $SERVICE_NAME"
                ;;
            *)
                die "سرویس بالا نیامد — لاگ بالا را ببینید."
                ;;
        esac
    fi
else
    warn "systemd در دسترس نیست — ربات را دستی اجرا کنید:"
    echo "    set -a; . $INSTALL_DIR/.env; set +a; $INSTALL_DIR/.venv/bin/python main.py"
    echo "    (برای اجرای دائمی از tmux یا screen استفاده کنید)"
fi

# --- قدم‌های بعد (تنظیمات از داخل ربات) ---
say "تمام شد! 🎉 ربات بالاست."
cat <<'EOF'
قدم‌های بعد — همه از داخل خود ربات (نیازی به ترمینال نیست):
  ۱. در تلگرام ربات را /start بزنید.
  ۲. دکمه‌ی 🛠 مدیریت را در منوی پایین بزنید.
  ۳. 🖥 مدیریت پنل ← ➕ افزودن پنل:
       • آدرس پنل 3x-ui (مثل https://host:port/webBasePath)
       • توکن API پنل (از Settings ← API با دسترسی admin)
       • بیس لینک ساب (مثل https://host:2096/hard/)
       • آیدی اینباندها (مثل 1,9,11)
     بعد «🔌 تست اتصال» را بزنید — باید ✅ بدهد.
  ۴. 💳 مدیریت کارت‌ها ← شماره کارت و نام صاحب کارت را وارد کنید.
  ۵. 📦 مدیریت پلن‌ها ← قیمت و حجم پلن‌های پیش‌فرض را به قیمت خودتان عوض کنید.
  ۶. با یک اکانت دیگر یک خرید آزمایشی انجام دهید.

  دیدن لاگ:  sudo journalctl -u hazhir_bot -f
  ری‌استارت:  sudo systemctl restart hazhir_bot
  نصب دوباره: bash install.sh
EOF
