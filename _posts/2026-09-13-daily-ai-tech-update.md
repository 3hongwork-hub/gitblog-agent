---
layout: post
title: "vLLM과 PagedAttention 최적화: 대규모 클라우드 환경에서의 초고속 분산 LLM 추론 아키텍처 실전 구축"
date: 2026-09-13 09:00:00 +0900
categories: [AI, Inference Infrastructure]
tags: [vLLM, PagedAttention, LLMInference, MLOps, DistributedComputing]
---

현대 생성형 AI 서비스가 프로덕션 환경으로 완전히 전환되면서, 대규모 언어 모델(LLM) 서빙 인프라의 효율성은 비즈니스의 성패를 가르는 핵심 지표가 되었습니다. 특히 수천 명의 사용자가 동시에 멀티턴 대화를 수행하는 환경에서, 기존의 메모리 관리 방식은 GPU VRAM의 심각한 파편화(Fragmentation)와 KV 캐시(Key-Value Cache)의 비효율적 할당이라는 병목을 유발해 왔습니다. 

본 포스트에서는 가상 메모리 관리 기법인 페이징(Paging) 개념을 LLM 추론에 도입하여 KV 캐시 메모리 낭비를 제로(0)에 가깝게 줄인 **vLLM**과 핵심 알고리즘인 **PagedAttention**의 내부 동작 원리를 심층 분석합니다. 나아가 실제 프로덕션 클라우드 환경에서 vLLM을 활용해 초고속 분산 추론 파이프라인을 구축하고 최적화하는 실전 아키텍처와 코드를 상세히 다룹니다.

---

### 1. PagedAttention의 등장 배경과 KV 캐시 메모리 파편화 문제

LLM의 디코딩(Decoding) 단계는 전형적인 메모리 집약적(Memory-bound) 연산입니다. 새로운 토큰을 생성할 때마다 이전 토큰들의 Key와 Value 텐서를 KV 캐시에 저장해야 하며, 요청(Request)의 최대 토큰 길이를 예측하기 어렵기 때문에 기존 시스템은 최악의 시나리오를 가정해 고정된 크기의 메모리 블록을 미리 할당했습니다.

이로 인해 다음과 같은 치명적인 문제가 발생했습니다.
* **내부 단편화(Internal Fragmentation):** 사용자가 실제 생성하는 토큰 수가 미리 할당된 최대 길이보다 훨씬 적을 경우, 할당된 메모리의 상당 부분이 낭비됩니다.
* **외부 단편화(External Fragmentation):** 가변적인 요청 길이로 인해 VRAM 공간이 조각나면서, 충분한 총 메모리가 남아 있음에도 새로운 요청을 처리하지 못하는 현상이 발생합니다.
* **배치 크기(Batch Size) 제약:** 낭비되는 메모리 때문에 동시에 처리할 수 있는 최대 동시 요청 수(Concurrency)가 크게 제한됩니다.

vLLM의 **PagedAttention**은 운영체제(OS)의 가상 메모리 및 페이징 기법에서 영감을 받아 이 문제를 해결했습니다. KV 캐시를 고정된 크기의 작은 '블록(Block)' 단위로 나누어 관리하고, 논리적(Logical) 블록과 물리적(Physical) 블록을 페이지 테이블을 통해 매핑합니다. 이를 통해 연속적인 메모리 공간을 확보할 필요가 없어지며, VRAM 메모리 낭비를 4% 미만으로 극적으로 줄이고 더 큰 배치 사이즈를 수용할 수 있게 됩니다.

---

### 2. vLLM 분산 추론 아키텍처 및 Tensor Parallelism 설계

단일 GPU의 VRAM 용량(예: A100 80GB)을 초과하는 대규모 모델(예: Llama-3-70B 또는 Mixtral 8x22B)을 서빙하기 위해서는 여러 GPU에 모델을 분산시키는 전략이 필수적입니다. vLLM은 Megatron-LM 스타일의 **Tensor Parallelism(TP)**과 **Pipeline Parallelism(PP)**을 완벽하게 지원하여 다중 GPU 노드 간의 초저지연 통신을 보장합니다.

실전 아키텍처를 설계할 때 고려해야 할 핵심 요소는 다음과 같습니다.
1. **Continuous Batching (Orca 스타일 스케줄링):** 전통적인 정적 배치 방식과 달리, 각 반복(Iteration)마다 완료된 요청은 즉시 제거하고 새로운 요청을 동적으로 삽입하여 GPU 유휴 시간(Idle Time)을 최소화합니다.
2. **Chunked Prefill:** 긴 프롬프트(Context)를 처리하는 Prefill 단계와 생성 단계의 연산량을 적절히 청크 단위로 나누어 인터리빙함으로써, 긴 입력으로 인해 디코딩 지연 시간(Time to First Token, TTFT)이 급증하는 현상을 방지합니다.
3. **Ray 기반 분산 오케스트레이션:** 여러 노드에 걸친 분산 GPU 환경에서 vLLM 엔진 간의 통신과 상태 동기화를 위해 Ray 프레임워크를 백엔드로 활용합니다.

