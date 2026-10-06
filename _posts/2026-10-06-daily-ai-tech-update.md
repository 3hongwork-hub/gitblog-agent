---
layout: post
title: "LoRA+와 GaLore를 활용한 메모리 효율적 파인튜닝: 대규모 언어 모델 저비용 학습의 실전 아키텍처"
date: 2026-10-06 09:00:00 +0900
categories: [AI, MLOps]
tags: [LoRA+, GaLore, LLM파인튜닝, 메모리최적화, PyTorch]
---

현대 대규모 언어 모델(LLM)의 파인튜닝은 여전히 엄청난 VRAM(비디오 메모리) 자원을 요구하는 고비용 작업입니다. 전통적인 Full Fine-Tuning은 모델 가중치뿐만 아니라 옵티마이저 상태(Optimizer States)와 그래디언트(Gradients)를 모두 메모리에 적재해야 하므로 수십 빌리언(Billion) 파라미터를 가진 모델을 다룰 때는 다중 GPU 클러스터가 필수적이었습니다. 이를 해결하기 위해 등장한 PEFT(Parameter-Efficient Fine-Tuning) 기법 중에서도 **LoRA+(LoRA Plus)**와 **GaLore(Gradient Low-Rank Projection)**는 메모리 병목을 극복하는 가장 혁신적인 최신 아키텍처로 주목받고 있습니다.

본 포스트에서는 기존 LoRA의 학습률 불균형 문제를 해결한 LoRA+와 가중치의 저랭크(Low-Rank) 구조를 활용해 옵티마이저 메모리를 극적으로 절감하는 GaLore를 결합하여, 단일 혹은 소수의 GPU 환경에서도 엔터프라이즈급 LLM을 효율적으로 사후 학습할 수 있는 실전 아키텍처와 파이프라인 구축 방법을 상세히 살펴봅니다.

---

### 1. LoRA+의 이론적 배경과 최적화 메커니즘

전통적인 LoRA(Low-Rank Adaptation)는 원래 모델의 가중치 행렬 $W$를 고정(Freeze)하고, 저랭크 분해 행렬인 $A$와 $B$만을 학습합니다. 이 방식은 파라미터 수를 대폭 줄여주지만, 최근 연구에 따르면 어텐션 가중치의 입력(A 행렬)과 출력(B 행렬) 피처 간의 최적 학습률(Learning Rate)이 서로 다름에도 불구하고 동일한 학습률을 적용하여 모델의 수렴 속도와 최종 성능이 저하되는 한계가 있었습니다.

**LoRA+**는 이 문제를 해결하기 위해 $A$ 행렬과 $B$ 행렬에 서로 다른 학습률을 적용합니다. 직관적으로 입력 변환 행렬 $A$보다 최종 출력을 결정하는 행렬 $B$에 더 높은 학습률을 부여($\lambda > 1$)함으로써, 피처 학습의 동역학적 균형을 맞추고 전체적인 파인튜닝 수렴 속도를 최대 2배 이상 단축시킵니다.

수학적으로 LoRA+의 업데이트 스케일은 다음과 같이 표현됩니다:
* 행렬 $A$의 학습률: $\eta_A$
* 행렬 $B$의 학습률: $\eta_B = \lambda \cdot \eta_A$ (일반적으로 $\lambda \in [16, 20]$ 권장)

이를 통해 엔터프라이즈 도메인 데이터셋에서 모델이 빠르게 수렴하며, 과적합 위험을 줄이면서도 정밀한 도메인 지식 주입이 가능해집니다.

---

### 2. GaLore: 그래디언트 저랭크 투영을 통한 옵티마이저 메모리 절감

Adam 계열의 옵티마이저는 파라미터마다 모멘텀과 분산(Variance) 값을 유지해야 하므로, 파라미터 수의 2배에 달하는 추가 메모리를 소비합니다. GaLore(Gradient Low-Rank Projection)는 **그래디언트 자체의 저랭크 성질(Low-Rank Property)**에 착안하여 이 문제를 근본적으로 해결합니다.

GaLore는 전체 가중치 공간에서 직접 옵티마이저 상태를 업데이트하는 대신, 그래디언트 행렬을 저랭크 부분 공간(Subspace)으로 투영(Projection)합니다. 이 과정에서 옵티마이저 상태가 원래 모델 차원이 아닌 압축된 저랭크 공간에서 계산되므로, Adam 옵티마이저가 차지하는 VRAM을 최대 65% 이상 절감할 수 있습니다. 결과적으로 기존에는 A100 80GB 멀티 노드에서나 가능했던 70B(700억) 파라미터 모델의 파인튜닝을 훨씬 더 접근성 높은 하드웨어 환경에서 수행할 수 있게 됩니다.

---

### 3. PyTorch 및 Hugging Face를 활용한 LoRA+와 GaLore 파인튜닝 실전 구현

실제 프로젝트에 적용할 수 있도록 Hugging Face `transformers`와 `peft`, 그리고 GaLore 구현 라이브러리를 결합한 실전 파인튜닝 코드를 작성해 보겠습니다. 아래 코드는 효율적인 메모리 관리를 위해 Mixed Precision(FP16/BF16)과 함께 GaLore 옵티마이저를 설정하는 표준 파이프라인입니다.

