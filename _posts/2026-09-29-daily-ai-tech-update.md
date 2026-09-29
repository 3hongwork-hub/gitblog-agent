---
layout: post
title: "Direct Preference Optimization(DPO)과 페어와이즈 데이터셋을 활용한 LLM 사후 정렬 및 보상 모델 없는 파인튜닝 실전 구축"
date: 2026-09-29 09:00:00 +0900
categories: [AI, MLOps]
tags: [DPO, LLM, FineTuning, RLHF, PyTorch]
---

대규모 언어 모델(LLM)을 사전 학습(Pre-training)한 이후, 인간의 선호도와 의도에 맞게 정렬(Alignment)하는 작업은 프로덕션급 AI 서비스 구축에 있어 가장 핵심적인 공정입니다. 전통적인 RLHF(Reinforcement Learning from Human Feedback) 방식은 별도의 보상 모델(Reward Model)을 학습시킨 뒤 PPO(Proximal Policy Optimization) 알고리즘을 적용해야 하므로, 훈련 안정성이 떨어지고 복잡한 하이퍼파라미터 튜닝이 요구되는 치명적인 단점이 있었습니다.

본 포스트에서는 복잡한 보상 모델이나 강화학습 루프 없이, 선호도 쌍(Preference Pairs) 데이터셋만을 활용해 수학적으로 동일한 목적 함수를 최적화하는 **DPO(Direct Preference Optimization)** 알고리즘의 핵심 원리를 파악하고, PyTorch와 PEFT/Transformers 라이브러리를 이용해 실제 프로덕션 환경에 즉시 적용할 수 있는 사후 정렬(Post-training Alignment) 파이프라인을 구축해 보겠습니다.

---

### 1. DPO(Direct Preference Optimization)의 이론적 배경과 RLHF와의 차별점

기존의 RLHF는 두 단계로 나뉩니다. 첫째, 프롬프트에 대한 모델의 응답 중 어느 것이 더 우수한지 평가하는 보상 모델 $R(x, y)$을 학습합니다. 둘째, 이 보상 모델을 기반으로 강화학습 알고리즘인 PPO를 사용하여 언어 모델의 가중치를 업데이트합니다. 이 과정에서 보상 모델, 정책 모델(Policy), 참조 모델(Reference Model), 가치 모델(Value Model) 등 최소 4개의 대규모 모델을 동시에 메모리에 올려야 하므로 엄청난 GPU 메모리와 엔지니어링 복잡성이 수반됩니다.

DPO는 보상 함수를 모델의 정책 파라미터 공간으로 직접 치환(Reparameterization)하는 수학적 유도를 통해 이 문제를 해결합니다. 최적화된 보상 함수를 브래들리-테리(Bradley-Terry) 선호도 모델에 대입하면, 보상 모델을 거치지 않고도 언어 모델의 확률 비(Log-ratio)만으로 선호도 최적화 손실 함수(Loss Function)를 정의할 수 있습니다.

$$\mathcal{L}_{DPO}(\pi_\theta; \pi_{ref}) = -\mathbb{E}_{(x, y_w, y_l)} \left[ \log \sigma \left( \beta \log \frac{\pi_\theta(y_w|x)}{\pi_{ref}(y_w|x)} - \beta \log \frac{\pi_\theta(y_l|x)}{\pi_{ref}(y_l|x)} \right) \right]$$

여기서 $\pi_\theta$는 학습 중인 정책 모델, $\pi_{ref}$는 정렬 전의 참조 모델, $y_w$는 선호되는 응답(Winner), $y_l$은 비선호 응답(Loser), $\beta$는 참조 모델과의 이탈을 제어하는 온도(Temperature) 파라미터를 의미합니다. 이 구조 덕분에 DPO는 지도학습(Supervised Fine-Tuning)과 유사한 안정성과 속도를 보여주며 실무 도입이 매우 용이합니다.

---

### 2. 고품질 페어와이즈 데이터셋 준비 및 전처리 파이프라인

DPO 학습을 성공적으로 수행하기 위해서는 명확한 대조군을 포함하는 페어와이즈(Pairwise) 데이터셋이 필수적입니다. 데이터셋은 일반적으로 `prompt`, `chosen`(인간이 선호하거나 검증된 우수 응답), `rejected`(유해하거나 부적절하거나 품질이 떨어진 응답)의 세 가지 필드로 구성됩니다.

실전에서는 도메인 특화 지식이나 안정적인 톤앤매너를 주입하기 위해 커스텀 페어와이즈 데이터셋을 JSONL 형식으로 구축하고 파이프라인에 주입합니다. 아래는 데이터 로딩 및 트랜스포머 입력 포맷으로 변환하는 파이썬 전처리 스크립트입니다.

```python
import json
from datasets import Dataset

def load_and_format_dpo_dataset(file_path: str) -> Dataset:
    """
    JSONL 파일로부터 DPO 페어와이즈 데이터를 로드하고 
    Hugging Face Dataset 객체로 변환합니다.
    """
    data = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            item = json.loads(line.strip())
            # DPO 트레이너가 요구하는 표준 키 매핑 (prompt, chosen, rejected)
            formatted_item = {
                "prompt": item.get("instruction", ""),
                "chosen": item.get("output_chosen", ""),
                "rejected": item.get("output_rejected", "")
            }
            data.append(formatted_item)
            
    # Hugging Face Dataset으로 변환하여 트레이너와 완벽 호환
    return Dataset.from_list(data)

# 데이터셋 로드 예시
# train_dataset = load_and_format_dpo_dataset("domain_alignment_pairs.jsonl")
```

