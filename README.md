# Stock Simulator

Python FastAPI, 실시간 주식 시세 API, Supabase를 사용하는 주식 투자 시뮬레이터입니다.

## 폴더 구조

```text
stock-simulator/
├─ backend/
│  ├─ app/
│  │  ├─ api/routes/   # FastAPI REST 엔드포인트
│  │  ├─ core/         # 환경변수와 공통 설정
│  │  ├─ models/       # DB 모델
│  │  ├─ schemas/      # 요청/응답 데이터 모델
│  │  ├─ services/     # 주식 API와 Supabase 로직
│  │  └─ main.py       # FastAPI 앱 시작점
│  └─ tests/           # 백엔드 테스트
├─ frontend/
│  ├─ assets/          # 이미지와 아이콘
│  ├─ css/             # 스타일시트
│  ├─ js/              # API, 화면, 상태 관리
│  └─ index.html
├─ supabase/
│  ├─ migrations/      # DB 스키마 변경 SQL
│  └─ seed.sql         # 개발용 초기 데이터
├─ .env.example        # 환경변수 이름 예시
├─ .gitignore
└─ backend/requirements.txt
```

## 시작하기

1. `.env.example`을 `.env`로 복사합니다.
2. Supabase URL/키와 주식 API 키를 `.env`에 입력합니다.
3. Python 가상환경 생성 후 의존성을 설치합니다.
4. FastAPI 개발 서버를 실행합니다.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
uvicorn app.main:app --reload --app-dir backend --port 3000
```

API 문서는 `http://localhost:3000/docs`, 상태 확인은
`http://localhost:3000/api/health`에서 할 수 있습니다.

실제 `.env` 파일과 API 키는 Git에 커밋하지 않습니다. 브라우저에서 주식 API 키나 Supabase service-role 키를 직접 사용하지 말고 백엔드를 통해 요청하세요.
