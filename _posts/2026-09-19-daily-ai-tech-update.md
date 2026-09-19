---
layout: post
title: "OpenTelemetry와 Arize Phoenix를 활용한 프로덕션급 LLM 옵저버빌리티 및 실시간 트레이싱 아키텍처 실전 구축"
date: 2026-09-19 09:00:00 +0900
categories: [AI, Observability]
tags: [OpenTelemetry, ArizePhoenix, LLMObservability, Tracing, MLOps]
---

대규모 언어 모델(LLM)과 복잡한 멀티에이전트 시스템이 프로덕션 환경에 도입됨에 따라, 전통적인 소프트웨어 모니터링 방식만으로는 시스템의 내부 동작을 완벽히 파악하기 어려워졌습니다. 단순한 HTTP 상태 코드나 CPU 사용률을 넘어, 토큰 소비량, 레이턴시 병목 구간, 프롬프트 인젝션 시도, 환각(Hallucination) 현상, 그리고 복잡한 체인(Chain) 내부의 상태 변화를 추적하는 **LLM 옵저버빌리티(Observability)**의 중요성이 날로 커지고 있습니다.

이번 포스트에서는 산업 표준 프로토콜인 **OpenTelemetry(OTel)**와 오픈소스 LLM 옵저버빌리티 플랫폼인 **Arize Phoenix**를 결합하여, 분산된 LLM 파이프라인의 실시간 트레이싱과 평가(Evaluation)를 수행하는 프로덕션급 아키텍처를 실전 구축해 보겠습니다.

---

### 1. 프로덕션 LLM 옵저버빌리티와 OpenTelemetry 표준의 이해

전통적인 마이크로서비스 아키텍처에서 분산 트레이싱을 위해 OpenTelemetry가 표준으로 자리 잡았듯, AI 엔지니어링 영역에서도 LLM 호출을 하나의 거대한 스팬(Span)이자 트레이스로 취급하려는 표준화 노력이 가속화되고 있습니다. 

LLM 옵저버빌리티가 기존 APM(Application Performance Monitoring)과 구별되는 결정적 차이는 다음과 같습니다:
* **비정형 데이터와 페이로드의 복잡성:** 단순한 문자열이 아닌 거대한 프롬프트, 시스템 메시지, 대화 이력, 그리고 멀티모달 데이터의 입출력을 효율적으로 캡처해야 합니다.
* **비용 및 토큰 메트릭:** 요청당 소요된 프롬프트 토큰과 컴완션(Completion) 토큰 수를 실시간으로 집계하여 비용 최적화와 연결해야 합니다.
* **실시간 품질 평가:** 응답의 정확성, 유해성, 관련성을 실시간 또는 비동기로 채점(Evaluation)할 수 있는 인프라가 필요합니다.

OpenTelemetry는 이러한 요구사항을 수용하기 위해 시멘틱 컨벤션(Semantic Conventions)을 확장하여 LLM의 입출력, 모델 이름, 온도(Temperature) 등의 파라미터를 표준화된 메타데이터로 로깅할 수 있는 기반을 제공합니다. Arize Phoenix는 OpenTelemetry 규격의 트레이스를 네이티브로 수집하고, 이를 시각화할 뿐만 아니라 오픈소스 평가 루프를 제공하여 프로덕션 환경의 품질 저하를 즉각 감지할 수 있게 돕습니다.

---

### 2. OpenTelemetry Collector 및 Arize Phoenix 연동 아키텍처 설계

전체 시스템 아키텍처는 애플리케이션 레이어, OTel Collector, 그리고 Phoenix Backend로 구성됩니다. 파이썬 기반의 LLM 애플리케이션(예: LangChain, LlamaIndex, 또는 순수 OpenAI SDK 호출)에서 발생한 트레이스는 OTel SDK를 통해 gRPC 또는 HTTP 프로토콜로 OTel Collector에 전달됩니다. OTel Collector는 이 데이터를 필터링 및 배치(Batch) 처리한 후, Arize Phoenix 수집기로 라우팅합니다.

```
[LLM 애플리케이션 (OTel SDK)] 
       │ (OTLP / gRPC)
       ▼
[OpenTelemetry Collector] 
       │ (오픈텔레메트리 표준 포맷)
       ▼
[Arize Phoenix Server & UI] ──► (실시간 트레이스 시각화 및 평가)
```

