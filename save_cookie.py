from getpass import getpass
from pathlib import Path

print("Chrome 개발자도구에서 /onlineRsv/list 요청의 Request Headers → Cookie 값을 복사하세요.")
print("주의: 'cookie:' 글자는 빼고, 오른쪽 값 전체만 붙여넣으세요.")
cookie = getpass("Cookie 값 붙여넣기(화면에는 표시되지 않음): ").strip()

if not cookie or "=" not in cookie:
    raise SystemExit("Cookie 값이 올바르지 않습니다.")

Path("cookie.txt").write_text(cookie, encoding="utf-8")
print("저장 완료: cookie.txt")
