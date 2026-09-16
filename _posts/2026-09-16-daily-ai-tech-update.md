---
layout: post
title: "KEDA 기반 GPU 오토스케일링과 Kubernetes Ray Cluster를 활용한 엔터프라이즈 클라우드 네이티브 MLOps 아키텍처 실전 구축"
date: 2026-09-16 09:00:00 +0900
categories: [AI, MLOps, Infrastructure]
tags: [KEDA, Kubernetes, RayCluster, GPUAutoscaling, CloudNativeMLOps]
---

현대적인 AI 엔지니어링 환경에서 대규모 LLM 추론, 대규모 배치 학습, 그리고 복잡한 분산 데이터 처리 파이프라인을 프로덕션 환경에 안정적으로 서빙하는 것은 수많은 인프라 엔지니어들의 핵심 과제입니다. 고비용의 GPU 자원을 항시 100% 가동 상태로 유지하는 것은 예산 낭비로 이어지며, 반대로 트래픽 급증 시 유연하게 확장되지 못하면 서비스 장애로 직결됩니다.

이번 포스트에서는 쿠버네티스(Kubernetes) 환경에서 **KEDA(Kubernetes Event-driven Autoscaling)**와 **Ray Cluster**를 결합하여, 실시간 대기열(Queue) 상태와 커스텀 메트릭을 기반으로 GPU 노드 및 워커(Worker)를 동적으로 스케일링하는 엔터프라이즈급 클라우드 네이티브 MLOps 아키텍처의 설계 방법과 실전 구현 코드를 상세히 다루겠습니다.

---

### 1. 엔터프라이즈 MLOps를 위한 KEDA와 Ray Cluster 아키텍처 개요

기본적인 쿠버네티스 HPA(Horizontal Pod Autoscaler)는 CPU와 메모리 사용량만을 기준으로 파드를 확장하므로, 수십 개에서 수백 개의 잡(Job)이 비동기 큐에 쌓이는 AI 워크로드의 특성을 반영하기 어렵습니다. 이 문제를 해결하기 위해 **KEDA**를 도입합니다. KEDA는 Prometheus, Redis, AWS SQS 등 외부 이벤트 소스를 모니터링하다가 트리거 조건이 충족되면 쿠버네티스 워크로드의 레플리카(Replica) 수를 0에서 N으로 동적으로 조절해 주는 이벤트 기반 오토스케일러입니다.

여기에 대규모 분산 계산을 담당하는 **Ray Cluster**를 결합하면, 헤드(Head) 노드와 동적으로 확장되는 워커(Worker) 노드들이 효율적으로 GPU 자원을 분할하여 사용할 수 있습니다. 아키텍처의 핵심 흐름은 다음과 같습니다:

1. **클라이언트 요청:** 사용자의 대규모 추론 또는 학습 요청이 API 게이트웨이를 거쳐 Redis 큐에 적재됩니다.
2. **KEDA TriggerScaler 감지:** KEDA가 Redis 큐의 대기 중인 메시지 수(Queue Length)를 주기적으로 폴링합니다.
3. **Ray Worker 스케일 아웃:** 큐에 임계값 이상의 작업이 쌓이면, KEDA는 Ray 클라이언트의 워커 파드 수 또는 쿠버네티스 클러스터 오토스케일러(Cluster Autoscaler)와 연동해 GPU 노드를 즉시 프로비저닝합니다.
4. **분산 처리 실행:** Ray Cluster의 헤드 노드가 동적으로 합류한 워커 노드들에 작업을 균등하게 분산하여 처리합니다.

---

### 2. KEDA ScaledObject를 활용한 Redis 큐 기반 GPU 워커 동적 확장 설정

실제 프로덕션 환경에서 Redis 큐에 쌓인 작업량에 따라 Ray 워커 파드를 동적으로 제어하기 위한 KEDA `ScaledObject` 매니페스트 설정을 살펴보겠습니다. 이 설정은 큐에 작업이 없을 때는 워커를 0으로 유지하여 GPU 비용을 절감하고, 작업이 들어오면 즉시 확장합니다.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: ray-worker-autoscaler
  namespace: mLOps-inference
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: ray-worker-deployment
  minReplicaCount: 0 # 유휴 상태일 때 GPU 비용 절감을 위해 0으로 설정
  maxReplicaCount: 10 # 트래픽 급증 시 최대 10대의 워커 파드로 확장
  cooldownPeriod: 300 # 부하가 사라진 후 스케일 인(Scale-in)까지 대기하는 시간 (초)
  pollingInterval: 15 # 큐 상태를 확인하는 주기 (초)
  triggers:
    - type: redis
      metadata:
        address: redis-master.mlops-inference.svc.cluster.local:6379
        listName: "llm_inference_queue"
        listLength: "5" # Redis 큐에 대기 중인 작업이 5개 이상일 때 스케일 아웃 트리거
        enableTLS: "false"
