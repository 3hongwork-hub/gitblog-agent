---
layout: post
title: "Kubernetes와 Ray Cluster 기반 클라우드 네이티브 MLOps: KEDA 기반 GPU 오토스케일링 및 분산 학습 파이프라인 실전 구축"
date: 2026-10-09 09:00:00 +0900
categories: [AI, Cloud-Native]
tags: [Kubernetes, RayCluster, KEDA, MLOps, GPUAutoscaling]
---

현대 대규모 인공지능(AI) 엔지니어링 환경에서 모델의 규모가 커지고 데이터셋이 방대해짐에 따라, 단일 노드 환경을 넘어선 분산 컴퓨팅과 효율적인 인프라 자원 관리는 프로덕션 성공의 핵심 요건이 되었습니다. 특히 LLM(대규모 언어 모델) 파인튜닝과 대규모 배치 추론 워크로드는 상시 고성능 GPU 자원을 요구하지만, 비용 효율성을 극대화하기 위해서는 수요에 맞춘 동적 확장(Auto-scaling) 구조가 필수적입니다.

이번 포스트에서는 쿠버네티스(Kubernetes) 환경에서 **Ray Cluster**와 **KEDA(Kubernetes Event-driven Autoscaling)**를 결합하여, 대기 중인 워크로드 큐(Queue) 상태에 따라 GPU 노드를 유연하게 스케일링하고 분산 학습 및 추론 작업을 안정적으로 오케스트레이션하는 클라우드 네이티브 MLOps 파이프라인 실전 구축 방법을 상세히 다룹니다.

---

### 1. 클라우드 네이티브 MLOps 인프라 아키텍처 설계

프로덕션급 MLOps 파이프라인의 핵심은 자원 낭비(Idle Cost)를 최소화하면서도, 대규모 분산 학습이나 대량의 추론 요청이 들어왔을 때 지연 없이 컴퓨팅 자원을 할당받는 것입니다. 이를 위해 본 아키텍처는 세 가지 핵심 컴포넌트를 유기적으로 결합합니다.

1. **Kubernetes Cluster (EKS / GKE):** 모든 컴퓨팅 자원의 기반이 되는 오케스트레이터로, NVIDIA GPU 오퍼레이터(GPU Operator)를 통해 물리적 GPU 장치 드라이버 및 컨테이너 런타임이 구성되어 있습니다.
2. **KEDA (Kubernetes Event-driven Autoscaling):** 외부 메트릭 소스(예: Prometheus, Redis 큐 등)를 모니터링하여 Kubernetes Cluster Autoscaler와 연동, GPU 노드 풀(Node Pool)을 0에서부터 N개까지 동적으로 확장합니다.
3. **KubeRay Operator:** 쿠버네티스위에서 Ray 클러스터(Head Node와 Worker Node)의 라이프사이클을 선언적으로 관리하며, 분산 학습 및 데이터 처리 작업을 효율적으로 분산시킵니다.

전체적인 흐름은 사용자가 분산 학습 작업을 제출하면, 큐에 쌓인 작업 메트릭을 KEDA가 감지하고 클라우드 Provider의 Node Group을 확장한 뒤, KubeRay가 동적으로 할당된 GPU 노드에 Ray Worker를 조인시켜 학습을 수행하는 구조로 이루어집니다.

---

### 2. KubeRay를 활용한 분산 학습 및 추론 클러스터 구성

Kubernetes 환경에서 Ray를 구동하기 위해서는 KubeRay Custom Resource Definition(CRD)을 활용해야 합니다. 아래는 Head 노드 1대와 동적으로 확장 가능한 Worker 노드 구성을 위한 RayCluster 매니페스트 파일 예시입니다.

```yaml
apiVersion: ray.io/v1
kind: RayCluster
metadata:
  name: enterprise-ray-cluster
  namespace: mltp-production
spec:
  rayVersion: '2.40.0'
  headGroupSpec:
    rayStartParams:
      dashboard-host: '0.0.0.0'
    template:
      spec:
        containers:
        - name: ray-head
          image: rayproject/ray:2.40.0-py310-gpu
          resources:
            limits:
              cpu: "8"
              memory: 16Gi
            requests:
              cpu: "4"
              memory: 8Gi
          ports:
          - containerPort: 6379
            name: gcs
          - containerPort: 8265
            name: dashboard
          - containerPort: 10001
            name: client
  workerGroupSpecs:
  - groupName: gpu-worker-group
    replicas: 1
    minReplicas: 0
    maxReplicas: 8
    rayStartParams: {}
    template:
      spec:
        tolerations:
        - key: "nvidia.com/gpu"
          operator: "Exists"
          effect: "NoSchedule"
        containers:
        - name: ray-worker
          image: rayproject/ray:2.40.0-py310-gpu
          resources:
            limits:
              cpu: "14"
              memory: 56Gi
              nvidia.com/gpu: "1"
            requests:
              cpu: "8"
              memory: 32Gi
              nvidia.com/gpu: "1"
```

