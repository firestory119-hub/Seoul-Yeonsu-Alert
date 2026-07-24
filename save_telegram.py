from getpass import getpass
from pathlib import Path
import json

token = getpass("TELEGRAM_BOT_TOKEN 입력: ").strip()
chat_id = input("TELEGRAM_CHAT_ID 입력: ").strip()

if not token or ":" not in token:
    raise SystemExit("봇 토큰 형식이 올바르지 않습니다.")
if not chat_id:
    raise SystemExit("Chat ID가 비어 있습니다.")

Path("telegram.json").write_text(
    json.dumps(
        {"bot_token": token, "chat_id": chat_id},
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)
print("저장 완료: telegram.json")
print("이 파일은 비밀정보이므로 공유하지 마세요.")