```python
import torch
from datasets import load_dataset
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    TrainingArguments,
    Trainer,
    DataCollatorForSeq2Seq
)
from peft import LoraConfig, get_peft_model, TaskType
# GaLore 옵티마이저 임포트 (galore-torch 패키지 활용 가정)
try:
    from galore_torch import GaLoreAdamW
except ImportError:
    # 패키지 미설치 시 표준 AdamW 사용 예시 안내용 주석
    pass

def train_llm_with_loraplus_galore():
    # 1. 모델 및 토크나이저 로드 (예: Llama-3-8B)
    model_id = "meta-llama/Meta-Llama-3-8B"
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    tokenizer.pad_token = tokenizer.eos_token
    
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        torch_dtype=torch.bfloat16,
        device_map="auto"
    )

    # 2. LoRA+ 설정을 위한 LoraConfig 구성 (B 행렬에 더 높은 학습률 부여)
    peft_config = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        target_modules=["q_proj", "v_proj", "k_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]
    )
    
    model = get_peft_model(model, peft_config)
    
    # LoRA+ 가중치 그룹 분리 (A와 B 행렬에 대한 차등 학습률 적용)
    lora_plus_lr_ratio = 16.0
    base_lr = 2e-4
    
    optimizer_grouped_parameters = []
    for name, param in model.named_parameters():
        if "lora_B" in name:
            optimizer_grouped_parameters.append({"params": [param], "lr": base_lr * lora_plus_lr_ratio})
        elif "lora_A" in name:
            optimizer_grouped_parameters.append({"params": [param], "lr": base_lr})
        else:
            # 베이스 모델 가중치는 고정 상태이므로 제외
            pass

    # 3. GaLore를 결합한 고성능 옵티마이저 설정
    # GaLore는 전체 가중치 혹은 특정 타겟 레이어(예: 모든 어텐션 및 MLP 레이어)에 적용
    galore_params = []
    for module_name, module in model.named_modules():
        if isinstance(module, torch.nn.Linear) and any(k in module_name for k in ["self_attn", "mlp"]):
            galore_params.append(module.weight)

    # GaLore 옵티마이저 초기화 (메모리 절감을 위한 저랭크 투영 활성화)
    optimizer = GaLoreAdamW(
        optimizer_grouped_parameters + [{"params": galore_params, "rank": 128, "update_proj_gap": 200, "scale": 2.0}],
        lr=base_lr,
        weight_decay=0.01
    )

    # 4. 데이터셋 로드 및 전처리
    dataset = load_dataset("json", data_files="domain_train_data.json")
    
    def tokenize_function(examples):
        outputs = tokenizer(
            examples["text"],
            truncation=True,
            max_length=2048,
            padding="max_length"
        )
        outputs["labels"] = outputs["input_ids"].copy()
        return outputs

    tokenized_dataset = dataset.map(tokenize_function, batched=True, remove_columns=["text"])

    # 5. TrainingArguments 및 Trainer 설정
    training_args = TrainingArguments(
        output_dir="./loraplus_galore_output",
        per_device_train_batch_size=4,
        gradient_accumulation_steps=4,
        learning_rate=base_lr,
        logging_steps=10,
        save_strategy="steps",
        save_steps=100,
        fp16=False,
        bf16=True, # 최신 GPU 환경에서 안정적인 학습을 위한 bfloat16 사용
        optim="adamw_torch", # 커스텀 옵티마이저 사용 시 아래 Trainer 오버라이드 참고
        lr_scheduler_type="cosine",
        warmup_ratio=0.05
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized_dataset["train"],
        data_collator=DataCollatorForSeq2Seq(tokenizer, pad_to_multiple_of=8, return_tensors="pt", padding=True),
    )
    
    # 커스텀 옵티마이저 주입
    trainer.optimizer = optimizer

    # 6. 파인튜닝 실행
    trainer.train()
    
    # 최종 어댑터 저장
    model.save_pretrained("./final_loraplus_galore_adapter")
    tokenizer.save_pretrained("./final_loraplus_galore_adapter")

if __name__ == "__main__":
    print("LoRA+ 및 GaLore 기반 메모리 효율적 LLM 파인튜닝 파이프라인 준비 완료")
```

---

### 결론

LoRA+와 GaLore의 결합은 대규모 언어 모델 파인튜닝 시장의 진입 장벽을 대폭 낮추는 강력한 기술적 해법입니다. LoRA+를 통해 학습의 수렴 속도와 정확도를 극대화하는 동시에, GaLore를 통해 옵티마이저 메모리 사용량을 획기적으로 감축함으로써 하드웨어 제약이 심한 온프레미스 환경이나 비용 효율적인 클라우드 인프라에서도 고성능 엔터프라이즈 AI 모델을 자유롭게 커스텀할 수 있게 되었습니다. 

향후 프로덕션 환경에서 도메인 특화 LLM을 자체 구축하려는 AI 엔지니어라면, 전통적인 방식에서 벗어나 이러한 메모리 최적화 PEFT 파이프라인을 적극 도입하여 인프라 비용 대비 성능 비율을 극대화하는 것을 강력히 권장합니다.