위 설정은 `minReplicas: 0`으로 설정하여 평상시에는 GPU 워커 노드를 유지하지 않고 비용을 절감하며, 작업이 요청될 때 KubeRay와 KEDA를 통해 인스턴스가 활성화되도록 설계되었습니다.

---

### 3. KEDA 기반 GPU 노드 오토스케일링(ScaledObject) 구현

큐에 대기 중인 작업(Task)의 수나 Prometheus를 통해 수집된 Ray 큐의 길이를 기반으로 KEDA가 오토스케일링을 트리거하도록 설정합니다. 아래는 Prometheus 메트릭을 활용한 `ScaledObject` 구성 예시입니다.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: ray-worker-autoscaler
  namespace: mltp-production
spec:
  scaleTargetRef:
    apiVersion: ray.io/v1
    kind: RayCluster
    name: enterprise-ray-cluster
    # KubeRay가 지원하는 Subresource 스케일링 대상 지정
    envSourceContainerName: ray-head
    kind: RayCluster
  minReplicaCount: 0
  maxReplicaCount: 8
  pollingInterval: 15
  cooldownPeriod: 300
  advanced:
    horizontalPodAutoscalerConfig:
      behavior:
        scaleDown:
          stabilizationWindowSeconds: 300
          policies:
          - type: Percent
            value: 50
            periodSeconds: 60
  triggers:
  - type: prometheus
    metadata:
      serverAddress: http://prometheus-k8s.monitoring.svc.cluster.local:9090
      metricName: ray_tasks_in_queue
      query: sum(ray_tasks_state{state="QUEUED"})
      threshold: '5'
```

이 `ScaledObject`는 Prometheus에 수집되는 `ray_tasks_in_queue` 메트릭이 5를 초과할 경우, KEDA가 KubeRay 클러스터의 `gpu-worker-group` 복제본(replica) 수를 자동으로 증가시켜 큐에 쌓인 연산 작업을 병렬로 처리할 수 있도록 만듭니다.

---

### 4. 실전 파이프라인 연동 및 검증 스크립트

구축된 클러스터 위에서 Ray를 이용해 분산 학습 작업을 제출하고 오토스케일링이 정상적으로 동작하는지 확인하는 파이썬 클라이언트 코드 예시입니다.

```python
import ray
import time
import os

# Kubernetes 내부 Ray Head 서비스 주소로 연결
ray.init(address="ray://enterprise-ray-cluster-head-svc.mltp-production.svc.cluster.local:10001")

print(f"현재 연결된 Ray 클러스터 리소스 현황: {ray.cluster_resources()}")

# 분산 처리를 위한 함수 정의 (GPU 활용 작업 가뮬레이션)
@ray.remote(num_gpus=1)
def train_distributed_model_task(task_id: int):
    import torch
    import time
    
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Task {task_id} 시작: 디바이스 {device} 할당됨")
    
    # 가상의 고부하 텐서 연산 수행
    x = torch.randn(10000, 10000, device=device)
    y = torch.matmul(x, x)
    
    time.sleep(30) # 연산 소요 시간 시뮬레이션
    return f"Task {task_id} 완료, 결과 텐서 크기: {y.shape}"

if __name__ == "__main__":
    # 대량의 분산 작업 병렬 발행 (KEDA 트리거 유도)
    num_tasks = 10
    print(f"총 {num_tasks개의 분산 학습 작업을 Ray 큐에 발행합니다.")
    
    futures = [train_distributed_model_task.remote(i) for i in range(num_tasks)]
    
    # 결과 수집 대기
    results = ray.get(futures)
    for res in results:
        print(res)
        
    ray.shutdown()
```

이 스크립트를 실행하면 10개의 병렬 작업이 큐에 들어가고, Prometheus 메트릭 임계값을 초과함에 따라 KEDA가 쿠버네티스 노드 풀을 확장하고 Ray Worker가 동적으로 생성되어 작업을 분산 처리하게 됩니다.

---

### 결론

오늘 살펴본 **Kubernetes, KubeRay, KEDA** 조합의 클라우드 네이티브 MLOps 아키텍처는 고비용의 GPU 인프라를 효율적으로 관리하고 운영할 수 있는 가장 강력한 현대적 솔루션 중 하나입니다. 

상시 구동형 인프라에 비해 최대 70% 이상의 비용 절감 효과를 거둘 수 있으며, 대규모 LLM 파인튜닝이나 배치 추론 파이프라인에서 수평적 확장성을 완벽하게 보장합니다. 엔터프라이즈 환경에서 AI 인프라의 안정성과 경제성을 동시에 극대화하고 싶다면, 오늘 소개한 클러스터 오토스케일링 파이프라인을 도입해 보시기를 강력히 권장합니다.