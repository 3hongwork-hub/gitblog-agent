---
layout: post
title: "Apple MLX와 LoRA 기반 온디바이스 에이전트 미세조정: M계열 실리콘 맥북에서 사내 특화 LLM 구축하기"
date: 2026-11-16 09:00:00 +0900
categories: [AI, On-Device]
tags: [AppleMLX, LoRA, FineTuning, OnDeviceAI, M-Series, Python]
---

클라우드 기반의 대형 언어 모델(LLM)은 뛰어난 범용성을 자랑하지만, 사내 보안 규정, 민감한 데이터 처리, 그리고 네트워크 지연 문제로 인해 온디바이스(On-Device) AI 에이전트 구축에 대한 수요가 급증하고 있습니다. 특히 Apple Silicon(M1/M2/M3/M4) 프로세서는 통합 메모리 아키텍처(Unified Memory Architecture)를 채택하고 있어, GPU VRAM의 물리적 용량 제한에서 비교적 자유롭게 대용량 모델을 로드하고 구동할 수 있습니다. 

이번 포스트에서는 Apple이 직접 개발한 머신러닝 프레임워크인 **MLX**와 파라미터 효율적 미세조정 기법인 **LoRA(Low-Rank Adaptation)**를 결합하여, 로컬 맥북 환경에서 사내 도메인 특화 LLM을 효율적으로 학습시키고 배포하는 파이프라인의 전 과정 실전 가이드를 공유합니다.

---

### 1. Apple MLX 아키텍처와 통합 메모리 구조의 이해

전통적인 머신러닝 프레임워크인 PyTorch나 TensorFlow는 CPU와 GPU(CUDA) 간의 명시적인 메모리 복사(`cuda()`, `to('device')`) 과정이 필요합니다. 반면, Apple MLX는 NumPy와 유사한 파이썬ic한 API를 제공하면서도, Apple Silicon의 CPU, GPU, 그리고 신경망 처리 장치(ANE)가 **통합 메모리를 공유**하도록 설계되었습니다.

* **지연 평가(Lazy Evaluation):** MLX는 연산 그래프를 즉시 실행하지 않고 지연 평가하여, 컴파일러가 전체 연산 체인을 최적화한 뒤 한 번에 실행합니다. 이는 메모리 대역폭을 극대화하여 모바일 및 데스크톱 칩의 효율성을 극대화합니다.
* **통합 메모리의 이점:** 32GB 또는 64GB 통합 메모리를 탑재한 맥북 프로 환경에서는 7B~8B 규모의 파라미터를 가진 오픈소스 LLM(예: Llama 3 또는 Mistral 계열)을 별도의 고가의 외장 GPU 서버 없이도 원활하게 파인튜닝할 수 있습니다.

---

### 2. MLX LM을 활용한 데이터셋 준비 및 LoRA 설정

온디바이스 미세조정을 시작하기 앞서, 사내 문서나 도메인 지식에 맞춘 JSONL 형태의 학습 데이터셋을 준비해야 합니다. MLX 진영에서 제공하는 공식 툴킷인 `mlx-lm`을 활용하면 몇 줄의 설정만으로 효율적인 LoRA 학습이 가능합니다.

우선 필요한 라이브러리를 설치합니다.

```bash
pip install mlx mlx-lm
```

학습에 사용할 도메인 데이터셋(`train.jsonl`)은 다음과 같은 구조로 준비합니다.

```json
{"text": "질문: 사내 클라우드 인프라 배포 명령어는 무엇인가요?\n답변: 사내 클라우드 배포는 `deploy-cli prod up` 명령어를 통해 수행할 수 있습니다."}
{"text": "질문: 시니어 개발자 온보딩 문서 위치는 어디인가요?\n답변: 온보딩 문서는 노션 'Engineering Wiki/Onboarding' 페이지에 정리되어 있습니다."}
```

---

### 3. 실전 파이썬 코드: MLX 기반 LoRA 파인튜닝 자동화 파이프라인

아래 코드는 `mlx-lm` 라이브러리를 활용하여 기본 모델을 다운로드하고, LoRA 어댑터를 적용하여 사내 도메인 데이터로 학습을 수행한 뒤, 최종 양자화(Quantization) 모델로 내보내는(Export) 전체 파이썬 스크립트입니다.