이 구조의 최대 장점은 애플리케이션 코드가 특정 옵저버빌리티 벤더에 종속되지 않는다는 점입니다. 나중에 엔터프라이즈 다른 모니터링 툴로 전환하더라도 OTel Collector의 라우팅 설정만 변경하면 되므로 뛰어난 유연성을 자랑합니다.

---

### 3. Python 기반 실전 OTel 트레이싱 및 Phoenix 파이프라인 구현

이제 실제로 OpenTelemetry와 Arize Phoenix를 파이썬 프로젝트에 통합하는 코드를 작성해 보겠습니다. 아래 코드는 OTel SDK를 초기화하고, LLM 호출을 트레이싱하여 Phoenix로 전송하는 전체 파이프라인을 구현한 예시입니다.

필요한 라이브러리를 먼저 설치합니다:
```bash
pip install opentelemetry-sdk opentelemetry-exporter-otlp openinference-instrumentation-openai phoenix
```

다음은 애플리케이션 초기화 및 트레이싱 설정 코드입니다:

```python
import os
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from openinference.instrumentation.openai import OpenAIInstrumentor
import openai

# 1. OpenTelemetry Tracer Provider 설정
tracer_provider = TracerProvider()
trace.set_tracer_provider(tracer_provider)

# 2. Arize Phoenix (또는 OTel Collector)로 향하는 OTLP Exporter 설정
# 기본 Phoenix 로컬 서버 주소: http://localhost:6006/v1/traces
phoenix_endpoint = os.getenv("PHOENIX_OTLP_ENDPOINT", "http://localhost:6006/v1/traces")
otlp_exporter = OTLPSpanExporter(endpoint=phoenix_endpoint)

# BatchSpanProcessor를 사용하여 비동기식으로 스팬 전송 (성능 저하 방지)
span_processor = BatchSpanProcessor(otlp_exporter)
tracer_provider.add_span_processor(span_processor)

# 3. OpenAI 인스트루멘테이션(Instrumentation) 활성화
# OpenAI SDK 호출 시 발생하는 모든 프롬프트, 응답, 토큰 사용량이 자동으로 캡처됩니다.
OpenAIInstrumentor().instrument()

def run_llm_pipeline(prompt_text: str):
    """
    OpenAI API를 호출하고 OTel을 통해 자동으로 트레이스가 수집되는 함수
    """
    client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    
    print(f"[*] LLM 요청 전송 중... 프롬프트: {prompt_text}")
    
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "당신은 전문 소프트웨어 엔지니어링 어시스턴트입니다."},
            {"role": "user", "content": prompt_text}
        ],
        temperature=0.2,
    )
    
    answer = response.choices[0].message.content
    print(f"[*] 응답 수신 완료: {answer[:50]}...")
    return answer

if __name__ == "__main__":
    # 환경 변수 설정 예시 (실제 구동 시 설정 필요)
    os.environ["OPENAI_API_KEY"] = "sk-your-openai-api-key"
    
    # 파이프라인 실행
    user_prompt = "OpenTelemetry를 활용한 LLM 옵저버빌리티 구축의 핵심 이점 3가지를 설명해줘."
    result = run_llm_pipeline(user_prompt)
```

위 코드를 실행하면, OpenAI API 호출 과정에서 발생하는 입력 토큰 수, 출력 토큰 수, 소요 시간(Latency), 그리고 정확한 프롬프트 내용이 OpenTelemetry 표준 스팬으로 변환되어 로컬에서 구동 중인 Arize Phoenix 서버로 전송됩니다.

---

### 결론

프로덕션 환경에서 LLM 애플리케이션을 안정적으로 운영하기 위해서는 '눈에 보이지 않는 블랙박스' 상태를 해소하는 것이 무엇보다 중요합니다. OpenTelemetry 표준을 활용하면 특정 벤더 종속성 없이 안전하게 원격 고성능 텔레메트리 데이터를 수집할 수 있으며, Arize Phoenix와 같은 강력한 오픈소스 UI를 통해 실시간 트레이싱과 품질 평가를 원스톱으로 처리할 수 있습니다. 

오늘 다룬 OTel 기반의 옵저버빌리티 파이프라인을 여러분의 AI 에이전트 및 RAG 아키텍처에 도입하여, 프로덕션 수준의 투명성과 안정성을 확보해 보시길 바랍니다.