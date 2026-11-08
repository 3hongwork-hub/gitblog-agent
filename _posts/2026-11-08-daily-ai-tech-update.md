---
layout: post
title: "LangGraph와 Postgres Checkpointer 기반의 내결함성 멀티에이전트 오케스트레이션: Human-in-the-Loop와 Time-Travel 디버깅 실전 아키텍처"
date: 2026-11-08 09:00:00 +0900
categories: [AI, Engineering]
tags: [LangGraph, MultiAgent, Checkpointing, HumanInTheLoop, StateMachine]
---

현대 엔터프라이즈 환경에서 자율형 AI 에이전트(Autonomous Agent)를 도입할 때 가장 큰 장애물은 '비결정론적 특성'과 '중단 복원력(Resilience)의 부재'입니다. 단순한 선형 체인(Linear Chain)이나 ReAct 루프는 복잡한 비즈니스 로직을 처리하는 도중 컨테이너 장애, API 타임아웃, 예외 상황이 발생했을 때 이전 상태를 복구할 수 없습니다. 

실제 프로덕션 레벨의 워크플로우는 **순환(Cycles)**, **조건부 분기(Conditional Branching)**, 그리고 관리자의 승인을 기다리는 **Human-in-the-Loop(HITL)**를 안정적으로 지원해야 합니다. 본 글에서는 LangGraph의 상태 머신(State Machine) 구조와 PostgreSQL 기반의 퍼시스턴트 체크포인터(`AsyncPostgresSaver`)를 결합하여, 시스템 장애 시에도 정확히 중단된 지점부터 복구(State Replay)되고 세션 타임-트래블(Time-Travel) 디버깅이 가능한 고가용성 멀티에이전트 아키텍처를 구축해 봅니다.

---

### 1. 상태 전이 모델(State Graph)과 Checkpointer의 영속성 메커니즘

LangGraph의 핵심 철학은 전체 워크플로우를 방향성 그래프(Directed Graph)이자 단일 상태(State)의 리듀서(Reducer) 구조로 모델링하는 것입니다. 각 노드는 순수 함수처럼 동작하며 현재 상태를 입력받아 변경 사항(Delta)을 반환하고, 엣지는 상태에 따라 다음 실행 노드를 라우팅합니다.

이 구조가 프로덕션에서 위력을 발휘하는 지점은 바로 **체크포인터(Checkpointer)**의 도입입니다.

```
       [ Client Request ]
               │
               ▼
   ┌───────────────────────┐
   │    Supervisor Node    │ ◄─── State Snapshot Saved to DB
   └───────────┬───────────┘
         ┌─────┴─────┐
         ▼           ▼
   ┌───────────┐ ┌───────────┐
   │ Reseacher │ │  Coder    │
   └─────┬─────┘ └─────┬─────┘
         │             │
         └─────┬───────┘
               ▼
   ┌───────────────────────┐
   │ Human Approval Node   │ ─── State: Interrupt (Awaiting UI Input)
   └───────────────────────┘
```

매 노드가 실행을 완료(Super-step 종료)할 때마다 LangGraph는 채널의 전체 스냅샷을 구성하고 고유한 `thread_id` 및 `checkpoint_id`와 함께 영속 스토리지(PostgreSQL)에 직렬화하여 기록합니다. 이를 통해 다음과 같은 엔터프라이즈 요구사항을 달성할 수 있습니다.

1. **내결함성(Fault Tolerance):** 파드가 재시작되더라도 마지막으로 기록된 서브스텝 체크포인트부터 상태 손실 없이 재실행됩니다.
2. **비동기 대기(Long-running Pauses):** 인간의 리뷰나 외부 웹훅 콜백을 대기할 때 인메모리 프로세스를 점유하지 않고 그래프를 즉시 인터럽트(Interrupt) 상태로 전환합니다.
3. **타임-트래블(Time-Travel) 및 상태 수정:** 과거 체크포인트를 조회하여 특정 분기 시점으로 상태를 되돌리고(Fork), 다른 파라미터나 프롬프트로 재실행(Re-run)할 수 있습니다.

---

### 2. 프로덕션 멀티에이전트 구현: 상태 스키마 및 노드 설계

아래는 Supervisor가 작업을 분배하고, 실행 에이전트가 코드를 생성한 뒤, 위험 작업 수행 전 인간 관리자의 서명을 요구하는 완전한 상태 머신 예제입니다. 상태 관리를 위해 `TypedDict`와 동시성 추가를 위한 `Annotated[list, operator.add]` 리듀서를 사용합니다.

