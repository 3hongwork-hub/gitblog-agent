---
layout: post
title: "LangGraph와 서브그래프(Subgraph): 복잡한 상태 기반 멀티에이전트 오케스트레이션 실전"
date: 2026-08-27 09:00:00 +0900
categories: [AI, MultiAgent]
tags: [LangGraph, MultiAgent, Subgraph, StateMachine, Orchestration, Python]
---

2026년 복잡한 엔터프라이즈 업무 자동화와 대규모 소프트웨어 개발 프로젝트를 수행하기 위해 **상태 기반 멀티에이전트 시스템(Stateful Multi-Agent System)**이 핵심 아키텍처로 자리잡았습니다.

단순한 선형적 체인(Chain)으로는 순환 루프(Cycle), 조건부 분기(Branching), 그리고 사람의 승인(Human-in-the-loop)을 유연하게 제어하기 어렵습니다. 이번 글에서는 유향 그래프(DAG + Cycles) 기반으로 상태를 관리하는 **LangGraph의 핵심 개념과 계층형 서브그래프(Hierarchical Subgraph) 설계 패턴**을 분석합니다.

---

## 1. LangGraph의 핵심 아키텍처: 노드, 엣지, 그리고 상태(State)

LangGraph는 모든 에이전트와 도구를 그래프의 **노드(Node)**로 정의하고, 이들 사이의 제어 흐름을 **조건부 엣지(Conditional Edge)**로 연결하며, 중앙의 **공유 상태(State)**를 불변성(Immutability)을 유지하며 점진적으로 갱신합니다.

```
+-------------------------------------------------------------+
|                 LangGraph Multi-Agent Architecture          |
|                                                             |
|   [State Intake] ──> [Supervisor Node]                      |
|                            │                                |
|             ┌──────────────┴──────────────┐                 |
|             ▼                             ▼                 |
|   [Researcher Subgraph]          [Coder Subgraph]           |
|             │                             │                 |
|             └──────────────┬──────────────┘                 |
|                            ▼                                |
|                 [Reviewer & Approval Node]                  |
+-------------------------------------------------------------+
```

* **서브그래프(Subgraph)를 통한 관심사 분리**: 연구(Research), 코딩(Coding), 보안 검수(Security) 등 하위 복잡도를 독립된 하위 그래프로 격리하여 상태 충돌을 방지
* **체크포인팅(Checkpointing)과 시간 여행(Time-Travel)**: 에러 발생 시 언제든 이전 체크포인트 상태로 롤백 및 디버깅 가능

---

## 2. 실전 Python 코드: 계층형 멀티에이전트 서브그래프 구현

```python
from typing import TypedDict, Annotated, Sequence
import operator
from langgraph.graph import StateGraph, END

# 1. 전역 공유 상태 정의
class AgentTeamState(TypedDict):
    task: str
    research_summary: str
    code_solution: str
    is_approved: bool
    iterations: int

# 2. 개별 노드 함수 정의
def supervisor_node(state: AgentTeamState):
    print(f"[*] Supervisor: 태스크 '{state['task']}' 분석 및 서브에이전트 할당")
    return {"iterations": state.get("iterations", 0) + 1}

def researcher_node(state: AgentTeamState):
    print("[*] Researcher: 기술 문서 및 API 스펙 탐색 완료")
    return {"research_summary": "FastAPI와 AsyncPG를 이용한 비동기 DB 커넥션 풀 구조"}

def coder_node(state: AgentTeamState):
    print("[*] Coder: 리서치 요약을 기반으로 파이썬 엔드포인트 코드 작성")
    return {"code_solution": "@app.get('/items') async def get_items(db=Depends(get_db)): ..."}

def reviewer_node(state: AgentTeamState):
    print("[*] Reviewer: 코드 린트 및 보안 검수 완료")
    return {"is_approved": True}

# 3. LangGraph 빌드
workflow = StateGraph(AgentTeamState)

workflow.add_node("supervisor", supervisor_node)
workflow.add_node("researcher", researcher_node)
workflow.add_node("coder", coder_node)
workflow.add_node("reviewer", reviewer_node)

workflow.set_entry_point("supervisor")
workflow.add_edge("supervisor", "researcher")
workflow.add_edge("researcher", "coder")
workflow.add_edge("coder", "reviewer")
workflow.add_edge("reviewer", END)

app = workflow.compile()

if __name__ == "__main__":
    initial_state = {
        "task": "고성능 비동기 REST API 구축",
        "iterations": 0,
        "is_approved": False
    }
    final_output = app.invoke(initial_state)
    print(f"\n최종 워크플로우 완료 상태: {final_output}")
```

---

## 3. 엔터프라이즈 LangGraph 도입 시 3대 팁

1. **상태 스키마(TypedDict/Pydantic) 엄격화**: 노드 간 전달되는 상태 필드의 타입을 엄격하게 검증하여 런타임 오류를 방지하세요.
2. **조건부 라우팅(Conditional Routing)**: `Reviewer` 노드에서 불합격 판정 시 `Supervisor`로 루프백(Cycle)하여 자동 수정을 유도하세요.
3. **Human-in-the-loop 중단점(Breakpoints)**: 배포나 DB 마이그레이션 직전 `interrupt_before` 설정을 통해 관리자의 승인 절차를 삽입하세요.

---

## 4. 결론

복잡한 멀티 에이전트 시스템을 단방향 프롬프트로 다루는 것은 불가능합니다. **LangGraph의 상태 머신과 계층형 서브그래프 아키텍처**를 통해 견고하고 예측 가능한 엔터프라이즈 AI 시스템을 완성해 보세요.
