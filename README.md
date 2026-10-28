# 대가 · DAEGA

투자에는 배움이, 선택에는 대가가. 무리한 빚투의 부담을 실제 시간에 따라 체험하는 투자 학습 웹 앱입니다.

React + TypeScript + Vite 프론트엔드와 Python FastAPI 백엔드로 구성했습니다. 키가 없으면 로컬 회원가입·SQLite 저장·고정 샘플 가격으로 전체 흐름을 실행할 수 있습니다. 서비스별 키를 연결하면 토스증권 시세, OpenDART 재무제표, Supabase Auth/PostgreSQL을 사용합니다. 실제 매매 주문 API는 호출하지 않습니다.

## 실행

일반 설치 환경은 Python 3.11 이상, Node.js 20.19 이상과 pnpm이 필요합니다. npm을 사용하는 경우 `pnpm install`, `pnpm run dev`, `pnpm run build`를 각각 `npm install`, `npm run dev`, `npm run build`로 바꿔 실행할 수 있습니다. 현재 작업 PC에는 `.venv`와 `node_modules`를 준비해 두었습니다.

```powershell
# 최초 설치
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
pnpm install
# .env가 없으면 예시 복사 (이미 작성한 .env를 덮어쓰지 마세요)
Copy-Item .env.example .env
```

터미널 두 개에서 각각 실행합니다. 가상환경 활성화 없이 실행하므로 PowerShell 실행 정책을 바꿀 필요가 없습니다.

```powershell
# 터미널 1: 백엔드
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload
# 터미널 2: 프론트엔드
pnpm run dev
```

브라우저: http://localhost:5173 / API 문서: http://localhost:8000/docs

빌드 후 한 개의 서버로도 실행할 수 있습니다. **빌드 완료 후 백엔드를 재시작**하면 `dist/`가 제공됩니다.

```powershell
pnpm run build
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

이 경우 웹 앱은 http://localhost:8000 입니다.

## 키 발급 후 연결

저장소 루트의 `.env`에 키를 넣고 백엔드를 재시작합니다. `.env`와 로컬 DB는 Git에서 제외됩니다. 브라우저에 노출되는 `VITE_*` 변수에 비밀키를 넣지 마세요.

### 1. Supabase 회원가입·DB

1. Supabase 프로젝트를 생성합니다.
2. SQL Editor에서 `supabase/migrations/202610280001_daega.sql` 전체를 **한 번 실행**합니다. 키만 입력해도 테이블이 자동 생성되지는 않습니다.
3. `.env`의 `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`를 채웁니다. 현재 REST 구현은 Supabase의 기존 JWT 형식 anon/service_role 키를 사용합니다.
4. Authentication의 이메일 가입을 활성화하고 확인 메일의 Site URL을 로컬 주소로 지정합니다. 이메일 확인이 켜져 있으면 가입 후 메일 인증을 거쳐 로그인합니다.
5. 서버를 재시작합니다. `/api/config`의 `auth_mode`가 `supabase`면 연결 모드입니다.

닉네임은 가입 트리거로 고유하게 저장됩니다. 보유 주식·예수금·거래 내역·학습 이력은 `accounts.data` JSONB에 저장하며, 서버 전용 함수의 버전 비교로 동시 주문 충돌을 막습니다. 클라이언트는 잔액·보상·수익률을 직접 수정할 수 없습니다. 랭킹에는 닉네임만 노출하며 이메일과 비밀번호를 공개하지 않습니다. 로컬 계정은 Supabase로 자동 이전하지 않으므로 연결 후 새로 가입합니다.

### 2. 토스증권 실제 시세

1. 토스증권 WTS의 설정 > Open API에서 `client_id`와 `client_secret`을 발급받고, 허용 IP 관리에 **서버를 실행하는 PC의 공인 IP**를 등록합니다. IP 미등록 시 403 오류가 발생합니다.
2. `.env`의 `TOSS_CLIENT_ID`, `TOSS_CLIENT_SECRET`을 채웁니다. `TOSS_BASE_URL`은 기본값 `https://openapi.tossinvest.com`을 그대로 사용합니다. `KIS_*` 환경변수는 사용하지 않습니다.
3. 서버를 재시작하면 화면에 실제 시세 모드가 표시됩니다. 가격은 15초 폴링, 공유 캐시는 10초입니다. WebSocket 틱 스트리밍은 아닙니다.
4. 샘플 계정 또는 이전 한국투자증권 계정으로 로그인 중이었다면 설정에서 **새 여정 시작**으로 토스 시세 계정을 만듭니다. 확인 후 시작하면 이전 거래·보유·보상은 초기화됩니다. 기존 계정 데이터를 자동 삭제하거나 다른 공급자 계정으로 재분류하지 않습니다.