---

### 3. 실전: vLLM 엔진 초기화 및 고성능 AsyncEngine API 구축

실제 프로덕션 FastAPI 백엔드에서 vLLM을 비동기(Asynchronous) 방식으로 연동하여 고성능 추론 서버를 구축하는 실전 코드를 살펴보겠습니다. 아래 코드는 PagedAttention 설정과 Tensor Parallelism을 적용한 비동기 추론 파이프라인의 표준 구현입니다.

```python
import asyncio
from typing import AsyncGenerator
from vllm import AsyncEngineArgs, AsyncLLMEngine, SamplingParams
from vllm.utils import random_uuid

# 1. vLLM 엔진 구성을 위한 아규먼트 설정
# 모델 경로, 양자화 기법, 텐서 병렬화 설정 등을 정의합니다.
engine_args = AsyncEngineArgs(
    model="meta-llama/Meta-Llama-3-8B-Instruct",
    tensor_parallel_size=1,        # 단일 노드 다중 GPU 사용 시 GPU 개수에 맞게 설정 (예: 2, 4)
    gpu_memory_utilization=0.90,   # VRAM 할당 비율 (GPU 메모리의 90% 활용)
    max_model_len=4096,            # 최대 컨텍스트 윈도우 길이
    enforce_eager=False,           # CUDA Graph 최적화 활성화 (추론 속도 향상)
    block_size=16,                 # PagedAttention 블록 크기 (기본값 16)
)

# 2. AsyncLLMEngine 초기화 (FastAPI 등 웹 서버 통합용)
llm_engine = AsyncLLMEngine.from_engine_args(engine_args)

async def generate_stream_response(prompt: str) -> AsyncGenerator[str, None]:
    """
    사용자 프롬프트를 받아 vLLM 비동기 엔진을 통해 토큰을 스트리밍 방식으로 생성합니다.
    """
    # 고유한 요청 ID 생성
    request_id = f"req-{random_uuid()}"

    # 샘플링 파라미터 설정 (Temperature, Top-p, Max tokens 등)
    sampling_params = SamplingParams(
        temperature=0.7,
        top_p=0.9,
        max_tokens=512,
        stop=["<|eot_id|>"]
    )

    # 비동기 엔진에 추론 요청 등록 및 제너레이터 획득
    results_generator = llm_engine.generate(
        prompt, 
        sampling_params, 
        request_id=request_id
    )

    # 스트리밍 응답 처리
    async for request_output in results_generator:
        # 현재까지 생성된 텍스트 중 새로 추가된 부분만 추출
        text_output = request_output.outputs[0].text
        yield text_output

# 테스트 실행 함수 (비동기 이벤트 루프 검증용)
async def main():
    test_prompt = "Explain the core mechanism of PagedAttention in vLLM in two sentences."
    print(f"Prompt: {test_prompt}\n--- Streaming Output ---")
    
    async for chunk in generate_stream_response(test_prompt):
        print(chunk, end="", flush=True)
    print()

if __name__ == "__main__":
    asyncio.run(main())
```

---

### 4. 프로덕션 운영을 위한 모니터링 및 트러블슈팅 가이드

vLLM 추론 인프라를 프로덕션 환경에 배포한 후에는 다음 메트릭을 지속적으로 모니터링해야 안정적인 서비스를 유지할 수 있습니다.

* **`vllm:num_requests_waiting` (대기 중인 요청 수):** 이 지표가 지속적으로 증가한다면 GPU 처리 용량이 한계에 도달했거나 `gpu_memory_utilization` 설정이 너무 높아 스케줄러가 병목을 겪고 있음을 의미합니다.
* **`vllm:gpu_cache_usage_factor` (KV 캐시 메모리 사용률):** PagedAttention 블록의 할당 상태를 보여줍니다. 이 값이 100%에 도달하면 메모리 부족으로 인해 요청이 지연되므로, `max_model_len`을 조정하거나 인스턴스를 수평 확장(Horizontal Scaling)해야 합니다.
* **TTFT 및 TPOT (Time Per Output Token):** 사용자 체감 지연 시간을 결정하는 핵심 지표로, Prometheus와 Grafana를 연동하여 실시간 대시보드로 구성하는 것이 필수적입니다.

---

### 결론

오늘날 LLM 서빙 엔지니어링에서 하드웨어 자원의 한계를 극복하고 비용 효율성을 극대화하는 것은 매우 중요한 과제입니다. vLLM과 PagedAttention은 메모리 파편화라는 오랜 난제를 우아하게 해결하여, 기존 대비 최대 수 배 이상의 처리량(Throughput) 향상과 저지연 서빙을 동시에 달성할 수 있게 해줍니다. 본 포스트에서 다룬 아키텍처 원리와 비동기 엔진 구현 코드를 바탕으로, 여러분의 엔터프라이즈 AI 서비스 인프라를 한 단계 더 도약시키시기 바랍니다.