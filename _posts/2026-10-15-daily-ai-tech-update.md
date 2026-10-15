---
layout: post
title: "DuckDB와 Apache Arrow 기반 초고속 Text-to-SQL 분석 에이전트: 인메모리 OLAP과 셀프 힐링 쿼리 파이프라인 구축"
date: 2026-10-15 09:00:00 +0900
categories: [DataEngineering, AI]
tags: [TextToSQL, DuckDB, ApacheArrow, DataAgent, OLAP, LLM]
---

자연어를 SQL로 변환하여 데이터를 조회하는 Text-to-SQL 기술은 엔터프라이즈 환경에서 비개발 직군과 데이터 분석가들의 생산성을 혁신할 핵심 솔루션으로 꼽혀왔습니다. 그러나 지금까지의 상용 Text-to-SQL 시스템은 심각한 운영상 병목을 겪어왔습니다. Snowflake, BigQuery 등 고비용 클라우드 데이터 웨어하우스(DW)에 검증되지 않은 LLM 생성 쿼리를 직접 전송하여 불필요한 컴퓨팅 비용과 레이턴시가 발생했고, 잘못된 테이블 조인이나 구문 에러가 발생했을 때 즉각적인 피드백 루프를 형성하기 어려웠습니다.

2026년 현재, 이러한 한계를 극복하기 위해 **DuckDB의 벡터화 임베디드 OLAP 엔진**과 **Apache Arrow의 무복사(Zero-Copy) 인메모리 전송 표준**을 결합한 경량 고성능 분석 에이전트 아키텍처가 급부상하고 있습니다. 이번 포스트에서는 LLM이 생성한 쿼리를 로컬 샌드박스 환경에서 마이크로초 단위로 사전 검증하고, 문법 및 런타임 에러를 스스로 복구(Self-Healing)하며 최종 결과를 시각화 레이어로 직렬화하는 차세대 데이터 엔지니어링 에이전트 파이프라인을 다룹니다.

---

### 1. 임베디드 OLAP과 Apache Arrow: 제로 카피 인메모리 샌드박스

전통적인 RDBMS 기반 접근 방식과 달리, DuckDB는 별도의 데몬 프로세스 없이 애플리케이션 메모리 공간 내에 상주하는 초경량 컬럼형(Columnar) 데이터베이스입니다. Parquet, Iceberg, CSV 파일 등 다양한 데이터 소스를 외부 엔진 기동 없이 직접 고속 스캔할 수 있으며, 최신 SIMD 벡터화 실행 엔진을 통해 수천만 건의 레코드를 수 밀리초 만에 집계합니다.

여기에 **Apache Arrow** 포맷이 결합되면서 데이터 에이전트의 아키텍처적 효율성은 극대화됩니다. DuckDB에서 실행된 쿼리 결과는 메모리 복사(Memory Copy)나 불필요한 역직렬화(Deserialization) 과정 없이 곧바로 Arrow RecordBatch 형태로 전달됩니다.

```
+-------------------------------------------------------+
|  User Natural Language Query                          |
+---------------------------+---------------------------+
                            |
                            v
+-------------------------------------------------------+
|  LLM (Schema-Linked Prompt with Metadata Injection)  |
+---------------------------+---------------------------+
                            | SQL Query Generation
                            v
+-------------------------------------------------------+
|  Sandboxed Local DuckDB Runtime                       |
|  - In-Memory Catalog Validation                       |
|  - Explain Plan & Cost Analysis                       |
|  - Execution on Local Parquet / Arrow Tables          |
+-------------+---------------------------+-------------+
              | (Syntax/Runtime Error)    | (Success)
              v                           v
+-----------------------------+  +----------------------+
| Self-Healing Reflection Loop|  | Apache Arrow Record  |
| - Error Traceback Injection |  | (Zero-Copy Transfer) |
| - SQL Regeneration          |  +----------+-----------+
+-----------------------------+             |
                                            v
                                 +----------------------+
                                 | Polars / Streamlit   |
                                 | Dynamic Visualization|
                                 +----------------------+
```

이 구조 덕분에 LLM 에이전트는 사용자의 자연어 질문을 SQL로 바꾼 뒤 즉시 클라우드 DW에 밀어 넣는 위험을 피할 수 있습니다. 로컬 메모리에 캐싱된 메타데이터 스키마와 대표 샘플 데이터를 기반으로 DuckDB 상에서 안전하게 쿼리를 드라이런(Dry-run)하고 최적화 계획을 검증할 수 있습니다.

---

### 2. 스키마 링킹(Schema Linking)과 의미론적 제약 주입 기법

