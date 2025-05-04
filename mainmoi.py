import asyncio
from telegram.ext import Application, CommandHandler, CallbackQueryHandler
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ParseMode
import json, os
from datetime import datetime, timedelta, timezone
from functools import wraps
from telegram.error import BadRequest

# ===== CẤU HÌNH TOKEN TRỰC TIẾP =====
BOT_TOKEN = "7599849151:AAE35B-nJKhNZJAnvhZCV1EUqtukj16SDPc"

# ===== Đọc / Ghi JSON =====
def doc_json(file):
    if not os.path.exists(file):
        return {}
    with open(file, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def ghi_json(file, data):
    with open(file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ===== Hàm hỗ trợ =====
def lay_gio_vn():
    return (datetime.now(timezone.utc) + timedelta(hours=7)).strftime("%H:%M:%S - %d/%m/%Y")

async def xoa_sau(msg, giay: int):
    await asyncio.sleep(giay)
    try:
        await msg.delete()
    except BadRequest:
        pass

def auto_delete(func):
    @wraps(func)
    async def wrapper(update: Update, context):
        if update.message:
            asyncio.create_task(xoa_sau(update.message, 10))
        result = await func(update, context)
        return result
    return wrapper

async def send_message(update, text, reply_markup=None):
    return await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)

# ===== Quyền VIP & Admin =====
def is_vip(user_id):
    data = doc_json("admin.json")
    return str(user_id) in data and data[str(user_id)].get("role") == "vip"

def them_vip(user_id, name):
    data = doc_json("admin.json")
    data[str(user_id)] = {"name": name, "role": "vip"}
    ghi_json("admin.json", data)

# ===== Quản lý số điện thoại =====
def is_valid_phone_number(s):
    return s.isdigit() and len(s) == 10 and s.startswith("0")

def is_duplicate(s, user_id):
    data = doc_json("num.json")
    return s in data.get(str(user_id), [])

def is_max_phone_limit_reached(user_id):
    data = doc_json("num.json")
    return len(data.get(str(user_id), [])) >= 10

def them_so_user(user_id, danh_sach):
    data = doc_json("num.json")
    uid = str(user_id)
    if uid not in data:
        data[uid] = []
    data[uid].extend(danh_sach)
    data[uid] = list(set(data[uid]))
    ghi_json("num.json", data)

def lay_so_user(user_id):
    return doc_json("num.json").get(str(user_id), [])

def xoa_so_user(user_id, danh_sach):
    data = doc_json("num.json")
    uid = str(user_id)
    if uid in data:
        data[uid] = [s for s in data[uid] if s not in danh_sach]
        if not data[uid]:
            del data[uid]
        ghi_json("num.json", data)

# ===== Các lệnh =====
@auto_delete
async def auto_handler(update: Update, context):
    user = update.effective_user
    user_id = user.id
    name = user.full_name
    vietnam_time = lay_gio_vn()

    if not is_vip(user_id):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Nhấn để đăng ký VIP", callback_data=f"vip:{user_id}")]
        ])
        return await send_message(update, "<pre>➤Bạn chưa có quyền VIP để dùng lệnh này.</pre>", reply_markup=keyboard)

    if not context.args:
        return await send_message(update, "<pre>➤ Vui lòng nhập số ĐT sau lệnh /auto←</pre>")

    added, dup, inv = [], [], []

    if is_max_phone_limit_reached(user_id):
        return await send_message(update, "<pre>➤ Bạn chỉ được thêm tối đa 10 ĐT←</pre>")

    for phone in context.args:
        phone = phone.strip()
        if not is_valid_phone_number(phone):
            inv.append(phone)
        elif is_duplicate(phone, user_id):
            dup.append(phone)
        else:
            them_so_user(user_id, [phone])
            added.append(phone)

    response = (
        "<pre>📡 Danh Sách Số ĐT 🥷\n"
        "───────────────────────\n"
        f"Thêm thành công: {len(added)}\n"
        f"  + {', '.join(added)}\n"
        f"Trùng lặp: {', '.join(dup)}\n"
        f"Không hợp lệ: {', '.join(inv)}\n"
        "───────────────────────\n"
        f"User: {name}\n"
        f"ID: {user_id}\n"
        f"Thời gian: {vietnam_time}\n"
        "</pre>"
    )
    await send_message(update, response)

