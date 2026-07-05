# AI Altcoin Research Agent v2

"지금 좋은 코인"이 아니라 **펀더멘털(온체인 활동·사용자·개발)은 오르고 있는데
가격은 아직 반영되지 않은 코인**을 선행 발굴하는 리서치 에이전트.

- 최종 산출물: 정적 JSON + 정적 웹사이트
- GitHub Actions가 매일 KST 07:00 / 19:00에 재생성해 배포 (상시 서버 없음)
- 가격 예측이나 매수/매도 지시는 하지 않음

## Stage 1 범위

- 프로젝트 스캐폴딩, 설정/로깅/파일 캐시
- 데이터 소스 클라이언트 (CoinGecko, DefiLlama, GitHub, RSS, 유료 소스 mock)
- Top300 수집 + 필터링 파이프라인
- 시계열 스냅샷 저장 + 30/90일 백필 (변화율 계산의 전제)

## Stage 2 범위

- 공통 인터페이스(`BaseAnalyzer`/`AnalysisContext`)를 따르는 Analyzer 8종
  (OnChainGrowth, UserEcosystem, Developer, Catalyst, Valuation, News, Technical, Risk)
- 모든 지표는 절대값이 아니라 **30일/90일 변화율**로 평가 (가격 모멘텀은 점수 요인 아님)
- 데이터가 없으면 추정하지 않고 `null` + 사유 기록 — Hallucination 0% 원칙
- Catalyst/News/Risk는 LLM 배치 호출로 뉴스 헤드라인을 분류 (Anthropic API, 키 없으면 결측 처리)
- `python -m pipeline.analyze`: Top300 전체를 async 병렬로 분석해 `data/latest/analysis.json` 생성

## Stage 3 범위

- **VPD (Value-Price Divergence)**: 온체인·사용자·개발 지표의 30일 변화율 가중평균(FG)과
  동일 기간 가격변화율(PG)을 유니버스 내 z-score로 표준화해 `VPD = FG_z − PG_z`를 계산하고,
  4사분면(선행기회/동반상승/순수펌핑/침체)으로 분류해 evidence에 기록
- **점수 모델 v2**: 100점 만점, 전 영역 유니버스 내 백분위 정규화
  (온체인 25 · VPD 20 · 개발자 15 · 사용자 10 · 촉매 10 · 밸류에이션 10 · 리스크 10). Technical은 0점
- **Entry Feasibility Filter(과열 필터)**: 점수 계산 "이후" 최종 랭킹 단계에서 적용.
  30일 +60%/90일 +150% 초과 코인은 Top20 후보에서 제외해 `momentum_leaders`로 별도 저장하고,
  RSI·200일MA·90일고점 조건은 감점으로 처리. 제외 후 후보가 20개 미만이면 제외 규칙을
  감점으로 완화해 재랭킹
- **Explainability**: 모든 점수를 "카테고리별 기여 점수 + 근거" 쌍으로 분해해 저장(`breakdown`),
  `summary` 필드에 "총점 = 온체인 +19 + VPD +17 + ... + 과열필터 −0" 형태로 합산 공식을 제공
- **Confidence Score**: 데이터 커버리지 + 소스 신선도 + 소스 간 일관성을 합성한 0~100 신뢰도 점수
- `python -m pipeline.rank`: Stage2 산출물을 읽어 Top20 + momentum_leaders를 `data/latest/ranking.json`으로 저장

## Stage 4 범위

- **Reason Generator v2**: Top20 각 코인에 대해 점수 분해(breakdown)와 근거 데이터만 입력으로
  LLM이 한국어 설명(선행 근거 요약/코인 개요/상세 이유/리스크 요약/AI 총평)을 생성
- **3중 필터**: (a) 프롬프트에 "제공된 데이터 밖 수치·사실 생성 금지" 명시 (b) 응답 내 모든 수치를
  입력 데이터와 자동 대조해 불일치 시 재생성(최대 2회), 끝까지 실패하면 그 필드만 결측 처리
  (c) 금지 표현 필터 — 직접 매수/매도 지시, "이미 N% 상승했으므로 추천" 류 후행적 근거(v2 신규, P1 재발 방지)
- **LLM 모듈 provider 추상화**: `LLMProvider` 인터페이스 + `AnthropicProvider` 구현체로 벤더 교체 가능,
  회당 호출 수 상한(`explain.max_llm_calls_per_run`)으로 비용 통제
