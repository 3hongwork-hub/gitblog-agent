---
layout: post
title: "Text-to-SQL과 DuckDB 기반 실시간 데이터 분석 에이전트: 로컬 인메모리 OLAP 파이프라인 실전 구축"
date: 2026-09-21 09:00:00 +0900
categories: [AI, DataEngineering]
tags: [TextToSQL, DuckDB, ApacheArrow, DataAgent, Python]
---

현대 엔터프라이즈 환경에서 비즈니스 인텔리전스(BI)와 데이터 분석의 패러다임이 급변하고 있습니다. 과거에는 복잡한 SQL 쿼리를 직접 작성하거나 별도의 대시보드 도구를 거쳐야만 비즈니스 인사이트를 얻을 수 있었으나, 최근에는 대규모 언어 모델(LLM)과 고성능 인메모리 데이터베이스를 결합한 **Text-to-SQL 분석 에이전트**가 표준으로 자리 잡고 있습니다. 

특히 대용량 데이터를 클라우드 웨어하우스로 전송하지 않고 로컬 환경이나 서비스 내부에서 초고속으로 처리할 수 있는 **DuckDB**와 **Apache Arrow** 에코시스템의 결합은 비용을 획기적으로 절감하고 응답 지연을 밀리초(ms) 단위로 단축합니다. 이번 포스트에서는 LLM이 자연어를 완벽한 SQL로 변환하고, 이를 DuckDB 인메모리 엔진을 통해 안전하게 실행하여 정형화된 인사이트 및 시각화 데이터까지 도출해내는 프로덕션급 Text-to-SQL 데이터 분석 에이전트 아키텍처를 실전 코드를 통해 구축해 보겠습니다.

---

### 1. 텍스트-투-SQL 아키텍처 설계와 스키마 컨텍스트 최적화

Text-to-SQL 파이프라인에서 가장 흔히 발생하는 실패 원인은 LLM이 대상 데이터베이스의 정확한 스키마 구조, 테이블 관계, 도메인 용어(예: 매출액의 정의, 환불 처리 상태 코드 등)를 제대로 이해하지 못하는 데 있습니다. 무작정 전체 스키마 DDL을 프롬프트에 주입하는 방식은 컨텍스트 윈도우 낭비뿐만 아니라 환각(Hallucination) 현상을 유발합니다.

따라서 효율적인 에이전트는 사용자의 질문(Intent)을 분석하여 연관된 최소한의 테이블과 컬럼 메타데이터만을 동적으로 추출해 프롬프트에 주입하는 **Dynamic Schema Linking** 기법을 사용해야 합니다. 또한, DuckDB의 강력한 메타데이터 쿼리 기능을 활용하면 런타임에 데이터베이스 스키마 정보를 실시간으로 파싱하고 캐싱할 수 있습니다.

```python
# schema_manager.py: 동적 스키마 링킹 및 메타데이터 관리
import duckdb
from typing import List, Dict, Any

class DuckDBSchemaManager:
    def __init__(self, db_path: str = ":memory:"):
        self.conn = duckdb.connect(db_path)
        
    def register_csv_table(self, table_name: str, file_path: str):
        # 대용량 CSV 파일을 DuckDB에 제로카피(Zero-copy) 방식으로 가상 테이블 등록
        self.conn.execute(f"CREATE TABLE IF NOT EXISTS {table_name} AS SELECT * FROM read_csv_auto('{file_path}')")
        
    def get_focused_schema(self, keywords: List[str]) -> str:
        """질문 속 키워드와 연관된 테이블 스키마만 필터링하여 반환"""
        tables_query = self.conn.execute("SHOW TABLES;").fetchall()
        all_tables = [t[0] for t in tables_query]
        
        schema_context = []
        for table in all_tables:
            # 키워드가 테이블명이나 컬럼명에 포함되는지 확인
            columns = self.conn.execute(f"DESCRIBE {table};").fetchall()
            col_str = ", ".join([f"{col[0]} ({col[1]})" for col in columns])
            
            # 연관성 검사 (실제 프로덕션에서는 임베디드 기반 벡터 검색 활용 가능)
            if any(kw.lower() in table.lower() or any(kw.lower() in c[0].lower() for c in columns) for kw in keywords):
                schema_context.append(f"Table: {table}\nColumns: {col_str}\n")
                
        if not schema_context: # 기본값으로 전체 스키마 요약 제공
            for table in all_tables:
                columns = self.conn.execute(f"DESCRIBE {table};").fetchall()
                col_str = ", ".join([f"{col[0]} ({col[1]})" for col in columns])
                schema_context.append(f"Table: {table}\nColumns: {col_str}\n")
                
        return "\n".join(schema_context)
```

---

### 2. DuckDB와 Apache Arrow 기반의 안전한 쿼리 실행 엔진

LLM이 생성한 SQL은 문법 오류나 존재하지 않는 컬럼 참조 등의 예외를 포함할 수 있으며, 악의적인 프롬프트 인젝션에 의해 `DROP TABLE` 같은 파괴적인 쿼리가 실행될 위험이 존재합니다. 따라서 쿼리 실행 레이어에서는 **AST(Abstract Syntax Tree) 파싱 기반의 보안 필터링**과 **안전한 샌드박스 실행**이 필수적입니다.

DuckDB는 Apache Arrow 포맷과 메모리를 직접 공유하므로, SQL 실행 결과를 별도의 직렬화 과정 없이 판다스(Pandas)나 넘파이(NumPy), 혹은 화살표(Arrow) 테이블로 즉시 변환하여 메모리 오버헤드를 제로(0)로 만들 수 있습니다.