선정 국내주식 8개를 `/api/v1/prices`로 일괄 조회합니다. 가격은 국내 통합 시세이고, 모의 주문은 `/api/v1/market-calendar/KR`의 당일 통합 정규장 세션에서만 허용합니다. 휴장일과 개장 시간 변경도 해당 응답을 따릅니다. 프리·애프터마켓 주문은 지원하지 않습니다. 주문 시 `/api/v1/stocks`의 상장·거래정지 상태와 최근 2분 이내의 시세 시각을 확인합니다. 거래 가능 여부가 불확실하거나 연결이 실패하면 주문을 거절하며 샘플로 대체 체결하지 않습니다.

일별 차트는 `/api/v1/candles`의 `interval=1d`, `adjusted=false` 데이터를 시간순으로 정렬합니다. 전일 대비 등락률은 조회한 현재가와 시세일 이전의 가장 최근 일봉 종가 (시세 시각이 없으면 오늘 이전 종가)로 계산합니다. 일봉 캐시는 60초이며, 전 거래일 종가가 없으면 등락률을 ‘—’로 표시합니다. 현재가의 공급자 시각이 누락되면 조회는 가능하지만 주문을 허용하지 않습니다. 기업행동 발생일에는 미수정 종가 비교로 등락률이 크게 나타날 수 있습니다.

접근 토큰은 form-urlencoded Client Credentials 방식으로 서버에서 발급·재사용하며, 만료 전에 갱신합니다. 데이터 요청이 401이면 한 번만 재발급 후 재시도합니다. 403(허용 IP·권한), 429(요청 한도) 등은 키를 노출하지 않는 오류 메시지로 안내합니다. 토스는 client당 유효 토큰이 1개이므로 같은 키를 여러 서버 프로세스에서 공유하지 말고 기본 단일 worker로 실행하세요. 증권 계좌번호나 계좌 식별 헤더는 사용하지 않으며 실제 주문 API를 호출하지 않습니다.

### 3. OpenDART 재무제표

`OPENDART_API_KEY`를 입력하고 재시작합니다. 기본적으로 전년도부터 최근 3개 사업연도 안에서 가장 최근 공개된 연간 재무제표를 조회합니다. 동일 연도의 연결(CFS)을 우선하고, 연결 공시가 없을 때만 별도(OFS)를 조회합니다. 자료 없음(013)만 다음 기준으로 넘어가며 인증·통신 오류로 과거 데이터를 대신 제공하지 않습니다. `DART_BUSINESS_YEAR`를 지정하면 해당 연도로 고정합니다. 회사 고유번호는 `backend/app/services/catalog.py`에 종목코드와 매핑해 두었습니다.

매출·순이익·자기자본·부채비율과 전체 공시 항목을 제공합니다. 누락 계정은 ‘미제공’으로 표시합니다. 평균 자기자본이 필요한 ROE는 기말 자본만으로 추정하지 않습니다. 실제 PER/PBR은 토스 현재가와 OpenDART 연간 공시로 계산합니다. 샘플 PER/PBR을 실제 수치처럼 사용하지 않습니다. 키가 없을 때 재무정보는 학습용 예시임을 별도로 표시합니다.

