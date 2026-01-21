# 💘 연프 라인 (Yeonpro Line)

> "당신의 예측이 데이터가 되는 순간, 연애 리얼리티의 새로운 라인이 시작됩니다."
> 
> 
> 시청자 참여형 예측 시스템과 실시간 민심 분석을 결합한 데이터 기반 연애 리얼리티 플랫폼
>

## 🌏 Project Overview

- **프로젝트명:** 연프 라인 (Yeonpro Line)
- **개발 기간:** 2026.01.15 ~ 2026.01.21 (KAIST 몰입캠프 2025 Winter · Week 2)
- **주요 서비스:** 라이브 연애 리얼리티 예측 및 실시간 여론 분석 웹 서비스
- **한 줄 소개:** "같이 예측하고, 같이 싸우고, 같이 복기하는" 과몰입 시청자를 위한 필수 동반자

## 프로젝트 구조
- `app/`: FastAPI 앱, 라우터, 모델, 스키마, 설정
- `app/api/endpoints/`: 주요 API 엔드포인트 (`auth`, `predictions`, `sentiment`, `users`, `rankings`, `chat`)
- `app/models/`: ORM 모델 (users, badges, frames, predictions 등)
- `scripts/`: 크롤러 및 운영 스크립트 (`crawl_sentiment.py`)

## 🎯 기획 의도

기존 연애 리얼리티 시청 방식은 단순히 방송을 보고 커뮤니티에서 대화하는 것에 그쳤습니다. 연프 라인은 시청자의 '촉'을 포인트와 랭킹으로 연결하고, 흩어진 여론을 데이터 시각화로 보여줌으로써 시청 경험을 한 단계 끌어올리기 위해 기획되었습니다.

## 🛠️ Tech Stack

### 🎨 Frontend

- Next.js (App Router)
- NextAuth
- Tailwind CSS
- Recharts
- Lucide Icons

### ☁️ Backend & Infra

- FastAPI
- SQLAlchemy
- Pydantic
- PostgreSQL
- Uvicorn
- WebSocket

### 🔑 **Auth**

- Google OAuth
- JWT

### **🤖 AI/Analytics**

- Gemini API (감성 요약)
- 크롤러(Python + BeautifulSoup)

🗄️ Database Schema (핵심 구조)

## 📱 Screen Definition (주요 화면 설계)
| **화면명** | **주요 구성 및 목적** |
| --- | --- |
| **1. 예측** | 예측 마감 카운드타운 타이머, 시즌 시작 예측, 시즌 최종 투표, 회차별 예측  |
| **2. 민심** | 출연자 선택 탭, 민심 변화 그래프, AI 여론 요약 |
| **3. 채팅** | 실시간 채팅 |
| **4. 순위** | 전체 유저 랭킹, 포인트샵 |
| **5. 내 정보** | 프로필, 획득한 배지, 예측 히스토리 |


## 실행 방법
1) 환경 변수 설정 (`.env`)
```env
sqlalchemy_database_url=postgresql://USER:PASSWORD@HOST:5432/DBNAME
google_client_id=...
google_client_secret=...
jwt_secret_key=...
gemini_api_key=...
```

2) 서버 실행
```bash
uvicorn app.main:app --reload
```

3) 민심 크롤러 실행 (예시)
```bash
PYTHONPATH=. python scripts/crawl_sentiment.py --pages 660,290 --page-count 1 --episode-id 18
```

## 주요 기능
- 예측: 시즌/회차 예측, 특수 베팅, 정답 채점 및 포인트 지급
- 민심 분석: 크롤링 → 요약/스냅샷/이벤트 적재
- 랭킹/프로필: 배지/프레임, 포인트, 적중률 통계
- 포인트 샵: 배지/프레임 구매 및 보유/선택 관리

## 개발 가이드
- **언어/스타일**: Python 3, FastAPI, Pydantic 스키마 중심 설계
- **네이밍**: 스키마/모델은 `snake_case`, 라우터는 `/users`, `/predictions` 등 REST 스타일
## 참고
- 프론트엔드: `../yeonproLine_front`