```python
import os
import asyncio
import operator
from typing import Annotated, Sequence, TypedDict, Literal
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

# 1. 그래프 공유 상태 정의 (State Definition)
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    next_step: str
    approval_required: bool
    is_approved: bool

# 모델 초기화
llm = ChatOpenAI(model="gpt-4o", temperature=0)

# 2. 노드 구현: 슈퍼바이저 (라우터 역할)
async def supervisor_node(state: AgentState) -> dict:
    messages = state["messages"]
    system_prompt = (
        "당신은 엔지니어링 오케스트레이터입니다. "
        "사용자의 요구사항을 분석하여 'coder' 노드로 보낼지, "
        "위험 변경 작업이 있어 관리자 승인이 필요한 경우 'approval'로 보낼지 결정하세요. "
        "작업이 완료되었다면 'FINISH'를 출력하세요. "
        "응답은 오직 'coder', 'approval', 'FINISH' 중 하나만 출력합니다."
    )
    response = await llm.ainvoke([SystemMessage(content=system_prompt)] + list(messages))
    decision = response.content.strip()
    
    if decision not in ["coder", "approval", "FINISH"]:
        decision = "coder"
        
    return {"next_step": decision}

# 3. 노드 구현: 코더 에이전트
async def coder_node(state: AgentState) -> dict:
    messages = state["messages"]
    system_prompt = "당신은 시니어 파이썬 개발자입니다. 주어진 요구사항에 맞는 프로덕션 코드를 작성하세요."
    response = await llm.ainvoke([SystemMessage(content=system_prompt)] + list(messages))
    
    # 파괴적 변경(DB Drop, 인프라 수정 등) 감지 로직 시뮬레이션
    needs_approval = "DROP" in response.content.upper() or "DELETE" in response.content.upper()
    
    return {
        "messages": [response],
        "approval_required": needs_approval
    }

# 4. 노드 구현: 인간 승인 노드 (인터럽트 진입점)
async def human_approval_node(state: AgentState) -> dict:
    # 이 노드는 그래프 실행 전 인터럽트 설정(interrupt_before)에 의해 멈춥니다.
    # 재개(Resume) 시 외부에서 주입된 is_approved 값을 상태로 병합합니다.
    return {"messages": [SystemMessage(content=f"Human review completed. Approved: {state.get('is_approved', False)}")]}

# 5. 조건부 라우팅 함수
def route_step(state: AgentState) -> Literal["coder", "human_approval", END]:
    next_step = state.get("next_step")
    if state.get("approval_required") and not state.get("is_approved"):
        return "human_approval"
    if next_step == "coder":
        return "coder"
    return END
```

---

### 3. 그래프 컴파일, Postgres 영속화 및 HITL 실행 흐름

상태 머신을 실제 프로덕션 데이터베이스 풀과 결합하고, 실행 중단점(Breakpoints)을 명시하여 Human-in-the-Loop 워크플로우를 완성하는 파이프라인입니다.

