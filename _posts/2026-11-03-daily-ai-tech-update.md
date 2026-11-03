---
layout: post
title: "KEDA와 Kubernetes Ray Cluster를 활용한 프로덕션급 GPU 오토스케일링 및 분산 AI 학습·추론 파이프라인 구축"
date: 2026-11-03 09:00:00 +0900
categories: [Cloud Native, MLOps]
tags: [KEDA, Kubernetes, Ray, GPU Autoscaling, MLOps, Distributed Training]
---

현대 엔터프라이즈 환경에서 대규모 언어 모델(LLM)과 고성능 멀티모달 모델을 운영할 때 가장 큰 기술적 난제 중 하나는 **인프라 비용 최적화와 트래픽 변동성에 대한 실시간 대응**입니다. 정적(Static)으로 고정된 GPU 인프라는 심각한 유휴 비용을 발생시키며, 반대로 급격한 트래픽 유입이나 대규모 파인튜닝 작업 시 리소스 부족으로 인한 병목 현상을 초래합니다. 

이번 포스트에서는 클라우드 네이티브 환경에서 **KEDA(Kubernetes Event-driven Autoscaling)**와 **Ray Cluster**를 결합하여, 실시간 추론 요청 및 대규모 분산 학습 파이프라인의 부하에 따라 GPU 노드를 탄력적으로 확장(Scale-out)하고 축소(Scale-in)하는 프로덕션급 아키텍처 구축 방법을 상세히 살펴봅니다.

---

### 1. 아키텍처 개요: KEDA와 Ray Cluster의 시너지

전통적인 Kubernetes의 HPA(Horizontal Pod Autoscaler)는 CPU나 Memory 메트릭만을 기반으로 동작하기 때문에, 큐(Queue)에 쌓인 작업의 개수나 GPU 메모리 대역폭, 모델 추론 요청 지연 시간(Latency) 같은 MLOps 특화 지표를 직접 반영하기 어렵습니다. 

이를 해결하기 위해 본 아키텍처에서는 두 가지 핵심 엔진을 결합합니다:
* **Ray Cluster (KubeRay):** 대규모 분산 머신러닝 학습 및 vLLM 기반 고성능 추론 워크로드를 여러 노드에 걸쳐 효율적으로 분산 처리하는 오케스트레이션 프레임워크입니다.
* **KEDA (Kubernetes Event-driven Autoscaling):** Prometheus 메트릭 서버나 Redis 큐 등의 이벤트를 감지하여, Ray Worker Pod 및 Kubernetes 노드 그룹을 0(Zero)까지 축소하거나 대규모로 즉각 확장하는 이벤트 기반 오토스케일러입니다.

이 조합을 통해 평상시에는 최소한의 GPU 리소스만 유지하다가, 대규모 배치 추론 요청이나 파인튜닝 잡(Job)이 들어오는 순간 KEDA가 이를 감지하여 Ray Cluster의 워커 노드를 동적으로 프로비저닝할 수 있습니다.

---

### 2. Prometheus 메트릭 기반 KEDA ScaledObject 구성

KEDA가 Ray Cluster의 부하 상태를 정확히 파악하려면, Ray 헤드 노드에서 노출하는 프로메테우스 메트릭(예: 대기 중인 작업 수 `ray_tasks_state`, 혹은 vLLM 큐 길이)을 수집하여 KEDA ScaledObject에 연동해야 합니다.

아래는 Prometheus 메트릭 기반으로 Ray Worker Pod의 개수를 동적으로 조절하는 KEDA `ScaledObject` 매니페스트 예시입니다.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: ray-worker-autoscaler
  namespace: mlops-cluster