Text-to-SQL 모델이 실패하는 가장 큰 원인은 테이블 및 컬럼 이름의 모호성, 그리고 도메인 비즈니스 로직(예: '활성 사용자'의 정의)을 모델이 인지하지 못하는 '컨텍스트 부족'입니다.

성공적인 에이전트를 구축하려면 정적 DDL(CREATE TABLE 문)만 프롬프트에 넣어서는 안 됩니다. 시스템 카탈로그에서 추출한 다음 세 가지 의미론적 계층(Semantic Layer)을 동적으로 결합해야 합니다:

1. **컬럼 카디널리티 및 값 분포 요약:** 범주형(Categorical) 컬럼의 고유 값 목록(예: `status IN ('PENDING', 'PAID', 'CANCELLED')`)을 포함하여 LLM이 존재하지 않는 값을 WHERE 절에 필터링하지 않도록 방지합니다.
2. **동적 외래키 맵(Foreign Key Map):** 다대다, 일대다 관계를 방향성 그래프 형태로 제공하여 무분별한 카티션 곱(Cartesian Product) 조인이 발생하는 것을 차단합니다.
3. **도메인 메트릭 계산 룰:** 예컨대 'ARPU(고객당 평균 매출)'라는 단어가 들어왔을 때 `SUM(revenue) / COUNT(DISTINCT user_id)`로 치환할 수 있는 계산 공식을 메타데이터 딕셔너리로 주입합니다.

이러한 메타데이터는 DuckDB의 `information_schema`와 `PRAGMA table_info()`를 통해 프로그래밍 방식으로 추출되어, 입력 프롬프트의 토큰 사용량을 최소화하는 컴팩트한 YAML/JSON 포맷으로 압축 전달됩니다.

---

### 3. 실전 파이프라인 구현: DuckDB + Arrow + LLM 셀프 힐링 에이전트

다음은 Python 3.12 환경에서 DuckDB, Apache Arrow, Pydantic, 최신 LLM 클라이언트를 결합하여 쿼리 실행, 오류 탐지 및 자가 수정(Self-Correction)을 수행하는 실전 Text-to-SQL 분석 에이전트의 완성형 코드입니다.

