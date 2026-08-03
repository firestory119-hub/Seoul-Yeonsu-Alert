# Seoul Yeonsu Alert v4.0

쿠키를 복사하지 않고 매 실행마다 자동 로그인한 뒤 서울시 연수원 빈자리를 조회합니다.

## GitHub Secrets

- `YEONSU_ID`
- `YEONSU_PASSWORD`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

기존 `YEONSU_COOKIE`는 더 이상 사용하지 않습니다.

## 동작

- GitHub Actions 5분 간격
- 자동 로그인
- 현재 월과 다음 달까지만 조회
- 금요일·토요일 체크인
- 새 빈자리만 텔레그램 발송
- `state.json`으로 중복 알림 방지

## 로컬 실행

```cmd
python -m pip install -r requirements.txt
python save_login.py
python save_telegram.py
python main.py
```

`login.json`과 `telegram.json`은 GitHub에 올리지 마세요.