spec:
  scaleTargetRef:
    apiVersion: ray.io/v1
    kind: RayCluster
    name: enterprise-llm-cluster
    # RayCluster 커스텀 리소스 내에서 스케일링할 WorkerGroup 이름 지정
    envSourceContainerName: ray-worker
  minReplicaCount: 0 # 유휴 상태일 때 GPU 비용 절감을 위해 0으로 설정 가능
  maxReplicaCount: 16 # 최대 확장 가능한 워커 Pod 수
  cooldownPeriod: 300 # 부하가 사라진 후 축소(Scale-in)까지 대기하는 시간 (초)
  pollingInterval: 15 # 메트릭을 폴링하는 주기 (초)
  triggers:
    - type: prometheus
      metadata:
        serverAddress: http://prometheus-k8s.monitoring.svc.cluster.local:9090
        metricName: ray_cluster_pending_tasks
        # 대기 중인 작업 수가 임계치를 넘으면 스케일 아웃 트리거 발동
        query: sum(ray_tasks_state{state="PENDING", cluster="enterprise-llm-cluster"})
        threshold: '5'
```

이 설정을 통해 Ray 큐에 처리 대기 중인 작업이 5건 이상으로 쌓이면, KEDA가 이를 감지하고 Kubernetes 클러스터 오토스케일러와 연동하여 클라우드(AWS EKS, GCP GKE 등)의 GPU 노드 인스턴스를 동적으로 생성하게 됩니다.

---

### 3. Ray Cluster 커스텀 리소스(CRD) 및 동적 워커 설정

KEDA의 신호를 받아 실제 분산 작업을 수행할 Ray Cluster의 KubeRay CRD 설정을 정의해야 합니다. 이 설정에는 GPU 리소스 할당, 톨러레이션(Toleration), 그리고 헤드 노드와 워커 노드 간의 통신 설정이 포함됩니다.

```yaml
apiVersion: ray.io/v1
kind: RayCluster
metadata:
  name: enterprise-llm-cluster
  namespace: mlops-cluster
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
                cpu: '8'
                memory: 32Gi
              requests:
                cpu: '4'
                memory: 16Gi
  workerGroupSpecs:
    - groupName: gpu-worker-group
      replicas: 2 # 초기 레플리카 수
      minReplicas: 0
      maxReplicas: 16
      rayStartParams: {}
      template:
        spec:
          # GPU 노드 전용  taint에 대한 toleration 설정
          tolerations:
            - key: "nvidia.com/gpu"
              operator: "Exists"
              effect: "NoSchedule"
          containers:
            - name: ray-worker
              image: rayproject/ray:2.40.0-py310-gpu
              securityContext:
                capabilities:
                  add: ["SYS_P/RACE"]
              resources:
                limits:
                  cpu: '16'
                  memory: 64Gi
                  nvidia.com/gpu: '1' # 노드당 1개의 GPU 할당
                requests:
                  cpu: '8'
                  memory: 32Gi
                  nvidia.com/gpu: '1'
```

위의 설정은 Ray Worker가 필요에 따라 `0`에서 최대 `16`개까지 확장될 수 있도록 보장하며, NVIDIA GPU 리소스를 안정적으로 점유하여 대규모 LLM 분산 추론 및 데이터 병렬 학습을 수행할 수 있게 합니다.

---

### 결론

오늘 살펴본 **KEDA와 Kubernetes Ray Cluster 조합**은 프로덕션 환경에서 AI 인프라를 운영하는 엔지니어들에게 가장 강력한 무기 중 하나입니다. 고비용의 GPU 자원을 24시간 상시 가동하는 대신, 실제 작업 큐와 메트릭 기반으로 정밀하게 오토스케일링을 구현함으로써 **인프라 비용을 최대 60% 이상 절감**하는 동시에 **대규모 트래픽 유입 시에도 안정적인 SLA를 유지**할 수 있습니다. 

클라우드 네이티브 MLOps 파이프라인을 고도화하고 싶다면, 오늘 제시한 KEDA ScaledObject와 KubeRay CRD 설정을 도입하여 여러분의 AI 인프라를 한 단계 더 진화시켜 보시길 바랍니다.