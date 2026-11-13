# 프록시 추가 포트 설정 (사용자 직접 실행 필요)

## 경과
- 1차: 80번 포트 → **KT가 차단** ("400 Page not found" 가짜 응답, Squid
  로그에는 아예 안 찍힘 → ISP 레벨 차단 확정). 80/8080/3128처럼 "서버로
  흔히 쓰이는" 잘 알려진 포트는 주거용 회선에서 막는 것으로 보임.
- 2차 시도: 임의의 높은 포트 **28431**로 재시도 (패턴 차단을 피하기 위해
  무작위 선택). 라우터 포트포워딩까지 완료 후 외부에서 정상 접속 확인됨.

## 원인 (참고)
Chromium(Playwright)이 프록시 포트가 443이면 TLS로 오인해서 즉시 연결을
리셋함. curl/httpx는 영향 없음. arca/fmkorea/quasarzone(헤드리스 브라우저
사용 소스)만 영향받음.

## 1. Windows 방화벽 인바운드 허용 (관리자 PowerShell) — 완료

```powershell
netsh advfirewall firewall add rule name="Proxy-HTTP-28431" dir=in action=allow protocol=TCP localport=28431
```

## 2. Windows → WSL 포트포워딩 (관리자 PowerShell) — 완료

```powershell
netsh interface portproxy add v4tov4 listenport=28431 listenaddress=0.0.0.0 connectport=28431 connectaddress=172.22.8.238
```

## 3. 라우터 포트포워딩 — 완료

KT GiGA WiFi home 관리 페이지(`http://172.30.1.254`) → 트래픽 관리 →
포트 포워딩 설정에서 외부포트 28431 → 내부IP 172.30.1.23 → 내부포트 28431
(TCP) 규칙 추가 완료.

## 4. 확인 (완료, 성공)

```powershell
curl.exe -v -x "http://proxyuser:<PROXY_PASSWORD>@222.101.105.96:28431" https://httpbin.org/ip --max-time 15
```

→ CONNECT tunnel 성공, `{"origin": "222.101.105.96"}` 응답 확인됨.
실제 프록시 비밀번호는 Railway Variables와 로컬 `.env`(git에 커밋되지 않음)
에만 보관.

## 5. 앱 쪽 프록시 환경변수 (Railway, 적용 완료)

```
# 기존 443 유지 (curl/httpx 경로, 정상)
HTTP_PROXY_URL=http://proxyuser:<PROXY_PASSWORD>@222.101.105.96:443
PPOMPPU_PROXY_URL=http://proxyuser:<PROXY_PASSWORD>@222.101.105.96:443

# 신규 포트로 분리 (Playwright 기반 소스 전용)
FMKOREA_PROXY_URL=http://proxyuser:<PROXY_PASSWORD>@222.101.105.96:28431
QUASARZONE_PROXY_URL=http://proxyuser:<PROXY_PASSWORD>@222.101.105.96:28431
```

arca는 `app/config.py`의 `ARCA_PROXY_URL`이 `FMKOREA_PROXY_URL`로 자동
fallback되므로 별도 Railway 변수 없이도 28431을 사용함 (확인됨, 26개
게시물 정상 수집).

## 남은 이슈

fmkorea는 포트 문제는 해결됐지만, 이 프록시가 단일 고정 IP라 Akamai가
해당 IP를 밴 처리하면 당분간 막힘. 코드에 자동 쿨다운(IP 밴 감지 시 300초
대기 후 세션 로테이션)이 이미 있어 시간이 지나면 자동 복구됨. 상용
로테이팅 프록시와 달리 교체 가능한 IP가 없다는 구조적 한계는 남아있음.