- **정적 JSON 생성기**(`python -m pipeline.publish`): Stage1(설명/체인/출시연도) + Stage2(촉매 원자료) +
  Stage3(점수)를 조인해 `frontend/public/data/`에 `recommendations.json`, `coins/{id}.json`, `market.json`
  (BTC/ETH 도미넌스 + Fear&Greed), `momentum-leaders.json`, `meta.json`, `history/{date}-{am|pm}.json`을 생성
- 전 회차 `recommendations.json`과 비교해 신규 진입(NEW)/이탈/순위 변동을 계산
- `python -m pipeline.run_all`: collect→analyze→rank→publish 원커맨드. 한 단계라도 실패하면
  그 이후 단계는 실행되지 않고 이전 산출물이 그대로 보존됨 (각 스테이지가 결과를 메모리에서
  전부 구성한 뒤 마지막에만 파일을 쓰기 때문)
- v1과 달리 상시 API 서버는 배포하지 않는다 — 파이프라인이 정적 JSON을 생성하면 끝이며,
  프론트엔드는 이를 직접 fetch한다 (로컬 미리보기는 정적 서버로 충분해 별도 백엔드 서버가 필요 없음)

## Stage 5 범위

- **프론트엔드**(React + Vite + Tailwind, `frontend/`): Dashboard(Top20 카드·시장심리바·모멘텀리더),
  Coin Detail(개요·FG/PG 차트·점수 waterfall·스파크라인·촉매·Confidence 게이지), Watchlist(localStorage)
- **PWA**: `vite-plugin-pwa`로 manifest + service worker 생성 — 홈 화면 추가, 오프라인 시 마지막 캐시 표시
- **간이 접근 게이트**: 프론트 빌드 시 주입되는 패스코드(`VITE_ACCESS_PASSCODE`) — 완전한 보안 아님(하단 참고)
- **GitHub Actions**(`.github/workflows/update.yml`): 매일 KST 07:00/19:00 자동 실행
  (`run_all` → 데이터 커밋 → 프론트 빌드 → GitHub Pages 배포), 실패 시 배포 스킵으로 이전 사이트 유지

## 프로젝트 구조

```
backend/
  common/        # config, logging, file cache, llm_client(provider 추상화)
  datasources/   # 외부 API 클라이언트 (재시도/백오프/캐시 공통 처리)
  analyzers/     # BaseAnalyzer 계약을 따르는 Analyzer 8종
  pipeline/      # collect/analyze/scoring/rank/explain(Reason Generator)/publish/run_all
tests/           # 클라이언트/필터/백필/Analyzer/스코어링/랭킹/설명생성/발행 유닛 테스트
data/
  history/raw/   # 매 실행 스냅샷: {date}.json (시계열 원본)
  analysis/      # 매 실행 분석 결과: {date}.json
  ranking/       # 매 실행 랭킹 결과: {date}.json
  latest/        # 최신 top300.json / analysis.json / ranking.json (파이프라인 내부용)
frontend/
  public/data/   # 최종 정적 산출물 (recommendations/coins/market/momentum-leaders/meta/history)
  public/icons/  # PWA 아이콘 (임시 플레이스홀더 — 실제 브랜딩으로 교체 권장)
  src/
    pages/       # Dashboard / CoinDetail / Watchlist
    components/  # CoinCard, ScoreWaterfall, FgPgChart, Sparkline, ConfidenceGauge 등
    lib/         # useJsonData(fetch 훅), watchlist(localStorage), format
.github/workflows/update.yml # 스케줄 실행 + Pages 배포 워크플로 (Stage 5)
config.yaml      # 필터 · LLM · 스코어링 가중치 · 과열 필터 · Reason Generator · 발행 경로 설정
```

## 로컬 실행

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev,llm]" # llm extra는 Catalyst/News/Risk/Reason Generator의 실제 LLM 호출에 필요 (없어도 동작함)
cp .env.example .env        # 필요 시 API 키 채우기

