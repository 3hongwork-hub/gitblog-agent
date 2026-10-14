---
layout: post
title: "LangGraph 상태 기반 멀티에이전트 오케스트레이션: 동적 서브그래프와 휴먼-인-더-루프(Human-in-the-loop) 아키텍처 실전 구축"
date: 2026-10-14 09:00:00 +0900
categories: [AI, Architecture]
tags: [LangGraph, MultiAgent, StateMachine, HumanInTheLoop, Python]
---

현대 엔터프라이즈 AI 시스템은 단일 LLM 프롬프트 호출의 한계를 넘어, 복잡한 비즈니스 로직을 스스로 분해하고 협업하는 **멀티에이전트(Multi-Agent) 시스템**으로 진화하고 있습니다. 단순한 순차적 파이프라인을 넘어 조건에 따라 동적으로 에이전트 간 제어권을 위임하고, 중요한 의사결정 구간에서 사람의 개입(Human-in-the-loop)을 안전하게 처리할 수 있는 오케스트레이션 엔진의 필요성이 그 어느 때보다 높아졌습니다.

본 포스트에서는 **LangGraph**를 활용하여 상태 머신(State Machine) 기반의 견고한 멀티에이전트 아키텍처를 설계하고, 동적 서브그래프(Subgraphs) 분할과 영속적 체크포인팅(Checkpointer)을 활용한 실전 프로덕션급 애플리케이션 구축 방법을 상세히 다룹니다.

---

### 1. 상태 머신 기반 멀티에이전트 아키텍처의 필요성

전통적인 에이전트 프레임워크들은 에이전트 간의 상호작용을 고정된 루프나 암시적 메시징에 의존하게 만들어, 디버깅이 어렵고 예외 상황에서의 상태 복구가 불가능하다는 치명적인 단점이 있었습니다. 반면, **LangGraph**는 그래프 구조를 통해 전역 상태(Global State)를 명시적으로 정의하고, 각 노드(Node)가 순수 함수(Pure Function)로서 상태를 입력받아 새로운 상태를 반환하도록 설계되었습니다.

멀티에이전트 환경에서 상태 머신 아키텍처가 제공하는 핵심 이점은 다음과 같습니다.
- **결정론적 제어 흐름(Deterministic Control Flow):** 조건부 엣지(Conditional Edges)를 통해 에이전트 간 라우팅을 명확히 제어하여 무한 루프를 방지합니다.
- **격리된 서브그래프(Isolated Subgraphs):** 복잡한 도메인(예: 코드 작성 에이전트와 코드 리뷰 에이전트 그룹)을 독립된 서브그래프로 캡슐화하여 유지보수성을 극대화합니다.
- **상태 영속성 및 타임머신(Time-travel Debugging):** 메모리 기반 체크포인터를 통해 특정 시점의 상태를 저장하고, 오류 발생 시 과거 상태로 롤백하거나 사람이 직접 개입하여 상태를 수정(Interrupt & Resume)할 수 있습니다.

---

### 2. LangGraph 상태 머신 및 동적 서브그래프 설계

아키텍처의 핵심은 전역 상태 정의와 서브그래프 간의 데이터 전달입니다. 연구원(Researcher), 코더(Coder), 리뷰어(Reviewer) 에이전트가 협력하여 소프트웨어 요구사항을 구현하는 시나리오를 상정해 보겠습니다.

전역 상태(`State`)는 에이전트 간에 공유되는 메시지 기록, 현재 작업 상태, 그리고 사람의 승인 여부 플래그를 포함합니다.

```python
from typing import Annotated, TypedDict, List, Literal
from langchain_core.messages import BaseMessage
import operator

# 전역 상태 정의 (TypedDict 기반)
class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], operator.add]
    current_task: str
    code_snippet: str
    review_feedback: str
    requires_human_approval: bool
    status: Literal["researching", "coding", "reviewing", "waiting_for_approval", "completed", "rejected"]
```

이 상태를 기반으로 리서치 노드와 코딩 서브그래프를 연결하는 메인 그래프를 구축합니다. 서브그래프 내부에서는 코더 에이전트가 코드를 생성하고, 리뷰어 에이전트가 이를 검증한 뒤 피드백을 루프백합니다.

---

### 3. 실전 코드 구현: 체크포인터와 Human-in-the-loop 적용

아래 코드는 LangGraph를 활용하여 동적 라우팅과 사람의 승인(Interrupt) 로직이 포함된 멀티에이전트 오케스트레이터의 실전 구현 예시입니다. `MemorySaver`를 사용하여 상태를 지속적으로 추적하고 중단 지점을 관리합니다.