```python
import os
from mlx_lm import lora, generate
from mlx_lm.tuner.utils import load_model_and_tokenizer

def run_mlx_lora_training():
    # 1. 설정 파라미터 정의
    model_path = "mlx-community/Meta-Llama-3-8B-Instruct-4bit" # 미리 양자화된 베이스 모델 활용
    data_dir = "./data" # train.jsonl과 valid.jsonl이 위치한 디렉토리
    adapter_path = "adapters"
    
    os.makedirs(adapter_path, exist_ok=True)
    
    print("==> 1. 베이스 모델 및 토크나이저 로드 중...")
    model, tokenizer = load_model_and_tokenizer(model_path)
    
    # 2. LoRA 학습 설정
    # Apple Silicon의 통합 메모리 효율을 극대화하기 위해 배치 크기와 LoRA Rank 설정
    training_args = {
        "model": model_path,
        "train": True,
        "data": data_dir,
        "adapter_path": adapter_path,
        "batch_size": 4,          # 통합 메모리 환경에 맞춘 최적 배치 사이즈
        "iters": 600,             # 데이터셋 크기에 따른 반복 횟수
        "steps_per_eval": 200,
        "save_every": 200,
        "lr": 1e-5,               # LoRA 학습용 안정적인 학습률
        "mlx_random_seed": 42,
        "lora_layers": 16,        # 적용할 LoRA 레이어 수 (모델 크기에 비례)
        "lora_parameters": {
            "rank": 8,
            "alpha": 16,
            "dropout": 0.05
        }
    }
    
    print("==> 2. MLX LoRA 파인튜닝 시작...")
    # mlx_lm.lora 모듈의 메인 학습 함수 호출
    lora.run(**training_args)
    print("==> 3. LoRA 어댑터 학습 완료 및 저장 성공!")

    # 3. 학습된 어댑터와 베이스 모델 병합(Fuse) 및 양자화
    fused_model_path = "./fused_model"
    print("==> 4. 어댑터 병합 및 4비트 양자화 모델 생성 중...")
    
    fuse_args = [
        "--model", model_path,
        "--adapter-path", adapter_path,
        "--save-path", fused_model_path,
        "--q-bits", "4"           # 온디바이스 추론 최적화를 위한 4비트 양자화
    ]
    
    # 모델 Fuse 실행
    from mlx_lm.fuse import main as fuse_main
    # sys.argv를 모방하여 fuse 함수 호출
    import sys
    sys.argv = ["fuse.py"] + fuse_args[1:]
    fuse_main()
    
    print(f"==> 완료! 최종 양자화 모델이 '{fused_model_path}'에 저장되었습니다.")

if __name__ == "__main__":
    # 실행 전 ./data 디렉토리에 train.jsonl 파일이 존재하는지 확인 필요
    if not os.path.exists("./data/train.jsonl"):
        print("경고: './data/train.jsonl' 파일이 없습니다. 샘플 데이터를 생성해주세요.")
    else:
        run_mlx_lora_training()
```

위 스크립트는 M계열 맥북의 통합 메모리를 효율적으로 활용하며, 학습 과정에서 발생하는 그래디언트 계산을 Apple Silicon의 GPU 코어로 가속합니다. 학습이 완료된 후 `--q-bits 4` 옵션을 통해 모델 용량을 대폭 줄여 온디바이스 에이전트 서비스에 바로 투입할 수 있는 상태로 만듭니다.

---

### 결론

Apple MLX와 LoRA의 조합은 사내 온디바이스 AI 에이전트 구축 패러다임을 완전히 바꾸어놓고 있습니다. 고가의 클라우드 GPU 인스턴스에 의존하지 않고도, 개발자의 로컬 맥북 환경에서 민감한 사내 데이터를 활용해 단 수십 분 만에 도메인 특화 LLM을 파인튜닝하고 검증할 수 있습니다. 

보안성이 보장되면서도 초저지연으로 구동되는 온디바이스 에이전트를 고민하고 계신다면, 오늘 당장 Apple MLX 기반의 파이프라인을 도입해 보시기를 강력히 추천합니다.