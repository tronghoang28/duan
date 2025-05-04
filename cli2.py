#!/usr/bin/env python3
# File: /root/bot/cli2.py
import sys
import nest_asyncio
import os
import json
import asyncio
import logging
import sqlite3
import aiofiles
import aiosqlite
from datetime import datetime
import aiohttp
import phonenumbers
from phonenumbers import carrier, geocoder
from datetime import datetime, timedelta, timezone
from functools import wraps
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from datetime import datetime, timezone, timedelta

# === Config & Paths ===
BASE_DIR    = '/root/bot'
DATA_DIR    = os.path.join(BASE_DIR, 'data')
ADMIN_FILE   = os.path.join(BASE_DIR, 'admin.json')
CONFIG_FILE = os.path.join(BASE_DIR, 'config5.json')
SYNC_FILES  = [
    os.path.join(DATA_DIR, 'numbers.json'),
    os.path.join(DATA_DIR, 'numbers_shared1.json'),
]
DB_PATH     = os.path.join(BASE_DIR, 'data.db')

# Create folders
os.makedirs(DATA_DIR, exist_ok=True)

# Load bot token & key
with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    cfg = json.load(f)
BOT_TOKEN = cfg['bot_token']

COOLDOWN_FILE = 'cooldown.json'

# Hàm để tải dữ liệu cooldown từ file
def load_cooldowns():
    if os.path.exists(COOLDOWN_FILE):
        with open(COOLDOWN_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

# Hàm để lưu dữ liệu cooldown vào file
def save_cooldowns(cooldowns):
    with open(COOLDOWN_FILE, 'w', encoding='utf-8') as f:
        json.dump(cooldowns, f, indent=4)

# Hàm kiểm tra xem người dùng có bị cooldown không (20 phút)
def is_on_cooldown(user_id, cooldown_time=20):
    cooldowns = load_cooldowns()
    last_used_time = cooldowns.get(str(user_id))
    
    if last_used_time:
        last_used_time = datetime.fromisoformat(last_used_time)
        current_time = datetime.now()

        # Kiểm tra thời gian cooldown (20 phút)
        if current_time - last_used_time < timedelta(minutes=cooldown_time):
            return True
    return False

# Hàm cập nhật cooldown cho người dùng
def update_cooldown(user_id):
    cooldowns = load_cooldowns()
    
    # Lưu thời gian hiện tại vào json
    cooldowns[str(user_id)] = datetime.now().isoformat()
    save_cooldowns(cooldowns)

# Hàm để lấy thời gian sử dụng lần cuối
def get_last_used_time(user_id):
    cooldowns = load_cooldowns()
    return cooldowns.get(str(user_id), None)

# === Helpers ===
def html(msg: str) -> str:
    return f"<pre>{msg}</pre>"

async def send_html(update, text, reply_markup=None):
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)

async def load_json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    async with aiofiles.open(path, 'r', encoding='utf-8') as f:
        return json.loads(await f.read())

async def save_json(path: str, data: dict):
    async with aiofiles.open(path, 'w', encoding='utf-8') as f:
        await f.write(json.dumps(data, ensure_ascii=False, indent=2))

def is_valid_phone(n: str) -> bool:
    return n.isdigit() and len(n) >= 9

def get_vietnam_time() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=7))\
        .strftime("%H:%M:%S - %d/%m/%Y")

async def delete_later(msg, sec: int):
    await asyncio.sleep(sec)
    await msg.delete()

def auto_delete(func):
    @wraps(func)
    async def wr(update: Update, context: ContextTypes.DEFAULT_TYPE):
        # schedule deletion of user message
        asyncio.create_task(delete_later(update.message, 10))
        res = await func(update, context)
        return res
    return wr

async def private_message_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.message.chat.type == "private":
        role = await get_user_role(user.id)
        if role != "admin":
            # Tuỳ chọn: gửi phản hồi rồi xoá sau vài giây
            await update.message.reply_text(
                "<pre>Bot </pre>",
                parse_mode=ParseMode.HTML
            )
            return  # Không xử lý tiếp    