```python
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, AIMessage

# 1. 노드 함수 정의: 리서치 에이전트
def research_node(state: AgentState) -> AgentState:
    print("--- [Researcher] 요구사항 분석 및 기술 스택 조사 중 ---")
    query = state["current_task"]
    # LLM 호출 시뮬레이션
    simulated_research = f"Research completed for: {query}. Recommended stack: Python, FastAPI."
    
    return {
        "messages": [AIMessage(content=simulated_research)],
        "status": "coding"
    }

# 2. 노드 함수 정의: 코딩 에이전트
def coding_node(state: AgentState) -> AgentState:
    print("--- [Coder] 코드 작성 중 ---")
    # 리서치 결과를 바탕으로 코드 생성
    code = "from fastapi import FastAPI\napp = FastAPI()\n\n@app.get('/')\ndef read_root():\n    return {'message': 'Hello World'}"
    
    return {
        "code_snippet": code,
        "messages": [AIMessage(content="Code generated successfully.")],
        "status": "reviewing",
        "requires_human_approval": True # 코드 완성 후 사람의 승인 요구
    }

# 3. 노드 함수 정의: 리뷰어 에이전트
def review_node(state: AgentState) -> AgentState:
    print("--- [Reviewer] 코드 품질 검토 중 ---")
    feedback = "Code looks clean and follows PEP8. Approved for production deployment."
    
    return {
        "review_feedback": feedback,
        "messages": [AIMessage(content=feedback)],
        "status": "waiting_for_approval"
    }

# 4. 조건부 라우팅 함수
def router_edge(state: AgentState) -> str:
    status = state["status"]
    if status == "coding":
        return "coder"
    elif status == "reviewing":
        return "reviewer"
    elif status == "waiting_for_approval":
        return "human_approval"
    return END

# 5. 그래프 빌드 및 컴파일
workflow = StateGraph(AgentState)

# 노드 등록
workflow.add_node("researcher", research_node)
workflow.add_node("coder", coding_node)
workflow.add_node("reviewer", review_node)

# 엣지 연결
workflow.set_entry_point("researcher")
workflow.add_edge("researcher", "coder")
workflow.add_edge("coder", "reviewer")

# 조건부 라우팅 설정
workflow.add_conditional_edges(
    "reviewer",
    router_edge,
    {
        "human_approval": END, # 사람의 승인을 위해 여기서 실행 중단 (Interrupt)
    }
)

# 메모리 체크포인터 설정 (프로덕션 환경에서는 Redis나 Postgres 체크포인터 사용 권장)
memory = MemorySaver()

# 사람의 개입(interrupt_before)을 활성화하여 컴파일
app = workflow.compile(
    checkpointer=memory,
    interrupt_before=["reviewer"] # 리뷰 단계 직전 혹은 승인 대기 단계에서 중단
)

if __name__ == "__main__":
    # 실행 설정 (Thread ID 부여)
    config = {"configurable": {"thread_id": "thread-2026-1014-01"}}
    
    initial_input = {
        "messages": [HumanMessage(content="고성능 REST API 서버를 만들어줘.")],
        "current_task": "Build FastAPI Server",
        "code_snippet": "",
        "review_feedback": "",
        "requires_human_approval": False,
        "status": "researching"
    }
    
    # 첫 번째 실행: 리뷰 단계(interrupt_before) 직전까지 자동 실행
    print("=== 멀티에이전트 파이프라인 실행 시작 ===")
    for event in app.stream(initial_input, config):
        print(event)
    
    # 상태 확인
    current_state = app.get_state(config)
    print(f"\n[현재 상태 정지됨]: status = {current_state.values.get('status')}")
    print(f"[생성된 코드]:\n{current_state.values.get('code_snippet')}")
    
    # Human-in-the-loop: 사람이 승인한 후 파이프라인 재개 (Resume)
    print("\n=== 사람이 코드를 검토하고 승인함. 파이프라인 재개 ===")
    # 상태를 직접 수정하거나 그대로 진행
    for event in app.stream(None, config): # 입력값 없이 None을 전달하면 중단된 지점부터 재개
        print(event)
```

---

### 4. 결론 및 프로덕션 운영 팁

LangGraph를 활용한 상태 기반 멀티에이전트 오케스트레이션은 복잡한 AI 워크플로우에 명확한 구조와 안정성을 부여합니다. 특히 대규모 LLM 에이전트 시스템을 프로덕션 환경에 배포할 때는 아래의 모범 사례를 반드시 고려해야 합니다.

1. **영속적 체크포인터 도입:** 메모리 기반(`MemorySaver`) 대신 프로덕션 환경에서는 PostgreSQL(`AsyncPostgresSaver`) 등을 연동하여 네트워크 장애나 서버 재시작 시에도 에이전트 상태가 유실되지 않도록 보장해야 합니다.
2. **타임아웃 및 재시도 정책 설정:** 외부 API 호출이나 LLM 응답 지연에 대비해 노드 레벨에서의 재시도(Retry) 및 타임아웃 메커니즘을 그래프 정의 시 함께 구성하는 것이 안전합니다.
3. **세분화된 서브그래프 분리:** 에이전트가 늘어남에 따라 단일 그래프가 너무 비대해지므로, 도메인별 서브그래프로 모듈화하여 `add_subgraph` 형태로 조합하는 설계 패턴을 적극 활용하시기 바랍니다.