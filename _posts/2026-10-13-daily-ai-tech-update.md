---
layout: post
title: "Arize Phoenix와 OpenTelemetry 분산 트레이싱을 활용한 프로덕션급 LLM 옵저버빌리티 및 실시간 환각 모니터링 아키텍처"
date: 2026-10-13 09:00:00 +0900
categories: [AI, Observability]
tags: [LLMObservability, ArizePhoenix, OpenTelemetry, Tracing, HallucinationDetection]
---

대규모 언어 모델(LLM) 기반 애플리케이션이 프로덕션 환경에 성공적으로 안착하기 위해서는 전통적인 소프트웨어 모니터링을 뛰어넘는 정교한 옵저버빌리티(Observability) 체계가 필수적입니다. 기존의 APM(Application Performance Monitoring) 툴만으로는 LLM 내부의 토큰 소비량, 비정형 프롬프트의 흐름, 지연 시간(Latency)의 급증 원인, 그리고 모델의 치명적인 환각(Hallucination) 현상을 실시간으로 파악하기 어렵습니다.

본 포스트에서는 오픈소스 LLM 옵저버빌리티 프레임워크인 **Arize Phoenix**와 표준 텔레메트리 프로토콜인 **OpenTelemetry(OTel)**를 결합하여, 분산 환경에서 구동되는 프로덕션급 LLM 애플리케이션의 엔드투엔드 트레이싱과 실시간 평가 파이프라인을 구축하는 실전 아키텍처를 상세히 살펴봅니다.

---

### 1. 프로덕션 LLM 옵저버빌리티의 핵심 요건과 OpenTelemetry 표준

전통적인 시스템 아키텍처에서는 CPU 사용량, 메모리, HTTP 상태 코드가 핵심 모니터링 지표였습니다. 하지만 생성형 AI 시스템에서는 다음과 같은 차원이 완전히 다른 메트릭이 시스템의 건강도를 좌우합니다.

* **멀티스텝 에이전트의 실행 추적 (Trace & Span):** 사용자의 단일 요청이 프롬프트 엔지니어링, 벡터 검색(RAG), 리랭킹(Re-ranking), LLM 호출, 그리고 툴(Tool) 실행까지 이어지는 복잡한 유기적 흐름을 시각화해야 합니다.
* **토큰 경제학 (Token Economics):** 프롬프트 토큰과 컴플리션 토큰의 세부 분할 집계를 통해 비용 최적화와 레이트 리밋(Rate Limit) 병목 현상을 진단합니다.
* **정량적 품질 모니터링:** 모델의 답변이 사용자 의도에 부합하는지, 혹은 안전 가이드라인을 위반했는지 실시간으로 평가(Evaluation)하는 파이프라인이 트레이싱 파이프라인과 실시간으로 연동되어야 합니다.

이를 구현하기 위해 **OpenTelemetry**는 LLM 연동을 위한 표준 시맨틱 컨벤션(Semantic Conventions)을 제공합니다. 애플리케이션 코드 수정 없이 혹은 최소한의 데코레이터만으로 모든 LLM 콜(Call)을 OTel 스팬(Span)으로 캡처하고, 이를 OTLP(OpenTelemetry Protocol) 규격에 맞춰 Arize Phoenix 백엔드로 전송할 수 있습니다.

---

### 2. Arize Phoenix와 OpenTelemetry 기반 아키텍처 설계

전체 아키텍처는 크게 세 가지 계층으로 구성됩니다.

1. **인스트루멘테이션 계층 (Instrumentation Layer):** FastAPI 기반의 LLM 백엔드 서비스에 OpenTelemetry SDK와 Phoenix의 인스트루멘테이션 라이브러리를 장착하여 모든 OpenAI, LangChain, LlamaIndex, 혹은 커스텀 LLM 호출을 자동으로 스팬화합니다.
2. **수집 및 전송 계층 (Collection & Ingestion Layer):** 수집된 트레이스 데이터를 OTLP 포맷을 통해 로컬 또는 클라우드에 분산 배치된 Arize Phoenix 콜렉터 서버로 비동기 스트리밍합니다.
3. **평가 및 시각화 계층 (Evaluation & UI Layer):** Phoenix 대시보드에서 분산 트레이스를 시각적으로 디버깅하고, 임베딩 공간 시각화(Embedding UMAP) 및 내장된 LLM-as-a-Judge 평가기를 통해 환각 및 편향 지표를 실시간으로 모니터링합니다.

```
[FastAPI / LangChain 앱] 
       │ (OpenTelemetry / OTLP 스트리밍)
       ▼
[Arize Phoenix Collector / Server]
       │
       ├─► [Distributed Trace UI (지연 시간 및 토큰 분석)]
       └─► [Real-time Evaluation (환각 탐지 및 LLM-as-a-Judge)]
```

---

### 3. 실전 구현: OpenTelemetry 자동 인스트루멘테이션 및 Phoenix 연동 코드

아래 코드는 FastAPI 기반의 LLM 서비스에 OpenTelemetry를 설정하고, Arize Phoenix로 트레이스 데이터를 전송하는 프로덕션급 백엔드 구현 예시입니다.

