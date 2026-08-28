---
layout: post
title: "Kubernetes와 Ray Cluster 기반 클라우드 네이티브 MLOps: 대규모 분산 추론 및 학습 오토스케일링 실전"
date: 2026-08-28 09:00:00 +0900
categories: [MLOps, CloudNative]
tags: [Kubernetes, RayCluster, KEDA, MLOps, DistributedAI]
---

AI 모델의 규모가 기하급수적으로 커지고 실시간 처리 요구사항이 거세짐에 따라, 단일 노드 기반의 인프라는 이미 한계에 다다른 지 오래입니다. 대규모 언어 모델(LLM)의 파인튜닝, 멀티모달 데이터의 분산 학습, 그리고 수천 명의 동시 사용자를 처리해야 하는 고성능 추론 서빙 환경에서는 효율적인 클라우드 네이티브 오케스트레이션이 필수적입니다. 

특히 쿠버네티스(Kubernetes) 환경에서 분산 AI 작업을 조율할 때, **Ray Cluster**와 **KEDA(Kubernetes Event-driven Autoscaling)**의 결합은 현대 MLOps 엔지니어에게 가장 강력한 무기를 제공합니다. 이번 포스트에서는 쿠버네티스 위에서 Ray와 KEDA를 연동하여 트래픽 부하와 GPU 자원 사용량에 따라 동적으로 확장되는 분산 MLOps 파이프라인을 구축하는 실전 아키텍처와 코드를 살펴보겠습니다.

---

### 1. 왜 Kubernetes와 Ray, 그리고 KEDA의 결합인가?

전통적인 클라우드 인프라에서는 GPU 인스턴스를 고정적으로 할당해 두거나, 수동으로 스케일링을 관리했습니다. 하지만 AI 워크로드의 특성상 배치 작업 시에는 엄청난 수의 GPU가 필요하지만, 유휴 시간대에는 비용 낭비로 이어집니다. 

* **Kubernetes:** 컨테이너화된 워크로드의 표준 배포 및 리소스 격리를 담당합니다.
* **Ray:** Python 기반의 분산 컴퓨팅 프레임워크로, 데이터 처리, 머신러닝 학습, 그리고 LLM 추론을 여러 노드에 걸쳐 매끄럽게 병렬화합니다.
* **KEDA:** 쿠버네티스의 기본 HPA(Horizontal Pod Autoscaler)의 한계를 뛰어넘어, 큐의 길이(Queue Length), 커스텀 메트릭, 또는 프로메테우스(Prometheus) 메트릭을 기반으로 제로(0) 스케일링까지 지원하는 이벤트 기반 오토스케일러입니다.

이 세 가지 기술이 결합하면, 추론 요청 큐에 데이터가 쌓이거나 분산 학습 작업이 제출되는 순간 자동으로 클러스터가 확장되고, 작업이 끝나면 비용 절감을 위해 즉각적으로 자원을 반환하는 진정한 의미의 클라우드 네이티브 MLOps 환경이 완성됩니다.

---

### 2. Ray Operator와 KEDA를 활용한 분산 아키텍처 설계

전체 시스템은 Kubernetes Custom Resource Definition(CRD) 기반의 KubeRay Operator와 KEDA ScaledObject로 구성됩니다. 사용자가 분산 학습이나 대규모 추론 작업을 요청하면 Ray Job이 생성되고, KEDA는 Prometheus를 통해 Ray 헤드 노드의 큐 상태(예: 대기 중인 작업 수)를 모니터링합니다.

아래는 KEDA가 Ray 워커 노드의 개수를 동적으로 조절할 수 있도록 정의한 `ScaledObject` 매니페스트 예시입니다. 이 설정은 프로메테우스 메트릭을 참조하여 대기 중인 태스크가 임계치를 넘을 때 워커 파드를 수평 확장합니다.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: ray-worker-autoscaler
  namespace: ray-system
spec:
  scaleTargetRef:
    apiVersion: ray.io/v1
    kind: RayCluster
    name: cluster-ml-train
  minReplicaCount: 1
  maxReplicaCount: 10
  cooldownPeriod: 300
  pollingInterval: 15
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
      metricName: ray_tasks_state
      query: sum(ray_tasks_state{state="PENDING"})
      threshold: '5'