python -m pipeline.run_all  # Stage1~4 전체 (collect->analyze->rank->publish) 한 번에 실행
# 또는 단계별로:
python -m pipeline.collect  # Stage1: Top300 수집 + 시계열 백필
python -m pipeline.analyze  # Stage2: Analyzer 8종 배치 실행 (collect 산출물 필요)
python -m pipeline.rank     # Stage3: VPD·과열필터·Confidence 반영해 Top20 산출 (analyze 산출물 필요)
python -m pipeline.publish  # Stage4: Reason Generator + frontend/public/data/ 생성 (rank 산출물 필요)
python -m pytest
```

### 프론트엔드 로컬 실행

`frontend/public/data/`에 위 파이프라인 산출물이 있어야 화면에 데이터가 표시됩니다.

```bash
cd frontend
npm install
cp .env.example .env.local   # 접근 게이트를 쓰려면 VITE_ACCESS_PASSCODE 설정 (비워두면 게이트 비활성화)
npm run dev                  # 개발 서버 (핫리로드)
npm run build && npm run preview  # 프로덕션 빌드 + 미리보기 (배포 전 최종 확인용)
```

`npm run dev`/`preview`로 Dashboard → 코인 상세 → 워치리스트 순으로 클릭해보며 라우팅과
데이터 fetch, 워치리스트 등록/삭제, JSON 내보내기/가져오기가 동작하는지 확인하세요.

## 데이터 소스

| 소스 | 용도 | 비고 |
|---|---|---|
| CoinGecko | 가격/시총/거래량, Top300 유니버스, 과거 스냅샷(백필) | 무료 데모 API 키 지원(`COINGECKO_API_KEY`) |
| DefiLlama | TVL, 프로토콜 fees, 스테이블코인 발행량 | API 키 불필요 |
| GitHub API | 커밋 활동, 스타 수 | `GITHUB_TOKEN` 없으면 60 req/h로 제한되므로 발급 권장 |
| CoinDesk/CoinTelegraph RSS | 뉴스 헤드라인 (참고용) | - |
| Santiment 등 유료 소스 | 소셜 볼륨, 개발자 활동 | 인터페이스만 구현, API 키 없으면 mock 사용 |

모든 클라이언트는 24시간 TTL 파일 캐시(`.cache/`)와 지수 백오프 재시도를 공유하며,
소스 하나가 실패해도 나머지 파이프라인은 계속 진행됩니다 (fallback).

## 시계열 백필 동작 방식

1. `data/history/raw/{오늘-N일}.json`이 로컬에 이미 있으면 그 값을 기준값으로 사용.
2. 없으면 (최초 실행 등) CoinGecko `/coins/{id}/history`, DefiLlama TVL 히스토리로
   해당 시점 값을 직접 조회해 소급 확보.
3. 그마저 실패하면 해당 지표는 `null`로 결측 처리하고 `data_flags`에 사유를 남김.

## 설정 조정

필터 기준(최소 거래량, 스테이블코인/랩드 토큰/스캠 판별), 캐시 TTL, HTTP 재시도,
스코어링 가중치, 스케줄 등은 모두 [`config.yaml`](config.yaml)에서 코드 수정 없이 조정 가능합니다.

## Analyzer 8종과 Hallucination 0% 원칙

각 Analyzer는 `AnalysisContext`(코인 스냅샷 · 섹터 동료 · 관련 헤드라인 · 데이터소스 클라이언트)만
입력받고 서로를 참조하지 않습니다. 출력은 항상 `{metrics, evidence, data_quality}` 형태이며,
계산할 수 없는 지표는 추정치를 만들어내지 않고 `null`과 함께 `data_quality.notes`에 사유를 남깁니다.

| Analyzer | 핵심 지표 | 비고 |
|---|---|---|
| OnChainGrowth | TVL/스테이블코인 유입 30·90일 변화율 | 활성주소·거래수·신규홀더·거래소 순유출입은 무료 소스 미지원으로 항상 결측 |
| UserEcosystem | DefiLlama fees 30·90일 변화율 | DAU는 무료 소스 미지원으로 항상 결측 |
| Developer | GitHub 커밋 페이스(30일 vs 90일), 컨트리뷰터, 릴리즈 빈도 | |
| Catalyst | 뉴스에서 메인넷/업그레이드/토큰이코노미/파트너십 추출 | LLM 배치 호출, 날짜·출처 포함. LLM 미가용 시 헤드라인만 evidence로 남기고 결측 |
| Valuation | MC/TVL, MC/Fees(연환산), FDV/MC의 섹터 내 백분위 | 동료 표본 5개 미만이면 백분위는 결측 |
| News | 헤드라인 감성(긍정/부정/중립) + 영향도 | LLM 배치 호출 |
| Technical | RSI(14), 200일 MA 괴리율, 30·90일 수익률, 90일 고점 대비 위치 | **점수 산정에 사용하지 않음** — 과열 필터 입력값 및 상세 페이지 참고용 |
| Risk | 유동성 비율(직접 계산), 해킹/규제 이슈(LLM 추출) | Token Unlock·고래 집중도는 무료 소스 미지원으로 항상 결측 |

Catalyst/News/Risk의 LLM 분류는 `ANTHROPIC_API_KEY`가 없거나 `llm.enabled: false`면
자동으로 비활성화되며, 이 경우도 추측 대신 명시적 결측으로 처리됩니다.

## 점수 모델 v2, VPD, 과열 필터 (Stage 3)

### VPD (Value-Price Divergence)

- **FG (Fundamental Growth)**: OnChainGrowth(TVL·스테이블코인 유입), UserEcosystem(fees),
  Developer(커밋 가속도)의 30일 변화율을 `scoring.fg_weights`로 가중평균. 일부 지표가
  결측이면 남은 지표의 가중치를 재정규화해 평균을 낸다. 전부 결측이면 FG는 결측.
- **PG (Price Growth)**: TechnicalAnalyzer의 30일 가격 수익률.
- FG/PG를 유니버스 전체에서 각각 z-score로 표준화한 뒤 `VPD = FG_z − PG_z`를 계산하고,
  유니버스 내 백분위로 환산해 20점 만점에 반영한다.
- 4사분면 분류(evidence에 기록, 점수에는 VPD 백분위가 이미 반영되어 있어 별도 가감 없음):
  - **선행 기회** (FG↑ PG↓): VPD가 가장 높은 구간 → 최고 점수
  - **동반 상승** (FG↑ PG↑): 중립
  - **순수 펌핑** (FG↓ PG↑): VPD가 가장 낮은 구간 → 최저 점수
  - **침체** (FG↓ PG↓)

### 점수 모델 v2 (100점)

온체인 25 · VPD 20 · 개발자 15 · 사용자·생태계 10 · 촉매 10 · 상대 저평가(Valuation) 10 · 리스크 10
(리스크는 위험도가 낮을수록 고득점). 각 영역은 유니버스 내 백분위로 정규화하며, 동점(tie)이
많은 지표(예: 촉매·리스크 플래그가 0인 코인이 다수)는 mid-rank 방식으로 처리해 다수가 부당하게
최상위 근처 점수를 받지 않도록 한다. 코인에 해당 카테고리 데이터가 전혀 없으면 벌점도 가점도
아닌 중립 점수(`neutral_score_ratio`, 기본 50%)를 부여하고 `breakdown[...].missing`에 표시한다.
Technical(RSI/MA/수익률)은 점수에 반영하지 않는다.

### Entry Feasibility Filter (과열 필터)

점수 계산 **이후**, 최종 랭킹 단계에서만 적용한다 (`config.yaml`의 `overheat_filter`).

1. 30일 수익률 > 60% 또는 90일 수익률 > 150% → Top20 후보에서 제외하고 `momentum_leaders`로 저장
2. RSI(14) > 75 / 200일 MA 대비 +80% 이상 / 90일 고점 −5% 이내 → 각각 감점(기본 −5/−5/−3)
3. 1번 제외 이후 후보가 `ranking.top_n`(기본 20) 미만이면, 하드 제외 대신
   `overheat_filter.relaxed_penalty`의 감점으로 완화해 전체를 재랭킹한다 (제외된 코인 없음)

**회귀 방지**: "30일 +60% 이상 상승한 코인은 Top20에 없다"는 [`tests/test_rank_pipeline.py`](tests/test_rank_pipeline.py)에서
항상 검증한다 (완화 모드가 아닌 정상 조건에서).

### Explainability & Confidence

각 코인의 랭킹 결과에는 카테고리별 `{weight, points, raw_value/percentile, reason}`로 구성된
`breakdown`과, "총점 X = 온체인 +.. + VPD +.. + ... + 과열필터 −.." 형태의 `summary` 문자열이
함께 저장된다. `confidence.score`(0~100)는 데이터 커버리지·소스 신선도·FG 하위 신호 간 방향
일관성을 합성한 엔지니어링 휴리스틱으로, 코인 자체에 대한 사실 주장이 아니라 "이 점수를
얼마나 신뢰할 수 있는가"를 나타낸다.

## Reason Generator v2와 정적 JSON (Stage 4)

### 3중 필터

[`pipeline/explain.py`](backend/pipeline/explain.py)는 코인 하나당 LLM을 한 번 호출해 7개 필드
(`leading_evidence_summary`, `one_liner`, `description_summary`, `primary_use_case`,
`detailed_reasons`, `risk_summary`, `ai_summary`)를 한꺼번에 생성하고, 각 필드를 독립적으로 검증한다.

1. **프롬프트 지시**: 시스템 프롬프트에 "제공된 데이터에 없는 수치·사실 생성 금지",
   "매수/매도 직접 지시 금지", "이미 올랐으므로 유망하다는 후행적 근거 금지"를 명시.
2. **수치 대조 검증**: 점수 분해·기술지표·가격·컨피던스 등 입력 데이터에 등장하는 모든 숫자를
   허용 집합으로 만들고(반올림 변형 포함), 생성된 텍스트에서 정규식으로 추출한 숫자가
   허용 집합과 5%(또는 절대 0.5) 오차 이내로 일치하는지 대조한다. 불일치하면 그 필드만 재생성.
3. **금지 표현 필터**: 정규식으로 직접 매수/매도 지시를 탐지하고, "상승/급등" 동사 + 퍼센트 +
   "추천/매수/유망" 단어가 한 문장에 동시에 나타나면 후행적 근거로 판단해 걸러낸다.

필드별로 최대 3회(최초 1회 + 재생성 2회) 시도하며, 통과한 필드는 유지하고 끝까지 실패한
필드만 `null` + `field_status`에 위반 사유를 남긴다 (전체를 폐기하지 않음). 카테고리/체인/출시연도는
LLM이 아니라 코드로 직접 계산해 애초에 환각 위험이 없다. 향후 촉매 목록은 Stage2 CatalystAnalyzer의
원자료를 그대로 노출하며 LLM이 재작성하지 않는다.

### 정적 JSON 산출물 (`frontend/public/data/`)

| 파일 | 내용 |
|---|---|
| `recommendations.json` | Top20 요약(점수·Confidence·선행근거 1줄·NEW뱃지·순위변동), `exited_since_last_run` |
| `coins/{id}.json` | 코인 상세 전체 (개요·점수분해·상세이유·리스크·촉매·AI총평·field_status) |
| `market.json` | BTC/ETH 도미넌스, 시가총액, Fear & Greed Index |
| `momentum-leaders.json` | 과열 필터로 제외된 코인 (참고용) |
| `meta.json` | 마지막/다음 갱신 시각(KST), 상태, LLM 가용 여부, AI 요약 커버리지 |
| `history/{date}-{am|pm}.json` | 회차별 Top20 스냅샷 (`publish.history_retention_days`, 기본 90일 보관) |

NEW 뱃지/순위 변동은 **직전에 발행된** `recommendations.json`과 비교해 계산한다 (없으면 전부 NEW).
모든 파일은 메모리에서 전부 구성한 뒤 마지막에 한 번에 쓰기 때문에, 생성 도중 실패하면
`frontend/public/data/`는 이전 상태 그대로 남는다.

## 프론트엔드, PWA, 배포 자동화 (Stage 5)

### 화면 구성

- **Dashboard** (`/`): 마지막 업데이트/다음 갱신 시각, BTC/ETH 도미넌스·Fear&Greed 바, Top20 카드
  (순위·점수·Confidence·선행근거 1줄·NEW뱃지·순위 ▲▼), 접혀있는 모멘텀 리더 섹션("참고용 — 추천 아님")
- **Coin Detail** (`/coins/:coinId`): 개요 카드(소개·카테고리·체인·용도·시총·현재가), FG vs PG 이중
  라인 차트, 점수 분해(클릭하면 근거 텍스트 펼쳐짐), 지표 30/90일 스파크라인, 상세 이유, 리스크 요약,
  촉매 캘린더, "점수 미반영" 라벨이 붙은 참고용 Technical 지표, AI 총평, Confidence 게이지
- **Watchlist** (`/watchlist`): localStorage 기반 등록/삭제, 최신 Top20과 대조한 순위 변동 표시,
  JSON 내보내기/가져오기 (기기 간 자동 동기화는 없다는 점을 화면에 명시)
- 전 화면 상단에 "본 서비스는 투자 조언이 아니며 정보 제공 목적입니다" 고지 배너 고정

FG vs PG 차트는 `frontend/public/data/history/`에 누적되는 회차별 스냅샷(각 항목에 `fg_raw_pct`,
`pg_raw_pct` 포함)을 모아 그린다. 정적 호스팅은 디렉터리 목록을 제공하지 않으므로
`history/index.json`(어떤 회차 파일이 있는지 목록)을 먼저 읽고, 그 목록의 파일들만 fetch한다.
파이프라인이 갓 시작되어 회차가 1개뿐이면 그래프 대신 최신 값만 안내 문구로 보여준다(데이터를
지어내지 않음).

### 간이 접근 게이트 — 보안 주의

`VITE_ACCESS_PASSCODE` 환경변수를 설정하면 첫 진입 시 코드 입력 화면이 뜬다. **이것은 완전한
보안이 아니다**: 값이 프론트엔드 빌드 산출물(JS 번들)에 그대로 포함되므로, 브라우저 개발자 도구로
번들을 열어보면 누구나 코드를 알아낼 수 있다. 정말 민감한 정보를 다루거나 접근을 확실히 막아야
한다면 별도의 인증(OAuth, IP 제한 등)이 필요하며, 이 게이트는 검색엔진 노출이나 우연한 방문을
막는 수준의 "가벼운 잠금"으로만 사용해야 한다. 값을 비워두면 게이트 자체가 꺼진다.

### GitHub 배포 설정 절차

1. **Secrets 등록** (Settings → Secrets and variables → Actions → New repository secret)
   | Secret | 필수 여부 | 용도 |
   |---|---|---|
   | `COINGECKO_API_KEY` | 권장 | 무료 데모 키. 없어도 동작하지만 레이트리밋으로 느려짐 |
   | `ANTHROPIC_API_KEY` | 선택 | Catalyst/News/Risk 분류 + Reason Generator 실제 생성에 필요. 없으면 관련 필드가 결측 처리됨 |
   | `VITE_ACCESS_PASSCODE` | 선택 | 프론트 접근 게이트 코드. 비워두면 게이트 비활성화 |

   `GITHUB_TOKEN`은 Actions가 각 실행마다 자동으로 발급하므로 별도로 등록할 필요가 없다
   (워크플로에서 우리 앱의 GitHub API 호출용으로 그대로 재사용해 레이트리밋을 올린다).

2. **저장소 쓰기 권한 확인** (Settings → Actions → General → Workflow permissions)
   "Read and write permissions"를 선택해야 파이프라인이 갱신한 `data/`, `frontend/public/data/`를
   워크플로가 다시 저장소에 커밋할 수 있다.

3. **GitHub Pages 활성화** (Settings → Pages → Build and deployment → Source: **GitHub Actions**)
   별도 브랜치 설정은 필요 없다 — 워크플로가 `actions/deploy-pages`로 직접 배포한다.

4. **최초 수동 실행**: Actions 탭 → "Update Data and Deploy" 워크플로 선택 → **Run workflow** 버튼으로
   `workflow_dispatch`를 1회 실행한다. 완료되면 Settings → Pages에 표시된 고정 URL
   (`https://<계정>.github.io/<저장소명>/`)에서 사이트를 확인할 수 있다.