```python
async def main():
    DB_URI = "postgresql://postgres:postgres@localhost:5432/agent_state_db"
    
    # PostgreSQL 연결 풀 생성
    async with AsyncConnectionPool(conninfo=DB_URI, max_size=20) as pool:
        checkpointer = AsyncPostgresSaver(pool)
        
        # 첫 구동 시 체크포인트 테이블 스키마 자동 생성
        await checkpointer.setup()

        # 그래프 빌더 구성
        workflow = StateGraph(AgentState)
        
        workflow.add_node("supervisor", supervisor_node)
        workflow.add_node("coder", coder_node)
        workflow.add_node("human_approval", human_approval_node)

        workflow.set_entry_point("supervisor")
        
        # 엣지 연결
        workflow.add_conditional_edges(
            "supervisor",
            route_step,
            {
                "coder": "coder",
                "human_approval": "human_approval",
                END: END
            }
        )
        workflow.add_edge("coder", "supervisor")
        workflow.add_edge("human_approval", "supervisor")

        # human_approval 노드 실행 직전에 상태를 멈추도록 설정
        app = workflow.compile(
            checkpointer=checkpointer,
            interrupt_before=["human_approval"]
        )

        thread_config = {"configurable": {"thread_id": "session-prod-cluster-001"}}
        
        # 초기 입력 및 실행 (위험 쿼리 유도)
        initial_input = {
            "messages": [HumanMessage(content="레거시 캐시 테이블을 제거하는 DROP TABLE 스크립트를 작성해줘.")],
            "approval_required": False,
            "is_approved": False
        }

        print("[INFO] 그래프 실행 시작...")
        async for event in app.astream(initial_input, config=thread_config):
            for node, output in event.items():
                print(f"[{node}] 노드 처리 완료: {output}")

        # 현재 스레드의 중단 상태 확인
        current_state = await app.aget_state(thread_config)
        print(f"\n[INTERRUPT 감지] 다음 실행 대기 노드: {current_state.next}")
        
        if "human_approval" in current_state.next:
            print(f"[HITL] 관리자 승인이 요구됩니다. 페이로드 검토 중...")
            print(f"[코드 스냅샷]: {current_state.values['messages'][-1].content}")

            # 관리자가 외부 UI(대시보드 등)에서 '승인' 버튼을 클릭했다고 가정
            # 타임-트래블: 상태를 안전하게 패치(Update) 후 중단된 지점부터 재개
            await app.aupdate_state(
                thread_config,
                {"is_approved": True, "approval_required": False},
                as_node="human_approval"
            )
            
            print("\n[INFO] 승인 완료. 그래프 재개(Resume)...")
            async for event in app.astream(None, config=thread_config):
                for node, output in event.items():
                    print(f"[{node}] 재개 노드 처리 완료: {output}")

if __name__ == "__main__":
    asyncio.run(main())
```

---

### 4. Time-Travel 디버깅과 프로덕션 운영 고려사항

이 아키텍처가 엔터프라이즈 환경에서 필수적인 이유는 단순 에러 복구를 넘어선 **Time-Travel Observability**를 제공하기 때문입니다.

1. **상태 히스토리 추적 (`get_state_history`):**
   `app.aget_state_history(thread_config)`를 호출하면 특정 `thread_id`에서 발생한 모든 스텝의 체크포인트 체인을 역순으로 순회할 수 있습니다. 이를 통해 에이전트가 어떤 지점에서 환각(Hallucination)을 일으키기 시작했는지 정확한 스냅샷 추적이 가능합니다.
2. **스냅샷 포크(Forking)를 통한 실시간 A/B 테스트:**
   프로덕션 장애 발생 시, 오류가 발생한 체크포인트 ID를 지정하여 새로운 하위 스레드로 상태를 분기(Fork)할 수 있습니다. 
   ```python
   # 특정 체크포인트 시점으로 타임머신 실행
   historical_checkpoint = "1ef9a32c-7b21-6540-8000-0c2d3a17e0ab"
   forked_config = {
       "configurable": {
           "thread_id": "debug-session-001",
           "checkpoint_id": historical_checkpoint
       }
   }
   # 해당 체크포인트의 상태를 수정하여 재실행
   await app.aupdate_state(forked_config, {"messages": [HumanMessage(content="대안 쿼리를 제시해줘")]})
   ```
3. **DB 커넥션 풀링 및 TTL 관리:**
   체크포인터는 매 스텝마다 JSONB 형태로 대량의 메시지 페이로드를 PostgreSQL에 기록합니다. 엔터프라이즈 환경에서는 `psycopg_pool`의 커넥션 제한을 반드시 설정하고, 완료된 스레드 데이터는 `checkpoint_blobs` 테이블에서 30일 후 아카이빙 또는 퍼지(Purge)되도록 파티셔닝 전략을 수립해야 합니다.

---

### 결론: 비결정론적 AI를 결정론적 제어 프레임워크로 감싸기

LLM 기반 멀티에이전트는 뛰어난 자율성을 갖는 반면 예측 불가능성을 본질적으로 내포하고 있습니다. LangGraph의 엄격한 상태 머신과 영속적 체크포인팅 레이어를 도입함으로써, 우리는 무한 루프 위험을 제어하고, 중요한 인프라 변경 시 인간의 개입을 강제하며, 예기치 못한 크래시 앞에서도 '정확히 한 번(Exactly-once)' 상태를 유지할 수 있는 견고한 백본을 얻게 됩니다.

복잡한 멀티에이전트 시스템을 프로덕션으로 이관하는 단계라면, 단순한 프롬프트 체이닝을 넘어 영속적 체크포인터를 결합한 상태 기반 아키텍처로의 전환을 최우선으로 검토하시기 바랍니다.