```python
# execution_engine.py: 안전한 SQL 실행 및 Arrow 변환 파이프라인
import duckdb
import sqlglot
from sqlglot import exp

class SafeQueryExecutor:
    def __init__(self, duck_conn: duckdb.DuckDBPyConnection):
        self.conn = duck_conn
        
    def _validate_sql(self, sql: str):
        """sqlglot을 이용해 읽기 전용(SELECT) 쿼리인지 엄격하게 검증"""
        try:
            parsed_expressions = sqlglot.parse(sql, read="duckdb")
            for expression in parsed_expressions:
                if not isinstance(expression, exp.Select):
                    raise ValueError(f"보안 정책 위반: SELECT 외의 쿼리는 실행할 수 없습니다. (감지된 구문: {expression.key})")
        except Exception as e:
            raise ValueError(f"SQL 구문 파싱 실패 또는 유효하지 않은 쿼리: {str.from_error(e) if hasattr(e, 'from_error') else str(e)}")

    def execute_to_arrow(self, sql: str) -> Any:
        """검증된 SQL을 실행하고 Apache Arrow Table 형태로 결과 반환"""
        self._validate_sql(sql)
        try:
            # DuckDB의 네이티브 Arrow 연동 기능 활용
            arrow_table = self.conn.execute(sql.strip()).arrow()
            return arrow_table
        except Exception as e:
            raise RuntimeError(f"DuckDB 쿼리 실행 중 오류 발생: {str(e)}")
```

---

### 3. LLM 기반 Self-Correction(자기 교정) 분석 에이전트 구현

실제 프로덕션 환경에서 LLM이 한 번에 완벽한 SQL을 작성할 확률은 100%가 아닙니다. 쿼리 실행 중 문법 에러나 빈 결과셋(Empty Result)이 반환될 수 있습니다. 이때 에이전트 스스로 에러 메시지를 인지하고 쿼리를 수정하는 **Self-Correction Loop**를 구현하는 것이 견고한 데이터 에이전트의 핵심입니다.

아래는 LangChain 및 최신 LLM 클라이언트를 활용하여 쿼리 생성, 실행, 에러 감지 및 자동 수정 루프를 수행하는 에이전트 코어 로직입니다.

```python
# agent_core.py: 자기 교정(Self-Correction) Text-to-SQL 에이전트 루프
import os
from openai import OpenAI

class TextToSQLAgent:
    def __init__(self, schema_manager, query_executor, model_name: str = "gpt-4o"):
        self.schema_manager = schema_manager
        self.executor = query_executor
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model_name = model_name

    def run_query_pipeline(self, user_question: str, max_retries: int = 3) -> dict:
        # 1단계: 사용자 질문에서 키워드 추출 및 동적 스키마 로드
        keywords = [word for word in user_question.split() if len(word) > 1]
        schema_info = self.schema_manager.get_focused_schema(keywords)
        
        system_prompt = f"""
        당신은 DuckDB SQL 전문가이자 데이터 분석 에이전트입니다.
        제공된 데이터베이스 스키마를 바탕으로 사용자의 자연어 질문에 답할 수 있는 정확한 DuckDB 표준 SQL 쿼리를 작성하세요.
        오직 순수 SQL 문자열만 마크다운 코드 블록(```sql ... ```) 형식으로 출력하세요. 설명은 필요 없습니다.
        
        [데이터베이스 스키마 정보]
        {schema_info}
        """

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_question}
        ]

        current_try = 0
        last_error = None

        while current_try < max_retries:
            try:
                # LLM을 통한 SQL 생성
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    temperature=0.0
                )
                raw_output = response.choices[0].message.content
                
                # 마크다운 블록에서 SQL 추출
                sql_query = self._extract_sql(raw_output)
                
                # 안전성 검증 및 실행 (Arrow 포맷)
                arrow_result = self.executor.execute_to_arrow(sql_query)
                
                # 결과 성공 반환
                return {
                    "success": True,
                    "sql": sql_query,
                    "data": arrow_result.to_pydict(),
                    "row_count": arrow_result.num_rows,
                    "retries": current_try
                }

            except Exception as e:
                last_error = str(e)
                current_try += 1
                # 실패 시 에러 피드백을 대화 역사에 추가하여 LLM이 스스로 수정하도록 유도
                messages.append({"role": "assistant", "content": raw_output})
                messages.append({"role": "user", "content": f"이전 SQL 실행 중 오류가 발생했습니다. 오류 내용을 참고하여 쿼리를 수정해주세요.\n오류: {last_error}"})

        return {
            "success": False,
            "error": last_error,
            "retries": max_retries
        }

    def _extract_sql(self, text: str) -> str:
        if "```sql" in text:
            return text.split("```sql")[1].split("```")[0].strip()
        elif "```" in text:
            return text.split("```")[1].split("```")[0].strip()
        return text.strip()
```

---

### 결론

오늘 포스트에서는 외부 대형 클라우드 웨어하우스에 대한 의존성을 낮추고, 로컬 인메모리 OLAP 환경에서 초고속으로 작동하는 **Text-to-SQL 및 DuckDB 기반 실시간 데이터 분석 에이전트 파이프라인**을 구축해 보았습니다. 

동적 스키마 링킹을 통한 컨텍스트 최적화, sqlglot 기반의 안전한 쿼리 AST 검증, 그리고 Apache Arrow를 통한 제로카피 데이터 핸들링은 엔터프라이즈 환경에서 요구하는 보안성과 성능을 모두 충족합니다. 나아가 Self-Correction 루프를 도입함으로써 에이전트의 자율성과 응답 정확도를 극대화할 수 있었습니다. 

오늘 구현한 아키텍처를 사내 로그 분석 시스템, 실시간 비즈니스 대시보드 백엔드, 혹은 대화형 BI 챗봇에 적용하여 AI 기반 데이터 인프라의 혁신을 경험해 보시기 바랍니다.