```python
import duckdb
import pyarrow as pa
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
import json

# ============================================================================
# 1. 스키마 정의 및 인메모리 OLAP 데이터베이스 초기화
# ============================================================================

def setup_in_memory_duckdb() -> duckdb.DuckDBPyConnection:
    """초고속 벡터화 연산을 위한 인메모리 DuckDB 세션 및 샘플 테이블 생성"""
    con = duckdb.connect(database=":memory:")
    
    # 이커머스 샘플 스키마 및 더미 데이터 삽입
    con.execute("""
        CREATE TABLE customers (
            customer_id INTEGER PRIMARY KEY,
            signup_date DATE,
            region VARCHAR,
            segment VARCHAR
        );
        CREATE TABLE orders (
            order_id INTEGER PRIMARY KEY,
            customer_id INTEGER,
            order_date TIMESTAMP,
            total_amount DOUBLE,
            status VARCHAR
        );
        
        INSERT INTO customers VALUES 
            (1, '2025-01-10', 'KR', 'Enterprise'),
            (2, '2025-03-15', 'US', 'SMB'),
            (3, '2025-06-20', 'KR', 'SMB'),
            (4, '2026-01-05', 'EU', 'Enterprise');
            
        INSERT INTO orders VALUES
            (101, 1, '2026-02-01 10:30:00', 12500.0, 'COMPLETED'),
            (102, 1, '2026-03-15 14:20:00', 8300.0, 'COMPLETED'),
            (103, 2, '2026-04-10 09:15:00', 450.0, 'REFUNDED'),
            (104, 3, '2026-05-01 18:00:00', 2100.0, 'COMPLETED'),
            (105, 4, '2026-08-12 11:45:00', 34000.0, 'COMPLETED');
    """)
    return con

# ============================================================================
# 2. 메타데이터 추출기 및 LLM 구조화 출력 스키마 정의
# ============================================================================

def extract_schema_metadata(con: duckdb.DuckDBPyConnection) -> str:
    """DuckDB 시스템 카탈로그로부터 스키마 및 제약 조건을 추출하여 문자열화"""
    tables = con.execute("SHOW TABLES").fetchall()
    schema_info = {}
    
    for (tbl,) in tables:
        cols = con.execute(f"PRAGMA table_info('{tbl}')").fetchall()
        schema_info[tbl] = [{"name": c[1], "type": c[2]} for c in cols]
        
    return json.dumps(schema_info, indent=2)

class SQLGenerationOutput(BaseModel):
    thought_process: str = Field(description="쿼리 작성 논리 및 조인 경로 설명")
    sql_query: str = Field(description="실행 가능한 순수 ANSI/DuckDB SQL 쿼리")

# ============================================================================
# 3. 셀프 힐링(Self-Healing) 실행 엔진
# ============================================================================

class DuckDBTextToSQLAgent:
    def __init__(self, db_con: duckdb.DuckDBPyConnection):
        self.con = db_con
        self.schema_metadata = extract_schema_metadata(self.con)
        
    def _mock_llm_call(self, prompt: str, is_retry: bool = False) -> SQLGenerationOutput:
        """
        학습 목적을 위해 모킹된 LLM 응답 함수.
        실제 환경에서는 OpenAI/Anthropic의 구조화된 출력(Tool Calling / Structured Output)을 연결합니다.
        """
        if not is_retry:
            # 1차 시도: 컬럼명 오타가 포함된 쿼리를 생성하여 에러를 시뮬레이션
            return SQLGenerationOutput(
                thought_process="2026년 한국(KR) 리전 고객들의 총 구매 금액을 합산하기 위해 고객 테이블과 주문 테이블을 조인합니다.",
                sql_query="SELECT c.region, SUM(o.total_amount) AS total_revenue "
                          "FROM customers c JOIN orders o ON c.id = o.customer_id " # c.id(오류: c.customer_id여야 함)
                          "WHERE c.region = 'KR' AND o.status = 'COMPLETED' GROUP BY c.region;"
            )
        else:
            # 2차 시도: 에러 피드백을 반영하여 교정된 SQL 반환
            return SQLGenerationOutput(
                thought_process="이전 런타임 에러(c.id 컬럼 부재)를 확인하고 c.customer_id로 조인 키를 수정했습니다.",
                sql_query="SELECT c.region, SUM(o.total_amount) AS total_revenue "
                          "FROM customers c JOIN orders o ON c.customer_id = o.customer_id "
                          "WHERE c.region = 'KR' AND o.status = 'COMPLETED' GROUP BY c.region;"
            )

    def execute_and_heal(self, user_question: str, max_retries: int = 3) -> pa.Table:
        """SQL을 생성하고 로컬 DuckDB에서 실행하며 오류 시 자가 복구를 수행하는 메인 루프"""
        error_context = ""
        
        for attempt in range(max_retries):
            # 프롬프트 조립
            prompt = (
                f"DB 스키마 메타데이터:\n{self.schema_metadata}\n\n"
                f"사용자 요청: {user_question}\n"
            )
            if error_context:
                prompt += f"\n[이전 실행 실패 피드백]: {error_context}\n오류를 수정한 정확한 쿼리를 다시 작성하세요."

            # LLM 추론 (모킹 인터페이스)
            generation = self._mock_llm_call(prompt, is_retry=(attempt > 0))
            print(f"[시도 {attempt + 1}] 생성된 SQL: {generation.sql_query}")

            try:
                # DuckDB 쿼리 실행 -> Apache Arrow Table로 제로 카피 변환
                arrow_result: pa.Table = self.con.execute(generation.sql_query).arrow()
                print("✓ 쿼리 실행 성공 (Arrow 포맷 반환 완료)")
                return arrow_result
                
            except duckdb.Error as e:
                error_message = str(e)
                print(f"✗ 런타임 오류 감지: {error_message}")
                # 다음 루프에 전달할 디버깅 컨텍스트 주입
                error_context = f"SQL: {generation.sql_query} | Error: {error_message}"

        raise RuntimeError(f"{max_retries}회 재시도 후에도 유효한 쿼리를 생성하지 못했습니다.")

# ============================================================================
# 4. 실행 및 Arrow 결과 파이프라인 연동
# ============================================================================

if __name__ == "__main__":
    db = setup_in_memory_duckdb()
    agent = DuckDBTextToSQLAgent(db)
    
    query = "한국 리전 엔터프라이즈 및 SMB 고객들의 완료된 총 주문 금액을 집계해줘."
    print(f"=== 사용자 요청 처리 시작: '{query}' ===\n")
    
    result_arrow_table = agent.execute_and_heal(query)
    
    print("\n=== 최종 처리된 Apache Arrow 레코드셋 ===")
    print(result_arrow_table.to_pandas())
```

위 파이프라인에서 주목해야 할 부분은 실행 결과가 파이썬 네이티브 튜플이나 딕셔너리로 변환되는 것이 아니라, `arrow()` 메서드를 통해 네이티브 C++ 메모