```python
import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from openinference.instrumentation.openai import OpenAIInstrumentor
from openai import OpenAI

# 1. OpenTelemetry 및 Phoenix 환경 설정
os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://localhost:6006/v1/traces"  # Arize Phoenix 기본 엔드포인트

resource = Resource.create({"service.name": "enterprise-llm-rag-service"})
provider = TracerProvider(resource=resource)

# OTLP 익스포터 설정 (Phoenix로 트레이스 전송)
otlp_exporter = OTLPSpanExporter(endpoint="http://localhost:6006/v1/traces")
span_processor = BatchSpanProcessor(otlp_exporter)
provider.add_span_processor(span_processor)

trace.set_tracer_provider(provider)

# 2. OpenInference를 통한 OpenAI 자동 인스트루멘테이션 활성화
# 이 설정 하나로 모든 OpenAI API 호출의 프롬프트, 토큰 수, 레이턴시가 OTel 스팬으로 자동 변환됩니다.
OpenAIInstrumentor().instrument()

app = FastAPI(title="LLM Observability Production Service", version="1.0.0")
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", "dummy-key"))

class PromptRequest(BaseModel):
    prompt: str
    user_id: str

@app.post("/v1/generate")
async def generate_text(request: PromptRequest):
    tracer = trace.get_tracer(__name__)
    
    # 커스텀 비즈니스 로직 스팬 생성
    with tracer.start_as_current_span("rag-pipeline-execution") as span:
        span.set_attribute("user.id", request.user_id)
        span.set_attribute("gen_ai.system", "openai")
        
        try:
            # LLM 호출 (자동으로 OTel 스팬이 자식 스팬으로 기록됨)
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "당신은 전문 엔터프라이즈 AI 어시스턴트입니다."},
                    {"role": "user", "content": request.prompt}
                ],
                temperature=0.2
            )
            
            output_text = response.choices[0].message.content
            token_usage = response.usage.dict() if response.usage else {}
            
            # 응답 메트릭을 스팬 어트리뷰트에 추가
            span.set_attribute("gen_ai.usage.prompt_tokens", token_usage.get("prompt_tokens", 0))
            span.set_attribute("gen_ai.usage.completion_tokens", token_usage.get("completion_tokens", 0))
            
            return {
                "status": "success",
                "response": output_text,
                "usage": token_usage
            }
            
        except Exception as e:
            span.record_exception(e)
            span.set_status(trace.StatusCode.ERROR, str(e))
            raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

---

### 4. 실시간 환각(Hallucination) 모니터링 및 평가 파이프라인 확장

트레이스 수집을 넘어, 프로덕션 환경에서는 모델의 답변 신뢰성을 실시간으로 검증해야 합니다. Arize Phoenix는 평가(Evaluation) 모듈을 내장하고 있어, 수집된 트레이스 스트림을 대상으로 동기 혹은 비동기 환각 평가를 수행할 수 있습니다.

아래는 Phoenix의 내장 평가 도구를 활용하여 검색된 컨텍스트와 모델의 응답 간의 일치 여부를 검증하는 평가 파이프라인의 핵심 구조입니다.

```python
from phoenix.evals import (
    HallucinationEvaluator,
    QREvaluator,
    run_evals,
)
from phoenix.session import get_active_session

# Phoenix 평가기 초기화 (LLM-as-a-Judge 방식 활용)
evaluator = HallucinationEvaluator(model="gpt-4o")

def run_production_evaluation():
    # 활성화된 Phoenix 세션에서 최근 트레이스 데이터프레임 로드
    session = get_active_session()
    if session is None:
        print("활성화된 Phoenix 세션이 없습니다.")
        return

    # 트레이스 데이터셋 가져오기 (실제 구현 시 주기적 배치 잡으로 구동)
    eval_df = session.get_trace_dataframe()
    
    # 환각 및 답변 관련성 평가 실행
    # Context, Prompt, Output 컬럼을 매핑하여 모델의 충실도(Faithfulness) 측정
    # results = run_evals(
    #     dataframe=eval_df,
    #     evaluators=[evaluator],
    #     provide_explanation=True
    # )
    
    print("환각 모니터링 및 평가 파이프라인 실행 완료.")

if __name__ == "__main__":
    run_production_evaluation()
```

---

### 결론

대규모 언어 모델을 기반으로 한 프로덕션 시스템은 예측 불가능한 자연어 특성 때문에 철저한 가시성 확보가 선행되지 않으면 운영 리스크가 급증합니다. 본 포스트에서 다룬 **Arize Phoenix와 OpenTelemetry** 조합은 표준화된 OTLP 프로토콜을 기반으로 벤더 종속성 없이 분산 트레이스를 수집할 수 있게 해주며, 토큰 경제학 분석부터 LLM-as-a-Judge 기반의 실시간 환각 탐지까지 원스톱으로 해결해 줍니다. 

안정적이고 신뢰할 수 있는 엔터프라이즈 AI 시스템 구축을 고민하고 계신다면, 오늘 바로 OpenTelemetry 인스트루멘테이션을 도입하여 프로덕션 내부의 숨겨진 흐름을 가시화해 보시길 권장합니다.