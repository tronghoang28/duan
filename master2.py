import json
import random
import asyncio
from telethon import TelegramClient

# --- Config ---
api_id = 20976448  # <-- Thay bằng API ID của bạn
api_hash = '9c550766b2ad538f194d27d0c30d8678'  # <-- Thay bằng API Hash của bạn
session_name = 'session'  # File session lưu trạng thái
group_b_id = -1002308136549  # ID nhóm đích

# Đọc file numbers1_share.json từ đúng thư mục
json_file = '/root/thumucmoi/num.json'

mass_send_interval = 22 * 60  # 22 phút

# --- Init Client ---
client = TelegramClient(session_name, api_id, api_hash)

# --- Helper Functions ---
def load_numbers():
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

async def mass_send():
    while True:
        print("[INFO] Bắt đầu gửi tin nhắn hàng loạt...")
        data = load_numbers()

        if not data:
            print("[LỖI] Không tìm thấy dữ liệu trong tệp JSON")
            await asyncio.sleep(60)  # Đợi 1 phút và thử lại
            continue

        messages = []
        for user_id, numbers in data.items():
            for number in numbers:
                action = random.choice(['/call', '/smscall'])
                text = f"{action} {number}"
                messages.append(text)

        if not messages:
            print("[LỖI] Không có tin nhắn nào để gửi")
            await asyncio.sleep(60)  # Đợi 1 phút và thử lại
            continue

        for msg in messages:
            try:
                await client.send_message(group_b_id, msg)
                print(f"[ĐÃ GỬI] {msg}")
                await asyncio.sleep(2)  # Delay 2 giây giữa các tin nhắn
            except Exception as e:
                print(f"[LỖI] Không thể gửi tin nhắn: {e}")

        print(f"[INFO] Đang đợi {mass_send_interval / 60} phút trước khi gửi tin nhắn tiếp theo...")
        await asyncio.sleep(mass_send_interval)

# --- Main ---
async def main():
    await client.start()
    if not client.is_connected():
        print("[LỖI] Không thể kết nối với Telegram")
        return

    print("[INFO] Bot gửi tin nhắn tự động đang chạy...")
    await mass_send()

if __name__ == '__main__':
    asyncio.run(main())
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[INFO] Chương trình bị gián đoạn bởi người dùng")
    except Exception as e:
        print(f"[ERROR] Lỗi không mong muốn: {e}")