@auto_delete
async def list_handler(update: Update, context):
    user = update.effective_user
    user_id = user.id
    vietnam_time = lay_gio_vn()

    if not is_vip(user_id):
        return await send_message(update, "<pre>❌ Bạn không có quyền VIP để sử dụng lệnh này.</pre>")

    user_numbers = lay_so_user(user_id)

    if not user_numbers:
        return await send_message(update, "<pre>➤ Bạn chưa thêm số điện thoại nào vào danh sách←</pre>")

    response = (
        "<pre>📡 Danh Sách Số ĐT 🥷\n"
        "───────────────────────\n"
        f"Số điện thoại đã thêm:\n"
        f"  + {', '.join(user_numbers)}\n"
        "───────────────────────\n"
        f"User: {user.first_name or ''} {user.last_name or ''}\n"
        f"ID: {user.id}\n"
        f"Thời gian: {vietnam_time}\n"
        "</pre>"
    )
    await send_html(update, response)

@auto_delete
async def delso_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    vietnam_time = lay_gio_vn()

    if not is_vip(user_id):
        return await send_message(update, "<pre>❌ Bạn không có quyền VIP để sử dụng lệnh này.</pre>")

    user_numbers = lay_so_user(user_id)

    if not context.args:
        return await send_html(update, "<pre>➤ Cách dùng: /delso [số thứ tự] hoặc /delso all←</pre>")

    arg = context.args[0].strip().lower()

    if arg == "all":
        if user_numbers:
            xoa_so_user(user_id, user_numbers)
            response_msg = (
                "<pre>➤ Đã xoá toàn bộ số điện thoại←\n"
                "───────────────────────\n"
                f"User: {user.first_name or ''} {user.last_name or ''}\n"
                f"ID: {user.id}\n"
                f"Thời gian: {vietnam_time}\n"
                "</pre>"
            )
        else:
            response_msg = "<pre>➤ Danh sách của bạn đang trống←</pre>"
    else:
        try:
            index = int(arg) - 1
            if 0 <= index < len(user_numbers):
                deleted_number = user_numbers[index]
                xoa_so_user(user_id, [deleted_number])
                response_msg = (
                    "<pre>➤ Đã xoá số:\n"
                    f"- {deleted_number}\n"
                    "───────────────────────\n"
                    f"User: {user.first_name or ''} {user.last_name or ''}\n"
                    f"ID: {user.id}\n"
                    f"Thời gian: {vietnam_time}\n"
                    "</pre>"
                )
            else:
                response_msg = "<pre>➤ Số thứ tự không hợp lệ←</pre>"
        except ValueError:
            response_msg = "<pre>➤ Sai cú pháp. Dùng: /delso [số thứ tự] hoặc /delso all←</pre>"

    await send_html(update, response_msg)

async def vip_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    name = query.from_user.full_name
    them_vip(user_id, name)
    await query.edit_message_text("<pre>✅ Bạn đã được cấp quyền VIP thành công!</pre>", parse_mode=ParseMode.HTML)

async def vip_callback_handler(update: Update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    name = query.from_user.full_name
    them_vip(user_id, name)
    await query.edit_message_text("<pre>✅ Bạn đã được cấp quyền VIP thành công!</pre>", parse_mode=ParseMode.HTML)

# ===== MAIN =====
async def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("auto", auto_handler))
    app.add_handler(CommandHandler("list", list_handler))
    app.add_handler(CommandHandler("delso", delso_handler))
    app.add_handler(CallbackQueryHandler(vip_callback_handler, pattern=r"^vip:\d+$"))

    print("Bot đang chạy...")
    await app.run_polling()

if __name__ == '__main__':
    asyncio.run(main())