```

이 설정을 통해 Ray 클러스터 내부의 작업 큐에 대기 중인 태스크가 5개 이상으로 증가하면 KEDA가 이를 감지하고 KubeRay Operator를 통해 워커 노드를 자동으로 프로비저닝하게 됩니다.

---

### 3. 실전: Ray 클러스터 배포 및 동적 분산 작업 처리 코드

실제 쿠버네티스 환경에 배포할 RayCluster CRD 정의와, 클러스터 내부에서 실행될 분산 데이터 처리 파이썬 스크립트의 구조를 살펴보겠습니다.

먼저, 헤드 노드와 오토스케일링이 적용되는 워커 노드 그룹을 포함하는 RayCluster 매니페스트입니다.

```yaml
apiVersion: ray.io/v1
kind: RayCluster
metadata:
  name: cluster-ml-train
  namespace: ray-system
spec:
  rayVersion: '2.40.0'
  headGroupSpec:
    rayStartParams:
      dashboard-host: '0.0.0.0'
    template:
      spec:
        containers:
        - name: ray-head
          image: rayproject/ray:2.40.0-py310
          resources:
            limits:
              cpu: "4"
              memory: "16Gi"
            requests:
              cpu: "2"
              memory: "8Gi"
          ports:
          - containerPort: 6379
            name: gcs
          - containerPort: 8265
            name: dashboard
          - containerPort: 10001
            name: client
  workerGroupSpecs:
  - groupName: gpu-workers
    replicas: 1
    minReplicas: 1
    maxReplicas: 8
    rayStartParams: {}
    template:
      spec:
        containers:
        - name: ray-worker
          image: rayproject/ray:2.40.0-py310-gpu
          resources:
            limits:
              cpu: "8"
              memory: "32Gi"
              nvidia.com/gpu: "1"
            requests:
              cpu: "4"
              memory: "16Gi"
              nvidia.com/gpu: "1"
```

다음으로, 위에서 구축된 Ray 클러스터에 접속하여 대규모 데이터셋을 분산 처리하는 파이썬 애플리케이션 코드입니다. Ray의 `@ray.remote` 데코레이터를 사용하여 클러스터 전체의 GPU 자원으로 연산을 분산합니다.

```python
import ray
import time
import torch

# Kubernetes 내부에 배포된 Ray 클러스터 헤드 주소로 연결
ray.init(address="ray://cluster-ml-train-head-svc.ray-system.svc.cluster.local:10001")

@ray.remote(num_gpus=1)
def process_batch_with_gpu(batch_id: int, data_chunk: list) -> dict:
    """
    각 Ray 워커 노드의 GPU를 활용하여 데이터 배치를 병렬 처리하는 분산 함수
    """
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Worker processing Batch {batch_id} on device: {device}")
    
    # 가상의 딥러닝 연산 시뮬레이션 (Tensor 연산)
    tensor_data = torch.tensor(data_chunk, dtype=torch.float32).to(device)
    result_tensor = torch.matmul(tensor_data, tensor_data.T)
    
    # 연산 소요 시간 시뮬레이션
    time.sleep(2)
    
    return {
        "batch_id": batch_id,
        "status": "success",
        "mean_value": result_tensor.mean().item()
    }

if __name__ == "__main__":
    # 대규모 데이터셋 생성 시뮬레이션 (총 10개 배치)
    total_batches = 10
    sample_data = [[float(i) for i in range(100)] for _ in range(100)]
    
    print("분산 작업을 Ray 클러스터에 제출합니다...")
    
    # 비동기로 분산 작업 객체(Object Reference) 생성
    futures = [
        process_batch_with_gpu.remote(i, sample_data) 
        for i in range(total_batches)
    ]
    
    # 결과 수집
    results = ray.get(futures)
    
    for res in results:
        print(f"완료됨 -> 배치 ID: {res['batch_id']}, 평균값: {res['mean_value']:.4f}")
        
    ray.shutdown()
```

이 코드가 실행되면, 쿠버네티스 클러스터 내의 Ray 헤드 노드는 10개의 태스크를 인식하고 워커 노드들에 분배합니다. 이때 동시에 부하가 급증하므로, KEDA가 이를 감지하여 워커 레플리카를 자동으로 확장(Scale-up)하고, 작업이 완료되면 다시 축소(Scale-down)하게 됩니다.

---

### 결론

오늘날 AI 엔지니어링에서 인프라 관리의 효율성은 곧 비즈니스의 경쟁력과 직결됩니다. 단일 머신의 제약에서 벗어나, Kubernetes와 Ray Cluster, 그리고 KEDA를 유기적으로 결합한 클라우드 네이티브 MLOps 파이프라인을 구축하면 대규모 분산 학습과 고성능 추론 서빙을 가장 경제적이고 안정적으로 운영할 수 있습니다. 

정적 인프라의 운영 부담을 덜고, 트래픽과 부하에 따라 유연하게 살아 숨 쉬는 자율형 MLOps 인프라를 여러분의 프로덕션 환경에도 도입해 보시길 바랍니다.