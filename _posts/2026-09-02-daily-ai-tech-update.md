---
layout: post
title: "LLM 옵저버빌리티의 진화: OpenTelemetry와 Arize Phoenix를 활용한 분산 트레이싱 및 실시간 평가 체계 구축"
date: 2026-09-02 09:00:00 +0900
categories: [AI, Engineering]
tags: [Observability, OpenTelemetry, ArizePhoenix, LLMOps, Tracing]
---

AI 에이전트와 복잡한 RAG(Retrieval-Augmented Generation) 시스템이 프로덕션 환경의 주류로 자리 잡으면서, '블랙박스'와 같은 LLM 내부 동작을 가시화하는 것이 엔지니어들의 최우선 과제가 되었습니다. 단순히 입력과 출력의 로그를 남기는 수준을 넘어, 수많은 도구 호출(Tool Calling), 벡터 데이터베이스 조회, 프롬프트 체이닝 과정에서 발생하는 지연 시간과 비용, 그리고 무엇보다 '응답의 품질'을 실시간으로 추적해야 할 필요성이 커졌기 때문입니다.

오늘 포스트에서는 클라우드 네이티브 생태계의 표준인 **OpenTelemetry(OTel)**를 기반으로 LLM 애플리케이션의 내부를 투명하게 들여다보고, 오픈소스 분석 플랫폼인 **Arize Phoenix**를 결합하여 실시간 트레이싱 및 가드레일 평가 체계를 구축하는 실전 아키텍처를 살펴보겠습니다.

### 1. 왜 LLM 옵저버빌리티에 OpenTelemetry 표준이 필요한가?

기존의 모놀리식 로깅 방식으로는 LLM의 비결정론적 특성을 관리하기 어렵습니다. 하나의 사용자 요청이 들어왔을 때, 내부적으로 발생하는 임베딩 생성, 리트리버(Retrieval) 검색, 리랭킹(Re-ranking), 그리고 최종 LLM 생성 단계까지의 전체 흐름을 하나의 '트레이스(Trace)'로 묶어서 관리해야 합니다.

OpenTelemetry를 채택하면 다음과 같은 이점을 얻을 수 있습니다.
- **벤더 중립성**: 특정 모니터링 도구에 종속되지 않고 Datadog, Honeycomb, 또는 자체 구축한 Arize Phoenix 등으로 데이터를 자유롭게 전송할 수 있습니다.
- **컨텍스트 전파(Context Propagation)**: 마이크로서비스 아키텍처 환경에서도 HTTP 헤더를 통해 LLM 요청의 추적 ID를 유지하며 서비스 간 상호작용을 파악할 수 있습니다.
- **풍부한 메타데이터**: 토큰 사용량, 모델 파라미터(Temperature 등), 프롬프트 템플릿 버전 등을 스팬(Span) 속성으로 포함시켜 사후 분석의 깊이를 더해줍니다.

### 2. Arize Phoenix를 활용한 실시간 추적 및 평가 아키텍처

Arize Phoenix는 LlamaIndex나 LangChain과 같은 프레임워크와 완벽하게 통합되는 옵저버빌리티 도구입니다. 특히 로컬 및 원격 환경 모두에서 실행 가능하며, 수집된 트레이스 데이터를 기반으로 'LLM-as-a-Judge' 기법을 활용해 응답의 할루시네이션(Hallucination) 여부나 관련성(Relevance)을 즉각적으로 평가할 수 있는 기능을 제공합니다.

전형적인 아키텍처는 다음과 같이 구성됩니다.
1. **Application Layer**: LangGraph 또는 Semantic Kernel로 구축된 에이전트가 OpenTelemetry SDK를 통해 스팬 데이터를 생성합니다.
2. **Collector Layer**: OpenTelemetry Collector가 데이터를 수집, 가공하여 분석 백엔드로 전달합니다.
3. **Backend Layer**: Arize Phoenix가 데이터를 수신하여 시각화하고, 사전에 정의된 평가 데이터셋(Golden Dataset)과 비교하여 성능 지표를 산출합니다.

