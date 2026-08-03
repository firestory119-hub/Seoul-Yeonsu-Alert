from getpass import getpass
from pathlib import Path
import json

user_id = input("연수원 아이디: ").strip()
password = getpass("연수원 비밀번호(화면에 표시되지 않음): ").strip()

if not user_id or not password:
    raise SystemExit("아이디 또는 비밀번호가 비어 있습니다.")

Path("login.json").write_text(
    json.dumps({"user_id": user_id, "password": password}, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
print("저장 완료: login.json")
print("이 파일은 GitHub에 올리지 마세요.")