### 연간 공시 기준 PER·PBR

- PER = 토스 현재가 ÷ 해당 연도 보통주 기본 EPS. 손익계산서의 표준 기본 EPS를 우선하며, 없으면 같은 결산일·접수번호·연결/별도 기준의 배당 공시 중 **기본 주당순이익임이 명시된 항목만** 확인합니다. 희석 EPS, 기본/희석 구분이 없는 EPS, 기말주식 수로 추정한 EPS는 대체 사용하지 않습니다.
- PBR = 토스 현재가 ÷ 기말 BPS. 연결은 비지배지분을 제외한 지배기업 소유주 귀속 자본, 별도는 해당 재무제표의 자기자본을 사용합니다. 주식총수 공시의 보통주 발행주식에서 자기주식을 제외한 수량으로 나눕니다. 보고서 기준일과 공시 접수번호도 일치해야 합니다.
- 우선주 등 다른 종류주식이 있는 기업은 보통주 귀속 자본 배분 근거가 부족하면 PBR을 **산출 불가**로 표시합니다. 이 경우에도 보통주 기본 EPS가 명확하면 PER은 계산할 수 있습니다. 보통주 주식 수·자기주식 수 누락, EPS/자본이 0 이하, 모호한 중복 공시 값 등도 이유와 함께 표시합니다.
- 현재 토스의 종목별 발행주식 수와 공시 당시 보통주 발행주식 수를 비교합니다. 분할·증자·소각 등으로 수량이 다르면 EPS/BPS 보정 없이 임의로 계산하지 않고 재확인이 필요하다고 표시합니다.
- 지표는 **최근 12개월(TTM)이 아닌 표시된 사업연도의 연간 실적** 기준입니다. 화면에 기준 연도·결산일·연결/별도, EPS/BPS, 공시 원문 링크와 산출 불가 사유를 제공합니다. 증권사 지표와 기준이 다를 수 있습니다.
- `/api/market/valuations`에서 별도로 조회해 시세·주문 응답이 느린 공시 조회를 기다리지 않게 합니다. 연간 분모는 6시간 캐시하고 가격이 바뀌면 비율을 다시 계산합니다. 실패 결과와 현재 발행주식 정보는 5분 캐시 후 재확인합니다. 실제 시세와 OpenDART 키가 모두 있어야 실제 지표를 표시합니다. 새 API 키는 필요하지 않습니다.

