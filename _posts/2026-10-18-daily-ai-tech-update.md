---
layout: post
title: "Apple MLX와 LoRA 파인튜닝을 활용한 맥북(Apple Silicon) 온디바이스 커스텀 LLM 학습 파이프라인 실전 구축"
date: 2026-10-18 09:00:00 +0900
categories: [AI, Apple Silicon]
tags: [Apple MLX, LoRA, 온디바이스AI, M-Series, 파인튜닝, Python]
---

대규모 언어 모델(LLM)의 파인튜닝은 전통적으로 고가의 고성능 엔터프라이즈 GPU 클러스터와 수많은 VRAM을 요구하는 무거운 작업으로 여겨졌습니다. 하지만 Apple Silicon(M1/M2/M3/M4) 프로세서의 통합 메모리(Unified Memory) 구조와 애플이 직접 개발한 머신러닝 프레임워크인 **MLX**의 등장으로 개발 환경은 완전히 새로운 국면을 맞이하고 있습니다. 맥북 프로 한 대만 있으면 클라우드 비용을 들이지 않고도, 로컬 환경에서 안전하고 빠르게 최신 소형 언어 모델(SLM)을 커스텀 도메인에 맞게 파인튜닝할 수 있는 시대가 열린 것입니다.

이번 포스트에서는 Apple MLX 프레임워크와 LoRA(Low-Rank Adaptation) 기법을 결합하여, Apple Silicon 환경에서 효율적으로 대규모 언어 모델을 커스텀 학습시키는 파이프라인 구축 방법을 실전 코드를 통해 상세히 알아보겠습니다.

---

### 1. Apple MLX 아키텍처와 통합 메모리 구조의 이해

Apple MLX는 Apple Silicon의 잠재력을 극한으로 끌어내기 위해 설계된 NumPy 라이크(NumPy-like) 머신러닝 프레임워크입니다. PyTorch나 JAX와 유사한 인터페이스를 제공하지만, Apple Silicon(CPU, GPU, Neural Engine)의 아키텍처적 특성을 완벽하게 타겟팅하여 설계되었습니다.

전통적인 클라우드 GPU 환경에서는 호스트 메모리(RAM)와 디바이스 메모리(VRAM) 사이에 데이터를 지속해서 복사해야 하는 병목 현상이 발생합니다. 반면, Apple Silicon은 **통합 메모리 아키텍처(Unified Memory Architecture, UMA)**를 채택하고 있어 CPU와 GPU가 동일한 물리적 메모리 풀을 공유합니다. 

```
[Traditional GPU Architecture]          [Apple Silicon MLX Architecture]
+--------------+     PCIe     +-------+    +------------------------------------+
|  Host RAM    | <----------> | VRAM  |    |            Unified RAM             |
+--------------+              +-------+    |  (CPU & GPU Shared Zero-Copy Pool) |
 (Data Copy Overhead)                      +------------------------------------+
                                            (Zero-Copy & Fast Tensor Operations)
```

이 구조 덕분에 MLX는 데이터 복사 비용(Zero-copy)을 없애고, 맥북의 막대한 시스템 메모리(예: 64GB 또는 128GB)를 온전히 모델 학습용 VRAM처럼 활용할 수 있습니다. 7B(70억 파라미터) 또는 14B급의 모델도 양자화 기법과 결합하면 메모리 부족 현상 없이 원활하게 파인튜닝을 수행할 수 있습니다.

---

### 2. MLX 대화형 데이터셋 준비 및 데이터 파이프라인 구축

MLX를 활용한 파인튜닝을 시작하려면 모델이 학습할 수 있는 형태의 JSON 또는 JSONL 포맷 데이터셋을 준비해야 합니다. 여기서는 고객 지원 챗봇 도메인에 특화된 프롬프트-응답 쌍 구조의 데이터셋을 정의하고, MLX 학습기(Trainer)가 요구하는 형식으로 변환하는 파이프라인을 구축합니다.

먼저 터미널에서 필요한 MLX 관련 패키지를 설치합니다.

```bash
pip install mlx mlx-lm
```

다음은 학습 데이터셋인 `data/train.jsonl` 파일의 예시 구조입니다.

```json
{"text": "Human: 사내 복지 포인트는 어디서 신청하나요? Assistant: 사내 복지 포인트는 인트라넷 '복지몰' 메뉴에서 매월 1일부터 10일 사이에 신청하실 수 있습니다."}
{"text": "Human: 연차휴가는 최소 며칠 전에 신청해야 하나요? Assistant: 연차휴가는 원칙적으로 사용 3일 전까지 팀장 승인을 받아 신청해야 합니다."}
```

이제 이 데이터셋을 로드하고 MLX 형식에 맞추어 토크나이징 및 데이터 전처리를 수행하는 파이프라인 스크립트를 작성합니다.

```python
# train_prep.py
import json
import os

def prepare_dataset():
    raw_data_path = "data/train.jsonl"
    
    if not os.path.exists("data"):
        os.makedirs("data")
        
    # 샘플 학습 데이터 생성 (실무에서는 대규모 데이터셋 활용)
    sample_data = [
        {"text": "Human: 사내 복지 포인트는 어디서 신청하나요? Assistant: 사내 복지 포인트는 인트라넷 '복지몰' 메뉴에서 매월 1일부터 10일 사이에 신청하실 수 있습니다."},
        {"text": "Human: 연차휴가는 최소 며칠 전에 신청해야 하나요? Assistant: 연차휴가는 원칙적으로 사용 3일 전까지 팀장 승인을 받아 신청해야 합니다."},
        {"text": "Human: 법인카드 영수증 증빙은 언제까지 해야 하나요? Assistant: 법인카드 사용일 기준 5영업일 이내에 지출결의서를 작성하여 재무팀에 제출해야 합니다."}
    ]
    
    with open(raw_data_path, "w", encoding="utf-8") as f:
        for item in sample_data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
            
    print(f"[+] 학습 데이터 준비 완료: {raw_data_path} (총 {len(sample_data)}건)")

if __name__ == "__main__":
    prepare_dataset()
```

