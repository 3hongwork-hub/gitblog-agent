---
layout: post
title: "Model Context Protocol(MCP) 2.0과 FastMCP를 활용한 엔터프라이즈 AI 툴링 및 외부 시스템 연동 아키텍처"
date: 2026-09-12 09:00:00 +0900
categories: [AI, Architecture]
tags: [MCP, ModelContextProtocol, FastMCP, AIIntegration, EnterpriseAI]
---

AI 에이전트와 대형 언어 모델(LLM)이 단순한 텍스트 생성 도구를 넘어 실제 비즈니스 프로세스를 수행하는 자율형 시스템으로 진화함에 따라, 가장 큰 병목 현상 중 하나는 '외부 데이터 및 엔터프라이즈 시스템과의 안전하고 유연한 연동'이었습니다. 과거에는 LLM이 외부 API를 호출하기 위해 매번 커스텀 함수 정의(Function Calling), 복잡한 스키마 파싱, 그리고 각 서비스별 파서(Parser)를 일일이 구현해야만 했습니다. 이러한 구조는 유지보수 비용을 폭증시킬 뿐만 아니라, 엔터프라이즈 환경에서의 보안 및 표준화 요구를 충족하기 어려웠습니다.

이러한 문제를 해결하기 위해 등장한 표준 프로토콜이 바로 **Model Context Protocol(MCP)**입니다. 특히 최신 MCP 2.0 스펙과 Python 기반의 **FastMCP** 라이브러리를 결합하면, 개발자는 복잡한 저수준 전송 계층(Transport Layer) 구현 없이도 몇 줄의 데코레이터만으로 강력하고 안전한 AI 전용 툴 서버를 구축할 수 있습니다. 본 포스트에서는 MCP 2.0의 아키텍처 핵심 개념을 살펴보고, FastMCP를 이용해 엔터프라이즈 데이터베이스 및 내부 API와 LLM을 유기적으로 연동하는 실전 파이프라인 구축 방법을 상세히 알아보겠습니다.

---

### 1. Model Context Protocol(MCP) 2.0 아키텍처와 핵심 컴포넌트

MCP는 LLM 애플리케이션(Client)과 외부 데이터 소스 또는 도구(Server) 간의 통신을 표준화하기 위해 설계된 개방형 표준 프로토콜입니다. 마치 USB-C 포트가 다양한 주변기기를 컴퓨터에 연결하는 표준 규격 역할을 하듯, MCP는 AI 모델이 다양한 컨텍스트와 도구에 접근할 수 있는 단일화된 인터페이스를 제공합니다.

MCP 아키텍처는 크게 세 가지 핵심 컴포넌트로 구성됩니다:
1. **MCP Host (LLM 클라이언트)**: Claude Desktop, Cursor, 혹은 커스텀 LangChain/LlamaIndex 기반 에이전트 등 LLM을 구동하며 사용자 요청을 처리하는 주체입니다.
2. **MCP Client**: Host 내부에서 실행되며, MCP Server와의 세션 관리, 보안 인증, 프로토콜 협상을 담당하는 모듈입니다.
3. **MCP Server**: 실제 외부 시스템(데이터베이스, 파일 시스템, Jira, GitHub 등)과 통신하며, LLM이 호출할 수 있는 도구(Tools), 리소스(Resources), 프롬프트 템플릿(Prompts)을 노출하는 경량 서버입니다.

MCP 2.0에서는 특히 **양방향 스트리밍 전송(SSE 및 stdio)** 최적화, **세분화된 권한 제어(Granular Access Control)**, 그리고 **상태 기반 리소스 구독(Resource Subscriptions)** 기능이 강화되었습니다. 이를 통해 엔터프라이즈 보안 감사 요구사항을 만족하면서도 실시간 데이터 변경 사항을 LLM 컨텍스트에 동적으로 반영할 수 있게 되었습니다.

---

### 2. FastMCP를 활용한 엔터프라이즈 툴 서버 설계 및 구현

기존 JSON-RPC 기반의 MCP 스펙을 직접 구현하는 것은 상당히 번거로운 작업입니다. FastAPI가 Python 웹 개발의 패러다임을 바꿨듯, **FastMCP**는 개발자가 직관적인 파이썬 데코레이터를 사용하여 표준을 준수하는 MCP 서버를 몇 분 만에 작성할 수 있도록 돕습니다.

아래는 사내 사내 데이터베이스(예: PostgreSQL)의 고객 주문 정보를 안전하게 조회하고 요약할 수 있는 엔터프라이즈 급 FastMCP 서버 구현 예시입니다.