공식 연동 참고: [토스증권 Open API 가이드](https://developers.tossinvest.com/docs), [서버 제공 OpenAPI JSON 명세](https://openapi.tossinvest.com/openapi-docs/latest/openapi.json), [OpenDART 단일회사 전체 재무제표](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS003&apiId=2019020), [Supabase 이메일 인증](https://supabase.com/docs/guides/auth/passwords).

## 게임 규칙

- 자기자본: 기본 1,000만원 (`INITIAL_CAPITAL`로 변경)
- 차근차근: 대출 1,000만원 / 연 4%
- 아슬아슬: 대출 3,000만원 / 연 9%
- 벼랑 끝: 대출 5,000만원 / 연 18%
- 투자 기간: 실제 90일 (`GAME_DAYS`로 변경). ‘다음 날’ 버튼은 없습니다.
- 단리: 미상환 원금 × 연이율 × 실제 경과 초 ÷ (365 × 86400). 로그아웃 중에도 경과 시간을 계산합니다.
- 상환: 누적 이자를 먼저 지급하고 원금을 줄입니다. 만기 이후에도 미상환 원금의 이자는 발생합니다. 만기 후 신규 거래·학습 보상은 중단되며 평가액은 계속 시장 가격으로 표시됩니다.
- 순자산 = 예수금 + 보유주식 평가액 − 대출 원금 − 누적 이자.
- 랭킹 수익률 = (순자산 − 초기 자기자본 − 학습 보상) ÷ (초기 자기자본 + 학습 보상) × 100. 학습 보상이 투자 수익으로 부풀려지지 않습니다.
- 샘플 시세 계정과 실제 시세 계정의 랭킹을 분리합니다. 최대 1,000개 계정 중 상위 100개를 표시합니다. 대규모 사용자 서비스로 확장하려면 DB 집계·페이징을 추가하세요.
- 수업별 정답 보상은 한 번 지급하며, 매매 수수료·세금·호가·슬리피지는 반영하지 않는 교육용 즉시 체결 모델입니다.

가상 대출금·금리는 교육용 제안값입니다. `catalog.py`의 `DIFFICULTIES`에서 변경할 수 있으며 기존 여정에는 적용되지 않습니다.

## 기업 군집화

순이익률(순이익/매출), 기말자본 대비 이익률(순이익/기말 자기자본), 부채비율을 부호를 보존하는 로그 변환·표준화한 후 결정적인 초기값으로 K-means 3개 군집을 계산합니다. 기말자본 대비 이익률은 평균 자기자본을 사용하는 ROE와 다릅니다. 토스 시세에 PER/PBR이 없으므로 시세 API 대신 재무데이터만으로 비교 기능을 유지합니다. 같은 군집과 지표 거리 순으로 비교 기업을 제공합니다. 8개 선정 기업 내 소규모 학습 모델이며 매수 권유나 수익 예측 모델은 아닙니다. 지표가 없거나 비교 가능한 기업이 부족하면 결과를 비웁니다. OpenDART 키가 없으면 샘플 재무데이터 기반임을 표시합니다.

## 구조

```text
backend/app/
  api/routes/platform.py  # 인증, 시세, 주문, 대출, 학습, 랭킹 API
  core/config.py          # 루트 .env 설정
  services/catalog.py     # 선정 종목, 난이도, 학습 콘텐츠
  services/market.py      # 토스 토큰·시세·장 운영, 연간 공시 조회·캐시
  services/valuation.py   # 연간 EPS/BPS와 PER/PBR 근거 검증·계산
  services/store.py       # Supabase / 로컬 SQLite, 인증·동시성
  services/game.py        # 이자, 순자산, 매매·상환 계산
  main.py                 # FastAPI / 정적 빌드 제공
backend/tests/            # 핵심 API와 금융 로직 테스트
frontend/src/
  main.tsx                # React 화면과 사용자 흐름
  api.ts                  # API 클라이언트 및 TypeScript 타입
  valuation.tsx           # 지표·기준 연도·계산 근거·누락 사유 표시
  styles.css              # 반응형 디자인
supabase/migrations/      # 테이블, RLS, 회원가입 트리거, 원자적 저장 함수
scripts/browser-smoke.cjs # 선택적 브라우저 회귀 테스트
```

## 검증

```powershell
.\.venv\Scripts\python.exe -m pytest -q
pnpm run build
```

선택적 UI 테스트는 Playwright와 설치된 Edge가 필요합니다. 두 개발 서버를 실행한 상태에서 `node scripts/browser-smoke.cjs`를 실행합니다. `PLAYWRIGHT_PACKAGE` 환경변수로 기존 Playwright 패키지 경로를 지정할 수도 있습니다. 결과 스크린샷은 Git에서 제외되는 `artifacts/`에 저장합니다.

실제 API 키와 Supabase 프로젝트가 없는 상태에서는 외부 인증·공시·실제 시세의 종단간 테스트는 수행할 수 없습니다. 키 발급 후 회원가입 확인메일, 시세 권한·이용 한도, 공시 연도, SQL 마이그레이션 실행을 확인하세요. 현재 쿠키 설정은 로컬 HTTP 개발용입니다. 공개 배포 시 HTTPS secure 쿠키와 배포 도메인 Origin 설정을 적용해야 합니다.