### 3. 실전 구현: LangChain과 OpenTelemetry 기반 트레이싱 설정

다음은 Python 환경에서 OpenTelemetry 인스트루멘테이션을 설정하고, LLM 애플리케이션의 데이터를 Arize Phoenix로 전송하는 핵심 코드 예시입니다.

```python
import os
from phoenix.otel import register
from openinference.instrumentation.langchain import LangChainInstrumentor
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# 1. Arize Phoenix 엔드포인트 설정 및 OpenTelemetry 등록
# Phoenix가 로컬 6006 포트에서 실행 중이라고 가정합니다.
PHOENIX_COLLECTOR_ENDPOINT = "http://localhost:6006/v1/traces"
register(
    project_name="customer-support-agent",
    endpoint=PHOENIX_COLLECTOR_ENDPOINT
)

# 2. LangChain 인스트루멘테이션 활성화
# 이 설정만으로 모든 LangChain 내부 호출이 자동으로 트레이싱됩니다.
LangChainInstrumentor().instrument()

def run_ai_agent(user_query: str):
    """
    사용자 질의를 처리하는 간단한 LLM 체인
    """
    model = ChatOpenAI(model="gpt-4o")
    prompt = ChatPromptTemplate.from_template("{topic}에 대해 기술적인 관점에서 설명해줘.")
    
    # Chain 구성
    chain = prompt | model | StrOutputParser()
    
    # 실행 시 발생하는 모든 내부 단계(Prompt, LLM Call 등)가 
    # OpenTelemetry 스팬으로 기록되어 Phoenix로 전송됩니다.
    response = chain.invoke({"topic": user_query})
    return response

if __name__ == "__main__":
    # 테스트 실행
    print("질의 처리 중...")
    result = run_ai_agent("분산 트레이싱의 중요성")
    print(f"결과: {result}")
    print("Arize Phoenix 대시보드(http://localhost:6006)에서 트레이스를 확인하세요.")
```

위 코드에서 `LangChainInstrumentor().instrument()`를 호출하는 순간, 코드 수정 없이도 프롬프트 내용, 사용된 토큰 수, 응답 시간 등이 표준화된 형식으로 수집됩니다. 이는 운영 환경에서 특정 요청이 왜 느려졌는지, 어떤 단계에서 비용이 많이 발생했는지 파악하는 데 결정적인 단서를 제공합니다.

### 4. 사후 분석에서 실시간 가드레일로: 평가 자동화

트레이싱이 준비되었다면, 다음 단계는 수집된 데이터를 평가하는 것입니다. Arize Phoenix는 수집된 트레이스 중 샘플을 추출하여 **Hallucination Evaluator**를 실행할 수 있습니다. 

예를 들어, RAG 시스템에서 리트리버가 가져온 문서(Context)와 LLM이 생성한 답변(Response) 사이의 논리적 일치성을 검사하여 'Faithfulness' 점수를 매깁니다. 이 과정이 자동화되면 엔지니어는 대시보드에서 품질이 저하되는 시점을 즉각적으로 감지하고, 해당 시점의 프롬프트나 파라미터를 역추적하여 개선할 수 있습니다.

### 결론: 관찰 가능한 AI가 신뢰할 수 있는 AI를 만든다

단순한 실험실 단계를 넘어 실제 비즈니스 가치를 창출하는 AI 서비스를 만들려면 '신뢰성'이 담보되어야 합니다. OpenTelemetry와 Arize Phoenix를 결합한 옵저버빌리티 체계는 단순히 버그를 잡는 도구를 넘어, 데이터 기반의 지속적인 모델 개선(Iterative Improvement)을 가능하게 하는 핵심 인프라입니다.

지금 구축하고 있는 AI 에이전트가 있다면, 가장 먼저 트레이싱부터 연동해 보시기 바랍니다. 보이지 않던 병목 지점과 할루시네이션의 패턴이 데이터로 드러나는 순간, 여러분의 AI 엔지니어링 수준은 한 단계 더 도약할 것입니다.