```python
import os
import asyncpg
from mcp.server.fastmcp import FastMCP

# FastMCP 인스턴스 초기화 (서버 이름 정의)
mcp = FastMCP("Enterprise-Order-Service-MCP")

# 데이터베이스 연결 풀 관리 (실무 환경에서는 환경 변수 또는 보안 금고 연동)
DB_URL = os.getenv("ENTERPRISE_DB_URL", "postgresql://user:password@localhost:5432/enterprise_db")

async def get_db_pool():
    """데이터베이스 비동기 커넥션 풀을 반환합니다."""
    return await asyncpg.create_pool(DB_URL)

@mcp.tool()
async def get_customer_order_history(customer_id: str, limit: int = 5) -> str:
    """
    특정 고객의 최근 주문 이력을 조회합니다.
    
    Args:
        customer_id: 조회할 고객의 고유 UUID
        limit: 가져올 최대 주문 건수 (기본값: 5)
    """
    try:
        pool = await get_db_pool()
        async with pool.acquire() as connection:
            query = """
                SELECT order_id, order_date, total_amount, status 
                FROM orders 
                WHERE customer_id = $1 
                ORDER BY order_date DESC 
                LIMIT $2;
            """
            rows = await connection.fetch(query, customer_id, limit)
            if not rows:
                return f"고객 ID {customer_id}에 대한 주문 내역이 존재하지 않습니다."
            
            result_lines = [f"--- 고객 {customer_id} 최근 주문 내역 ---"]
            for row in rows:
                result_lines.append(
                    f"주문번호: {row['order_id']} | 날짜: {row['order_date']} | "
                    f"금액: ${row['total_amount']} | 상태: {row['status']}"
                )
            return "\n".join(result_lines)
            
    except Exception as e:
        # 엔터프라이즈 환경에서는 상세 예외를 로깅하고 사용자 친화적 메시지 반환
        return f"데이터베이스 조회 중 오류가 발생했습니다: {str(e)}"

@mcp.resource("enterprise://policies/refund")
def get_refund_policy() -> str:
    """
    엔터프라이즈 환불 정책 문서를 LLM 컨텍스트에 직접 주입합니다.
    """
    return """
    [사내 표준 환불 정책 v2.4]
    1. 상품 수령 후 7일 이내에만 환불 신청이 가능합니다.
    2. 디지털 굿즈 및 다운로드 상품은 다운로드 이력이 없는 경우에만 환불됩니다.
    3. 단순 변심에 의한 반품 시 배송비는 고객 부담입니다.
    """

if __name__ == "__main__":
    # stdio 또는 SSE 방식을 통해 MCP 클라이언트와 통신 시작
    mcp.run()
```

이 코드는 `@mcp.tool()` 데코레이터를 통해 파이썬 함수의 타입힌트와 독스트링(Docstring)을 자동으로 LLM이 이해할 수 있는 JSON Schema 도구 정의로 변환합니다. 또한 `@mcp.resource`를 통해 LLM이 함수 호출 없이도 직접 정적 혹은 동적 컨텍스트(정책, 설정 등)를 읽어갈 수 있는 리소스 엔드포인트를 제공합니다.

---

### 3. 클라이언트 연동 및 프로덕션 환경에서의 보안·운영 베스트 프 prácticas

개발한 FastMCP 서버를 실제 프로덕션 환경에 배포하고, LLM 에이전트(예: Claude Desktop 또는 LangChain 에이전트)와 연동하는 과정에서는 몇 가지 중요한 아키텍처적 고려사항이 존재합니다.

첫째, **전송 계층(Transport Layer)의 선택**입니다. 로컬 개발 환경이나 데스크톱 앱 연동 시에는 표준 입출력(`stdio`) 기반의 프로세스 통신이 안전하고 간편합니다. 반면, 클라우드 분산 환경이나 여러 에이전트가 하나의 툴 서버를 공유해야 하는 마이크로서비스 아키텍처에서는 Server-Sent Events(SSE) 기반의 HTTP 통신 방식을 채택해야 합니다.

둘째, **엔터프라이즈 보안 및 인증(Authentication)**입니다. LLM이 외부 툴을 통해 사내 데이터베이스나 결제 시스템에 접근하므로, MCP 서버 앞단에서 권한 토큰(OAuth2, JWT) 검증 단계를 거쳐야 합니다. 

아래는 SSE 방식을 사용하고 간단한 토큰 인증 미들웨어를 개념적으로 적용한 클라이언트 설정 구성 예시(Claude Desktop `claude_desktop_config.json` 기준)입니다.

```json
{
  "mcpServers": {
    "enterprise-orders": {
      "command": "python",
      "args": [
        "/path/to/your/enterprise_mcp_server.py"
      ],
      "env": {
        "ENTERPRISE_DB_URL": "postgresql://secure_user:secure_password@prod-db.internal:5432/enterprise_db"
      }
    }
  }
}
```

프로덕션 운영 시 모니터링 관점에서는 OpenTelemetry 등을 활용해 MCP 서버로 들어오는 LLM의 툴 호출 빈도, 실행 지연 시간(Latency), 에러율을 실시간으로 트레이싱해야 합니다. 특히 LLM이 환각(Hallucination) 현상으로 인해 잘못된 인자로 툴을 연속 호출하는 루프(Infinite Loop)를 방지하기 위해, 서버 단에서 입력값 검증(Pydantic 기반)과 호출 횟수 제한(Rate Limiting)을 반드시 병행해야 견고한 시스템을 완성할 수 있습니다.

---

### 결론

지금까지 Model Context Protocol(MCP) 2.0의 아키텍처 철학을 바탕으로, FastMCP를 활용해 엔터프라이즈 급 AI 툴링 및 데이터 연동 파이프라인을 구축하는 방법을 살펴보았습니다. 

과거에는 복잡한 API 연동 코드를 일일이 작성하고 프롬프트를 수동으로 튜닝해야 했지만, MCP 표준을 도입함으로써 개발자는 표준화된 방식으로 에이전트의 능력을 확장할 수 있게 되었습니다. FastMCP를 통해 사내 데이터베이스와 정책 문서를 안전하게 노출하고, 이를 에이전트 생태계에 유기적으로 연결한다면, 귀하의 조직은 진정한 의미의 자율형 엔터프라이즈 AI 시스템 구축에 한 걸음 더 다가갈 수 있을 것입니다. 지금 바로 사내 레거시 시스템 중 하나를 MCP 서버로 감싸며 차세대 AI 에이전트 아키텍처를 시작해 보시기 바랍니다.