# === Database init & access ===
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS roles (
            user_id INTEGER PRIMARY KEY,
            role TEXT NOT NULL CHECK(role IN ('user','vip','admin'))
        )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS stats (
            user_id INTEGER,
            date TEXT,
            count INTEGER DEFAULT 0,
            PRIMARY KEY(user_id, date)
        )""")
        await db.commit()

async def get_user_role(user_id: int) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT role FROM roles WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else "user"

async def set_role(uid: int, role: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO roles(user_id, role) VALUES(?,?)
            ON CONFLICT(user_id) DO UPDATE SET role=excluded.role
        """, (uid, role))
        await db.commit()

async def get_role(uid: int) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT role FROM roles WHERE user_id=?", (uid,))
        row = await cur.fetchone()
    return row[0] if row else 'user'

async def record_number(user_id: int):
    today = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO stats (date, user_id, count)
            VALUES (?, ?, 1)
            ON CONFLICT(date, user_id) DO UPDATE SET count = count + 1
        """, (today, user_id))
        await db.commit()

async def can_add_number(user_id: int) -> bool:
    today = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT count FROM stats WHERE date = ? AND user_id = ?", (today, user_id)) as cursor:
            row = await cursor.fetchone()
            role = await get_user_role(user_id)
            limit = LIMIT_USER if role == "user" else LIMIT_VIP if role == "vip" else 999
            current = row[0] if row else 0
            return current < limit

# === Decorators ===
def admin_only(func):
    @wraps(func)
    async def w(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if await get_role(update.effective_user.id) != 'admin':
            return await send_html(update, html("💸 Chỉ Admin mới dùng được lệnh này."))
        return await func(update, context)
    return w

def vip_only(func):
    @wraps(func)
    async def w(update: Update, context: ContextTypes.DEFAULT_TYPE):
        r = await get_role(update.effective_user.id)
        if r not in ('vip','admin'):
            return await send_html(update, html("💸 Chỉ VIP/Admin mới dùng được lệnh này."))
        return await func(update, context)
    return w



# === Number storage ===
async def load_data() -> dict:
    data = await load_json(SYNC_FILES[0])
    # ensure same for all files
    return data

async def save_data(data: dict):
    # write to all sync files
    await asyncio.gather(*(save_json(p, data) for p in SYNC_FILES))
    
@auto_delete
async def auto_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    uid_s = str(uid)
    role = await get_user_role(uid)  # Lấy vai trò người dùng
    nums = context.args  # Lấy danh sách số điện thoại từ lệnh

    # Kiểm tra nếu không có số điện thoại được nhập
    if not nums:
        return await send_html(update, "<pre>📋 Vui lòng nhập số điện thoại...</pre>")

    # Kiểm tra hạn mức số điện thoại của người dùng
    if not await can_add_number(uid):
        return await send_html(update, "<pre>💸 Bạn đã hết hạn mức hôm nay.</pre>")

    # Xác định giới hạn số điện thoại theo vai trò người dùng
    limit = LIMIT_USER if role == "user" else LIMIT_VIP if role == "vip" else None

    # Kiểm tra nếu số lượng số điện thoại vượt quá giới hạn
    if limit and len(nums) > limit:
        return await send_html(update, f"<pre>{role.upper()} chỉ được thêm tối đa {limit} số/lần.</pre>")

    # Tải dữ liệu từ tệp
    data = await load_data()
    user_set = set(data.get(uid_s, []))  # Tạo một tập hợp các số điện thoại của người dùng

    # Danh sách để phân loại số điện thoại (mới, trùng lặp, không hợp lệ)
    added, dup, inv = [], [], []

    # Xử lý từng số điện thoại nhập vào
    for n in nums:
        n = n.strip()
        if not is_valid_phone(n):  # Kiểm tra tính hợp lệ của số điện thoại
            inv.append(n)
        elif n in user_set:  # Kiểm tra nếu số đã tồn tại trong danh sách
            dup.append(n)
        else:  # Nếu số hợp lệ và chưa tồn tại, thêm vào danh sách
            user_set.add(n)
            added.append(n)
            await record_number(uid)  # Ghi lại việc thêm số

    # Cập nhật dữ liệu người dùng
    data[uid_s] = sorted(user_set)
    await save_data(data)

    # Gửi thông tin người dùng về các số điện thoại đã thêm, trùng lặp và không hợp lệ
    await send_user_info(update, user, added, dup, inv, role)

    # Tạo tin nhắn phản hồi
    response_msg = (
        "<pre>📡 Danh Sách Số ĐT 🥷\n"
        "───────────────────────\n"
        f"Thêm thành công: {len(added)}\n"
        f"  + {', '.join(added)}\n"
        f"Trùng lặp: {', '.join(dup)}\n"
        f"Không hợp lệ: {', '.join(inv)}\n"
        "───────────────────────\n"
        f"User: {user.first_name or ''} {user.last_name or ''}\n"
        f"ID: {user.id}\n"
        f"Thời gian: {vietnam_time}\n"
        "</pre>"
    )

    # Gửi tin nhắn phản hồi
    await send_html(update, response_msg)

@auto_delete
async def list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid_s = str(user.id)
    role = await get_user_role(user.id)  # Bạn cần định nghĩa hàm này
    data = await load_data()             # Bạn cần định nghĩa hàm này

    nums = data.get(uid_s, [])
    if not nums:
        return await send_html(update, "<pre>📋 Danh sách trống.</pre>")

    # Giả định bạn đã có dữ liệu như sau:
    added = ["0901234567", "0912345678"]  # các số mới được thêm
    dup = ["0901234567"]                 # số bị trùng
    inv = ["abcd", "123"]               # số không hợp lệ
    vietnam_time = "02/05/2025 14:30"   # bạn nên dùng pytz hoặc datetime để lấy giờ VN
    kb = None                           # nếu bạn có bàn phím trả lời thì đặt ở đây

    lines = [
        "📡 Danh Sách Số ĐT 🥷",
        "───────────────────────",
        f"Tổng số: {len(added)}" if added else "",
        f"  + {', '.join(added)}" if added else "",
        f"Dùng stop dừng số: {', '.join(dup)}" if dup else "",
        f" 1,2..Hoặc all: {', '.join(inv)}" if inv else "",
        "───────────────────────",
        f"User: {user.first_name or ''} {user.last_name or ''}",
        f"ID: {user.id}",
        f"Thời gian: {vietnam_time}",
    ]

    # Loại bỏ dòng rỗng
    lines = [line for line in lines if line]

    msg = "<pre>" + "\n".join(lines) + "</pre>"

    await send_html(update, msg, reply_markup=kb)

@auto_delete
async def stop_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; uid_s=str(user.id)
    role = await get_user_role(user.id)
    args = context.args
    data = await load_data(); nums = data.get(uid_s, [])
    if not args:
        return await send_html(update,
            "<pre>📋 Nhập số thứ tự hoặc 'all'.</pre>"
        )
    removed=[]
    if args[0].lower()=="all":
        removed = nums.copy(); nums=[]
    else:
        try:
            idxs = sorted({int(x)-1 for x in args[0].split(",")}, reverse=True)
            for i in idxs:
                if 0<=i<len(nums):
                    removed.append(nums[i]); nums.pop(i)
        except:
            return await send_html(update,"<pre>📋 Sai cú pháp.</pre>")
    data[uid_s]=nums; await save_data(data)
    msg = ["<pre>",
           f"🥷 {user.full_name}",
           f"💻 ID: {user.id}",
           "●" + "≈"*30 + "●"]
    if removed:
        msg += ["🗑️ Xóa:\n"+ "\n".join(f"➤ {r}" for r in removed)]
    else:
        msg += ["❓ Không xóa được."]
    msg += [
        f"📌 Còn lại: {len(nums)} số.",
        {"admin":"👑 ADMIN","vip":"⭐ VIP","user":"☠️ USER"}[role],
        "📝 /list để xem",
        "</pre>"
    ] 
@auto_delete
async def smscall_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id

    # 1. Kiểm tra quyền VIP/Admin
    role = await get_user_role(user_id)
    if role not in ("vip", "admin"):
        return await send_html(update, "<pre>📋 Chỉ Dành Cho VIP/Admin.</pre>")

    # 2. Kiểm tra hạn mức
    if not await can_add_number(user_id):
        return await send_html(update, "<pre>💸 Đã hết lượt hôm nay.</pre>")

    # 3. Kiểm tra cú pháp
    if len(context.args) != 1:
        return await send_html(update, "<pre>Cú pháp: /smscall Số [ Vip đc 10 Số ]</pre>")

    phone_number = context.args[0].strip()

    # 4. Validate số điện thoại
    if not phone_number.isdigit() or len(phone_number) != 10:
        return await send_html(update, "<pre>Số không hợp lệ.</pre>")

    # 5. Lấy thông tin nhà mạng và khu vực
    try:
        parsed = phonenumbers.parse(phone_number, "VN")
        carrier_name = carrier.name_for_number(parsed, "vi")
        region       = geocoder.description_for_number(parsed, "vi")
        if not carrier_name:
            return await send_html(update, "<pre>Không xác định nhà mạng.</pre>")
    except phonenumbers.phonenumberutil.NumberParseException:
        return await send_html(update, "<pre>Số không hợp lệ.</pre>")

    # 6. Thực thi lệnh bất đồng bộ
    cmd = f"screen -dm bash -c 'timeout 500s python3 main.py {phone_number} 1000'"
    proc = await asyncio.create_subprocess_shell(cmd)
    await proc.communicate()

    # 7. Ghi thống kê
    await record_number(user_id)

    # 8. Lấy thời gian Việt Nam
    vietnam_time = get_vietnam_time()

    # 9. Tạo và gửi thông điệp
    msg = (
        "<pre>📡 Thông Tin Tấn Công 🥷\n"
        "───────────────────────\n"
        f"Phone: {phone_number}\n"
        f"Count: 1000\n"
        f"Nhà mạng: {carrier_name}\n"
        f"Khu vực: {region}\n"
        "───────────────────────\n"
        f"User: {user.first_name or ''} {user.last_name or ''}\n"
        f"ID: {user.id}\n"
        f"Thời gian: {vietnam_time}\n"
        "</pre>"
    )
    await send_html(update, msg)


@auto_delete
async def stopvip_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        return await send_html(update,"<pre>💸 /stopvipsms</pre>")
    proc = await asyncio.create_subprocess_shell("pkill -f main.py")
    await proc.communicate()
    await update.message.reply_text(
        "<b>🗑️ Đã STOP Spam All Api VIPSMS</b>",
        parse_mode=ParseMode.HTML
    )

@auto_delete
async def ngl_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id

    # Kiểm tra cooldown 20 phút
    if is_on_cooldown(user_id):
        # Lấy thời gian last_used_time
        last_used_time = get_last_used_time(user_id)
        return await update.message.reply_text(
            f"<pre>⏳ Bạn đã sử dụng lệnh /ngl lúc {last_used_time}. Vui lòng đợi thêm 20 phút nữa.</pre>",
            parse_mode=ParseMode.HTML
        )

    # Kiểm tra cú pháp
    if len(context.args) != 3:
        return await update.message.reply_text(
            "<pre>📋 Cách dùng: /ngl [username] [nội_dung] [số_lần]</pre>",
            parse_mode=ParseMode.HTML
        )

    username, noidung, repeat = context.args
    try:
        repeat_count = int(repeat)
        if repeat_count > 100:
            return await update.message.reply_text(
                "<pre>Số lần tối đa là 100.</pre>",
                parse_mode=ParseMode.HTML
            )
    except ValueError:
        return await update.message.reply_text(
            "<pre>Số lần phải là số nguyên.</pre>",
            parse_mode=ParseMode.HTML
        )

    # Ghi cooldown, thực thi spam và trả kết quả
    update_cooldown(user_id)
    cmd = f"screen -dm bash -c 'timeout 250s python3 spamngl.py {username} \"{noidung}\" {repeat_count}'"
    os.system(cmd)

    await update.message.reply_text(
        f"<pre>📨 Thông Tin Spam NGL 🥷\n"
        f"────────────────────────\n"
        f"Username    : {username}\n"
        f"Nội dung    : {noidung}\n"
        f"Số lần gửi  : {repeat_count}\n"
        f"ID người dùng: {user_id}\n"
        f"⏱ Cooldown  : 20 phút\n"
        f"</pre>",
        parse_mode=ParseMode.HTML
    )


@auto_delete
async def tiktok_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "<pre>📋 Vui lòng nhập link video hoặc username:\n/tiktok [link | username]</pre>",
            parse_mode=ParseMode.HTML
        )
        return

    query = context.args[0]
    is_video_link = "tiktok.com" in query  # đơn giản: nếu là link thì tải video

    payload = {'url': query}
    headers = {
        "Host": "www.tikwm.com",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 10; K) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Mobile Safari/537.36"
        )
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("https://www.tikwm.com/api/", headers=headers, data=payload) as response:
                result = await response.json()

        data = result.get("data", {})
        if result.get("code") != 0 or not data:
            raise ValueError("Không tìm thấy dữ liệu.")

        if is_video_link:
            # Trả về link video không logo
            video_url = data.get("play")
            if not video_url:
                raise ValueError("Không tìm thấy link video.")
            await update.message.reply_text(
                f"<pre>📋 Link video tải về:</pre>\n{video_url}",
                parse_mode=ParseMode.HTML
            )
        else:
            # Trả về thông tin user TikTok
            author = data.get("author", {})
            info = (
                f"<pre>📋 THÔNG TIN VIDEO TIKTOK 🥷\n"
                f"────────────────────────────\n"
                f"Tác giả   : {author.get('nickname','Không rõ')} "
                f"(@{author.get('unique_id','Không rõ')})\n"
                f"Tiêu đề   : {data.get('title','Không rõ')}\n"
                f"Lượt xem  : {data.get('play_count',0)}\n"
                f"Thả tim   : {data.get('digg_count',0)}\n"
                f"Bình luận : {data.get('comment_count',0)}\n"
                f"Chia sẻ   : {data.get('share_count',0)}\n"
                f"────────────────────────────\n"
                f"Link: {query}\n"
                f"</pre>"
            )
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("💬 MUA VIP Treo 24/7", url="https://t.me/nonameoaivcl")
            ]])
            await update.message.reply_text(info, parse_mode=ParseMode.HTML, reply_markup=keyboard)

    except Exception as e:
        await update.message.reply_text(
            f"<pre>💸 Đã xảy ra lỗi: {e}</pre>",
            parse_mode=ParseMode.HTML
        )


async def helpad_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if get_user_role(update.effective_user.id) != "admin":
        await send_html_message(update, "🔥 - Bạn không phải Admin!")
        return

    help_text = (
        f"👑 HƯỚNG DẪN ADMIN 👑\n"
        f"●══════════════════════════════●\n\n"
        f" /advip [id] - Thêm VIP\n"
        f" /xoavip [id] - Xoá VIP\n"
        f" /addmin [id] - Thêm Admin\n"
        f" /xoaad [id] - Xoá Admin\n"
        f" /lvip - Xem danh sách VIP\n"
        f" /lad - Xem danh sách Admin\n"
        f" /clear - Bật bot\n"
        f" /thongke - Xem dư liệu\n"
        f" /checkid [id] - Kiểm tra quyền\n\n"
        f"●══════════════════════════════●\n"
    )
    await send_html_message(update, help_text)

@admin_only
async def removeadmin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        return await update.message.reply_text(f"📋 - Nhập ID cần xoá Admin. </pre>", 
        parse_mode=ParseMode.HTML)
    try:
        uid = int(context.args[0])
    except ValueError:
        return await update.message.reply_text(f"📋 - ID không hợp lệ </pre>", 
        parse_mode=ParseMode.HTML)
    perms = load_permissions()
    if uid in perms["admins"]:
        perms["admins"].remove(uid)
        save_permissions(perms)
        await update.message.reply_text(f"<pre>📋 - Đã xoá {uid} khỏi Admin </pre>", 
        parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(f"<pre>📋 - ID này không nằm trong danh sách Admin.</pre>", 
        parse_mode=ParseMode.HTML)

@admin_only
async def removevip_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("<pre>📋 Nhập ID cần xoá VIP.</pre>", 
        parse_mode=ParseMode.HTML)
    try:
        uid = int(context.args[0])
        remove_role(uid, "vip")
        await update.message.reply_text(f"<pre>💸 Đã xoá {uid} khỏi VIP.</pre>", 
        parse_mode=ParseMode.HTML)
    except:
        await update.message.reply_text("<pre>💸 ID không hợp lệ.</pre>", 
        parse_mode=ParseMode.HTML)


@admin_only
async def lvip_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await list_roles(update, context, "vips")

@admin_only
async def lad_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await list_roles(update, context, "admins")

@admin_only
async def advip_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await send_html(update, html("/advip [uid]"))
    uid2 = int(context.args[0])
    await set_role(uid2, 'vip')
    await send_html(update, html(f"⭐ Đã cấp VIP cho {uid2}"))

@admin_only
async def clear_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import os
    import json

    # Xoá dữ liệu trong numbers.json
    try:
        with open("numbers.json", "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=4)
        
        # Nếu bạn có đồng bộ sang numbers.shared1.json
        with open("numbers.shared1.json", "w", encoding="utf-8") as f2:
            json.dump([], f2, ensure_ascii=False, indent=4)

        # Tuỳ chọn: dọn rác bộ nhớ hoặc tệp tạm (nếu có thư mục ./temp hoặc ./cache)
        for folder in ["temp", "cache"]:
            if os.path.exists(folder):
                for file in os.listdir(folder):
                    try:
                        os.remove(os.path.join(folder, file))
                    except Exception:
                        pass  # Bỏ qua file đang bị sử dụng

        await send_html(update, html("🧹 Đã xoá thành công"))
    except Exception as e:
        await send_html(update, html(f"Lỗi khi xoá dữ liệu: {e}"))

    
@admin_only
async def addmin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await send_html(update, html("/addmin [uid] "))
    uid2 = int(context.args[0])
    await set_role(uid2, 'admin')
    await send_html(update, html(f"Đã cấp ADMIN cho {uid2} "))


async def checkid_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid2 = update.effective_user.id
    await send_html(update, html(f"ID: {uid2}"))


async def thongke_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT date,SUM(count) FROM stats GROUP BY date ORDER BY date DESC LIMIT 7")
        rows = await cur.fetchall()
    txt = "\n".join(f"{r[0]}: {r[1]} số" for r in rows)
    await send_html(update, html("Thống kê 7 ngày:\n" + txt))


if __name__ == "__main__":
    import asyncio
    from telegram.ext import CommandHandler

    # 1. Khởi tạo database trước (tạo bảng nếu chưa có)
    asyncio.get_event_loop().run_until_complete(init_db())

    # 2. Tạo Application
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # 3. Đăng ký các handler
    app.add_handler(CommandHandler("auto", auto_handler))
    app.add_handler(CommandHandler("list", list_handler))
    app.add_handler(CommandHandler("stop", stop_handler))
    app.add_handler(CommandHandler("smscall", smscall_handler))
    app.add_handler(CommandHandler("stopvip", stopvip_handler))
    app.add_handler(CommandHandler("tiktok", tiktok_handler))
    app.add_handler(CommandHandler("ngl", ngl_handler))
    app.add_handler(CommandHandler("xoavip", removevip_handler))
    app.add_handler(CommandHandler("xoaad", removeadmin_handler))
    app.add_handler(CommandHandler("helpad", helpad_handler))
    app.add_handler(CommandHandler("advip", advip_handler))
    app.add_handler(CommandHandler("addmin", addmin_handler))
    app.add_handler(CommandHandler("lvip", lvip_handler))
    app.add_handler(CommandHandler("lad", lad_handler))
    app.add_handler(CommandHandler("checkid", checkid_handler))
    app.add_handler(CommandHandler("thongke", thongke_handler))
    app.add_handler(CommandHandler("clear", clear_handler))
   
   
    # 4. Chạy bot (sử dụng phương thức đồng bộ)
    print("Bot is running... (nhấn Ctrl+C để dừng)")
    app.run_polling()