5. **정기 실행 확인**: Actions 탭의 워크플로 상세 페이지에서 다음 예약된 cron 실행이 "Scheduled"로
   표시된다 (`50 21 * * *`, `50 9 * * *` UTC = KST 06:50/18:50 트리거, 파이프라인 실행 후 07:00/19:00
   전후로 반영). 스케줄 실행은 저장소에 최근 활동이 있어야 GitHub가 계속 활성 상태로 유지한다는
   점(60일 이상 비활성 저장소는 스케줄이 자동 중지됨)을 참고한다.

### 실패 시 동작

파이프라인(`run_all`) 단계가 실패하면 그 이후의 커밋/빌드/배포 스텝은 전혀 실행되지 않는다
(GitHub Actions가 실패한 스텝 이후를 자동으로 건너뜀) — 이전에 배포된 사이트가 그대로 유지된다.
실패는 Actions 탭에 빨간 표시로 남고, 저장소 알림 설정(기본값)에 따라 이메일 등으로 통지된다.
`timeout-minutes: 30`으로 한 회 실행이 30분을 넘기면 강제 종료되어 역시 실패로 처리된다.

### PWA 설치 확인

배포된 사이트에 모바일 브라우저로 접속한 뒤 "홈 화면에 추가"(iOS Safari) 또는 자동으로 뜨는
설치 배너(Android Chrome)를 사용하면 앱처럼 아이콘이 생기고 standalone 모드로 실행된다.
오프라인이거나 네트워크가 불안정하면 서비스 워커가 마지막으로 성공한 `data/*.json` 응답을 보여준다
(`vite.config.js`의 `NetworkFirst` 캐싱 전략). `frontend/public/icons/`의 아이콘은 자리표시용
단색 로고이니 실제 배포 전에 브랜드 아이콘으로 교체하는 것을 권장한다.