데이터 정제 과정에서 `chosen`과 `rejected`의 답변 길이가 너무 차이나거나, 프롬프트 자체에 모호함이 있는 샘플은 모델의 학습 방향을 교란(Over-optimization)시키므로 사전에 필터링하는 것이 프로덕션 안정성을 높이는 비결입니다.

---

### 3. TRL(Transformer Reinforcement Learning)을 활용한 DPO 학습 실전 구축

Hugging Face ecosystem의 `trl` 라이브러리는 `DPOTrainer`를 기본 제공하므로 수십 줄의 코드만으로 고성능 DPO 파이프라인을 구축할 수 있습니다. 또한 메모리 효율성을 극대화하기 위해 QLoRA(4-bit Quantization + LoRA)를 결합하여 단일 고성능 GPU 환경에서도 효율적인 학습이 가능하도록 구현합니다.

아래는 실제 프로덕션 환경에서 활용할 수 있는 DPO 파인튜닝 스크립트의 아키텍처와 구현 코드입니다.

```python
import torch
from datasets import load_dataset
from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from trl import DPOTrainer

def run_dpo_pipeline():
    # 1. 모델 및 토크나이저 설정 (메모리 최적화를 위한 4비트 양자화 적용)
    model_id = "meta-llama/Llama-3-8B-Instruct"
    
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    # 4비트 양자화 설정을 통한 VRAM 절감
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        torch_dtype=torch.bfloat16,
        device_map="auto",
    )
    
    # 그라디언트 체크포인팅 및 전처리 준비
    model = prepare_model_for_kbit_training(model)

    # 2. PEFT (LoRA) 설정 정의
    peft_config = LoraConfig(
        r=16,
        lora_alpha=32,
        target_modules=["q_proj", "v_proj", "k_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
    )

    # 3. 도메인 정렬용 DPO 샘플 데이터셋 로드 (여기서는 예시 데이터셋 사용)
    # 실제 환경에서는 앞서 정의한 커스텀 데이터셋을 사용합니다.
    train_dataset = load_dataset("trl-lib/ultrafeedback_binarized", split="train[:1000]")

    # 4. 학습 인자 설정 (DPO 특화 하이퍼파라미터 포함)
    training_args = TrainingArguments(
        output_dir="./dpo_aligned_llama3",
        learning_rate=5e-7,                    # DPO는 일반적으로 매우 작은 학습률 사용
        per_device_train_batch_size=2,         # GPU 메모리 상황에 맞게 조절
        gradient_accumulation_steps=4,
        logging_steps=10,
        num_train_epochs=1,
        max_length=1024,
        max_prompt_length=512,
        bf16=True,                             # A100/H100 등 최신 GPU 환경에서 bfloat16 권장
        optim="paged_adamw_8bit",
        report_to="tensorboard",
    )

    # 5. DPOTrainer 초기화 (beta 파라미터는 보통 0.1 ~ 0.5 사이로 설정)
    dpo_trainer = DPOTrainer(
        model=model,
        ref_model=None,                         # None으로 설정 시 PEFT 모델의 언젠가 고정된 복제본을 내부 생성
        args=training_args,
        beta=0.1,                               # 선호도 패널티 강도 조절 (Temperature)
        train_dataset=train_dataset,
        tokenizer=tokenizer,
        peft_config=peft_config,
    )

    # 6. 학습 실행 및 체크포인트 저장
    print(">>> DPO 정렬 파이프라인 학습을 시작합니다...")
    dpo_trainer.train()
    
    # 최종 정렬된 어댑터 가중치 저장
    dpo_trainer.save_model("./dpo_aligned_llama3_final")
    print(">>> DPO 학습 완료 및 모델 저장 성공!")

if __name__ == "__main__":
    run_dpo_pipeline()
```

이 스크립트는 `ref_model=None`으로 설정하여 TRL 내부적으로 레퍼런스 모델을 효율적으로 핸들링하게 하였으며, `beta=0.1` 설정을 통해 원본 모델의 언어적 능력 손실(Catastrophic Forgetting)을 방지하고 정렬 효과를 극대화합니다.

---

### 결론

DPO는 복잡한 보상 모델 구축과 불안정한 강화학습 루프를 완전히 우회하면서도, 수학적으로 엄밀하게 인간의 선호도를 언어 모델에 내재화할 수 있는 가장 우아하고 강력한 사후 정렬 방법론입니다. 본 포스트에서 살펴본 페어와이즈 데이터 전처리 파이프라인과 TRL 및 QLoRA 기반의 학습 아키텍처를 결합한다면, 엔지니어링 리소스는 최소화하면서도 특정 비즈니스 도메인이나 서비스 가이드라인에 완벽히 부합하는 고품질 LLM을 안정적으로 구축할 수 있습니다. 

실무에 적용할 때는 `beta` 값의 튜닝과 함께, 정렬 과정에서 모델의 창의성이 지나치게 억제되지는 않는지(Over-optimization) 정기적으로 평가 파이프라인(LLM-as-a-Judge 등)을 통해 모니터링하는 것을 권장합니다.