```

위 설정을 적용하면, `llm_inference_queue` 리스트의 길이를 실시간으로 모니터링하며 KEDA가 자동으로 파드 레플리카 수를 조절합니다. 쿠버네티스 클러스터 레벨에서는 Cluster Autoscaler 또는 Karpenter가 연동되어 있어, 파드 요구에 맞춰 실제 AWS EC2나 GCP의 NVIDIA GPU 인스턴스(예: `g5.2xlarge`)를 수초 내에 프로비저닝하게 됩니다.

---

### 3. Kubernetes 환경에서의 Ray Cluster 및 오토스케일링 파이프라인 구현

KEDA가 파드를 확장할 때, Ray 워커들이 헤드 노드에 안정적으로 등록되고 작업을 병렬 처리할 수 있도록 구성된 쿠버네티스 파이프라인 및 파이썬 분산 추론 코드 예시입니다.

#### Ray Head 및 Worker 배포 매니페스트 (Kubernetes)
```yaml
apiVersion: ray.io/v1
kind: RayCluster
metadata:
  name: enterprise-ray-cluster
  namespace: mlops-inference
spec:
  rayVersion: '2.39.0'
  headGroupSpec:
    rayStartParams:
      dashboard-host: '0.0.0.0'
    template:
      spec:
        containers:
          - name: ray-head
            image: rayproject/ray:2.39.0-py310-gpu
            resources:
              limits:
                cpu: "4"
                memory: "16Gi"
              requests:
                cpu: "2"
                memory: "8Gi"
  workerGroupSpecs:
    - groupName: gpu-workers
      replicas: 0 # KEDA 및 Ray Autoscaler에 의해 동적 제어
      minReplicas: 0
      maxReplicas: 10
      rayStartParams: {}
      template:
        spec:
          containers:
            - name: ray-worker
              image: rayproject/ray:2.39.0-py310-gpu
              resources:
                limits:
                  cpu: "8"
                  memory: "32Gi"
                  nvidia.com/gpu: "1" # 파드당 1개의 NVIDIA GPU 할당
                requests:
                  cpu: "4"
                  memory: "16Gi"
                  nvidia.com/gpu: "1"
```

#### Ray를 이용한 분산 배치 추론 작업 처리 코드 (Python)
동적으로 확장된 Ray Cluster 환경에서 Redis 큐를 폴링하며 대규모 추론 작업을 비동기로 분산 처리하는 파이썬 엔트리포인트 스크립트입니다.

```python
import ray
import redis
import time
import json

# Ray 클러스터 초기화 (쿠버네티스 내부 헤드 서비스 주소 연결)
ray.init(address="ray://enterprise-ray-cluster-head-svc.mlops-inference.svc.cluster.local:10001")

# Redis 연결 설정
redis_client = redis.Redis(host='redis-master.mlops-inference.svc.cluster.local', port=6379, db=0)

@ray.remote(num_gpus=1)
def process_inference_task(prompt_data: dict) -> dict:
    """
    GPU 자원을 할당받아 대규모 언어 모델 추론을 수행하는 분산 워커 함수
    """
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    # 모델 로드 (실제 프로덕션에서는 캐시된 로컬 모델 또는 vLLM 엔진 활용 권장)
    model_id = "meta-llama/Meta-Llama-3-8B-Instruct"
    
    # GPU 텐서 연산 시뮬레이션
    prompt = prompt_data.get("prompt", "")
    task_id = prompt_data.get("task_id")
    
    print(f"[Worker] Processing Task ID: {task_id} with prompt length: {len(prompt)}")
    
    # 추론 수행 시뮬레이션 지연
    time.sleep(2) 
    
    return {
        "task_id": task_id,
        "status": "success",
        "result": f"Generated response for: {prompt[:30]}..."
    }

def main_orchestrator():
    print("Starting MLOps Ray Orchestration Loop...")
    while True:
        # Redis 큐에서 작업 가져오기 (Blocking Pop)
        queue_item = redis_client.brpop("llm_inference_queue", timeout=5)
        
        if queue_item:
            _, raw_data = queue_item
            task_data = json.loads(raw_data.decode('utf-8'))
            
            # Ray 비동기 태스크로 분산 처리 위임
            future_ref = process_inference_task.remote(task_data)
            
            # 결과를 비동기로 수집하거나 별도 결과 큐에 적재
            result = ray.get(future_ref)
            print(f"Completed: {result}")
        else:
            # 큐가 비어있는 경우 대기
            time.sleep(1)

if __name__ == "__main__":
    main_orchestrator()
```

---

### 결론

오늘 살펴본 **KEDA와 Kubernetes Ray Cluster 기반의 MLOps 아키텍처**는 고비용의 GPU 인프라를 사용하는 기업들이 트래픽 변동성에 유연하게 대응하면서도 비용을 극적으로 절감할 수 있는 가장 현대적이고 강력한 대안입니다. 

특히 큐 기반의 이벤트 드리븐 스케일링(KEDA)을 통해 유휴 상태의 리소스를 0으로 줄이고, 대규모 작업 발생 시 Ray를 통해 수십 대의 GPU 워커로 작업을 병렬 분산 처리함으로써 인프라 효율성과 운영 안정성을 동시에 확보할 수 있습니다. 엔터프라이즈 환경에서 LLM 및 고도화된 AI 파이프라인을 운영하고 있다면, 금일 소개한 아키텍처를 도입하여 클라우드 네이티브 MLOps 파이프라인을 한 단계 업그레이드해 보시길 권장합니다.