---

### 3. Apple MLX-LM을 활용한 LoRA 파인튜닝 실전 코드

`mlx-lm` 패키지는 허깅페이스(Hugging Face) 포맷의 모델을 로드하고, LoRA(Low-Rank Adaptation) 방식을 통해 매우 적은 메모리로 파인튜닝할 수 있는 고수준의 CLI 및 Python API를 제공합니다. 아래는 Python 코드를 통해 직접 파이프라인을 구동하는 스크립트입니다.

```python
# mlx_lora_train.py
import mlx.core as mx
from mlx_lm import lora, load
from mlx_lm.tuner.utils import print_trainable_parameters

def run_fine_tuning():
    # 1. 베이스 모델 설정 (예: 4비트 양자화된 Llama-3 또는 Mistral 모델)
    model_path = "mlx-community/Meta-Llama-3-8B-Instruct-4bit"
    
    print(f"[+] 베이스 모델 로딩 중: {model_path}")
    model, tokenizer = load(model_path)
    
    # 2. 학습 가능한 LoRA 파라미터 정보 출력
    print_trainable_parameters(model)
    
    # 3. LoRA 학습 설정 (Configuration)
    # Apple Silicon의 메모리 효율을 극대화하기 위해 rank(r)와 alpha 값을 조절합니다.
    config = {
        "model": model_path,
        "data": "data",            # train.jsonl, valid.jsonl이 위치한 디렉토리
        "train": True,
        "batch_size": 2,           # 통합 메모리에 맞춘 배치 크기
        "iters": 300,              # 학습 반복 횟수
        "steps_per_eval": 50,
        "save_every": 100,
        "steps_per_report": 10,
        "lora_parameters": {
            "rank": 8,             # LoRA 랭크 (낮을수록 메모리 절약)
            "alpha": 16,           # 스케일링 팩터
            "dropout": 0.05,
            "scale": 10.0,
            # 주의 깊게 학습할 대상 레이어 지정 (Attention Projections)
            "keys": ["self_attn.q_proj", "self_attn.v_proj"]
        },
        "learning_rate": 1e-5,
        "adapter_path": "adapters" # 학습된 어댑터 저장 경로
    }
    
    print("[+] Apple MLX LoRA 파인튜닝을 시작합니다...")
    
    # 4. 학습 실행
    lora.training(model, tokenizer, config)
    
    print(f"[+] 파인튜닝 완료! 어댑터가 '{config['adapter_path']}'에 저장되었습니다.")

if __name__ == "__main__":
    run_fine_tuning()
```

이 스크립트를 실행하면 백그라운드에서 Apple Silicon의 GPU와 통합 메모리를 적극 활용하여 가벼우면서도 빠름 속도로 가중치 업데이트가 진행됩니다. 기존 클라우드 인프라와 달리 네트워크 지연이나 과도한 전기 요금 부담 없이 로컬 환경에서 반복 실험이 가능해집니다.

---

### 4. 파인튜닝된 어댑터 병합(Fusion) 및 추론 검증

학습이 완료되면 원본 베이스 모델 위에 학습된 LoRA 어댑터 가중치를 병합(Fuse)하여 단일 모델 파일로 만들거나, 추론 시 실시간으로 어댑터를 로드하여 테스트할 수 있습니다. 아래 코드는 학습된 어댑터를 베이스 모델에 융합하고 로컬에서 프롬프트를 테스트하는 스크립트입니다.

```python
# mlx_inference.py
from mlx_lm import load, generate

def evaluate_custom_model():
    model_path = "mlx-community/Meta-Llama-3-8B-Instruct-4bit"
    adapter_path = "adapters"
    
    print("[+] 학습된 어댑터와 베이스 모델을 병합하여 로딩합니다...")
    # 어댑터가 포함된 모델 로드
    model, tokenizer = load(model_path, adapter_path=adapter_path)
    
    # 테스트 프롬프트 작성
    prompt = "Human: 사내 복지 포인트는 어디서 신청하나요? Assistant:"
    
    print(f"\n[Prompt]\n{prompt}")
    print("\n[Generated Response]")
    
    # 추론 수행
    response = generate(
        model, 
        tokenizer, 
        prompt=prompt, 
        verbose=True, 
        max_tokens=100,
        temperature=0.1
    )

if __name__ == "__main__":
    evaluate_custom_model()
```

실행 결과, 사내 규정에 특화되지 않았던 기본 Llama-3 모델이 우리가 학습시킨 데이터셋을 기반으로 정확하고 정제된 사내 복지 안내 답변을 생성해내는 것을 확인할 수 있습니다.

---

### 결론

지금까지 Apple MLX 프레임워크와 LoRA 기법을 활용하여 Apple Silicon 환경에서 온디바이스 커스텀 LLM 학습 파이프라인을 구축하는 전 과정을 살펴보았습니다. 

클라우드 GPU 인프라 구축과 유지보수 비용에 대한 압박에서 벗어나, 개발자의 책상 위 맥북 프로 한 대로 최신 소형 언어 모델을 자유롭게 커스텀하고 실험할 수 있다는 점은 AI 엔지니어링의 생산성을 극적으로 끌어올리는 혁신적인 변화입니다. 보안이 민감한 엔터프라이즈 환경이나 개인 데이터 보호가 필수적인 온디바이스 AI 애플리케이션 개발에 Apple MLX 기반 파인튜닝 파이프라인을 적극 도입해 보시기를 권장합니다.