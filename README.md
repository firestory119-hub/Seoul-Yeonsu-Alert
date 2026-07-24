# Seoul Yeonsu Alert v3.0

서울시 연수원 예약 가능 객실을 현재 월과 다음 달 범위에서 확인하고,
새 빈자리만 텔레그램으로 알립니다.

## 동작
- GitHub Actions: 5분 간격 예약 실행
- 조회 대상: 금요일·토요일 체크인, 1박
- 조회 범위: 오늘부터 다음 달 마지막 날
- 중복 알림 방지: `state.json`
- 로컬 실행과 GitHub Actions 모두 지원

## GitHub Secrets
저장소의 `Settings → Secrets and variables → Actions`에서 아래 3개를 만듭니다.

- `YEONSU_COOKIE`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

`cookie.txt`와 `telegram.json`은 GitHub에 올리지 마세요.

## 수동 테스트
저장소의 `Actions → Seoul Yeonsu Alert → Run workflow`를 실행합니다.

> GitHub 예약 실행은 5분 간격으로 설정되어 있지만, GitHub 사정에 따라 실제 시작이 몇 분 지연될 수 있습니다.
