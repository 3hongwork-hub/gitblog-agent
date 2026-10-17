---
layout: post
title: "WebGPU와 Transformers.js v3 기반 온디바이스 SLM 인프라: 서버리스 제로-네트워크 로컬 추론 엔진 구축"
date: 2026-10-17 09:00:00 +0900
categories: [AI, WebEngineering]
tags: [WebGPU, TransformersJS, OnDeviceAI, SLM, Quantization, EdgeComputing]
---

대규모 클라우드 GPU 클러스터 기반 LLM 서비스는 막대한 인프라 비용, 네트워크 왕복 시간(RTT)으로 인한 지연, 그리고 데이터 프라이버시 침해라는 치명적인 단점을 항상 수반합니다. 특히 2026년 현재, 매개변수 1B~3B 규모의 고성능 소형 언어 모델(SLM, Small Language Model)들이 상위 모델에 근접하는 지능 지수를 입증하면서, 브라우저 클라이언트 내부에서 모델을 온전히 구동하는 **온디바이스(On-device) AI 아키텍처**가 실현 가능한 프로덕션 대안으로 완전히 자리잡았습니다.

브라우저는 더 이상 단순한 뷰어가 아닙니다. W3C 표준으로 안착한 **WebGPU** 인터페이스와 양자화 포맷(AWQ, ONNX Runtime Web, INT4/FP16)의 결합을 통해, 클라이언트 기기의 네이티브 GPU(NVIDIA, Apple Silicon M-시리즈, Intel Arc, Qualcomm Snapdragon X) 파워를 브라우저 런타임에서 직접 가속할 수 있게 되었습니다. 

본 포스트에서는 최신 **Transformers.js v3**와 WebGPU 백엔드를 활용하여, 민감한 개인정보를 서버로 단 1바이트도 전송하지 않고 브라우저 메모리 내에서 4-bit 양자화 모델을 캐싱 및 구동하는 제로-레이턴시 엣지 추론 파이프라인 실전 구현법을 다룹니다.

---

### 1. WebGPU와 브라우저 기반 SLM 실행의 핵심 구조

WebGPU는 기존 WebGL의 높은 드라이버 오버헤드와 비효율적인 셰이더 바인딩 한계를 극복하기 위해 설계된 저수준 그래픽 및 연산 API(Vulkan, Metal, DirectX 12 기반)입니다. 브라우저 내부에서 범용 컴퓨팅(GPGPU)을 수행할 수 있도록 컴퓨트 셰이더(Compute Shader)와 워크그룹(Workgroup) 단위 병렬 처리를 직접 제어합니다.

온디바이스 추론에서 핵심적인 도전 과제는 다음 세 가지입니다:

1. **대용량 가중치 다운로드 및 메모리 상주**: 3B 모델이라도 FP16 상태에서는 6GB 이상의 VRAM을 요구하므로 모바일 및 저전력 PC 환경에서는 OOM(Out of Memory)이 발생합니다. 이를 위해 **4-bit/8-bit 양자화(INT4 AWQ/Q4F16) ONNX 가중치**를 활용해 1.5GB 내외로 줄여야 합니다.
2. **셰이더 컴파일 지연(Shader Pre-compilation)**: 최초 브라우저 로딩 시 연산 셰이더 파이프라인 생성에 멈춤 현상(Jank)이 발생하지 않도록 비동기 파이프라인 캐시를 구축해야 합니다.
3. **메인 UI 스레드 블로킹 방지**: 텐서 연산 및 텍스트 토크나이징 과정이 브라우저의 렌더링 프레임(60/120fps)을 저해하지 않도록 **Dedicated Web Worker** 계층으로 런타임을 완전히 분리해야 합니다.

```
+-----------------------------------------------------------------------------------------+
|                                    Client Browser                                       |
|                                                                                         |
|  [Main Thread]                                      [Web Worker Thread]                 |
|  +--------------------+                             +--------------------------------+  |
|  | React/Vue UI       |  postMessage(Prompt)        | Transformers.js v3 Core        |  |
|  | - Virtual List     | ------------------------->  | - Hugging Face Tokenizer (WASM)|  |
|  | - Streaming Render |                             | - ONNX Runtime Web (WebGPU)    |  |
|  |                    |  onmessage(Stream Tokens)   +---------------+----------------+  |
|  |                    | <-------------------------                  |                   |
|  +--------------------+                                             | Direct Dispatch   |
|                                                                     v                   |
|  +-----------------------------------------------------------------------------------+  |
|  | WebGPU Native Hardware API (Vulkan / Metal / DX12)                                |  |
|  | [Model Weights in Origin Private File System (OPFS) / IndexedDB Cache: 1.5GB Q4]  |  |
|  +-----------------------------------------------------------------------------------+  |
+-----------------------------------------------------------------------------------------+
```

---

### 2. 고효율 브라우저 캐싱: OPFS(Origin Private File System)와 스트리밍 로더

수 기가바이트에 달하는 LLM 가중치를 매 세션마다 다운로드하는 것은 불가능합니다. 일반 `Cache API`나 `IndexedDB`는 대용량 바이너리 입출력 시 청크 직렬화 오버헤드가 크고 가비지 컬렉터(GC) 압박을 유발합니다. 

현대적인 웹 AI 아키텍처에서는 **Origin Private File System(OPFS)**을 사용하여 로컬 파일 시스템 수준의 제로 복사(Zero-copy) 읽기 스트림을 구성합니다. Transformers.js v3는 내장 캐시 인터페이스를 통해 모델 샤드(Shard)를 OPFS에 영구 저장하고, 모델 인스턴스화 시 GPU 버퍼로 직접 메모리 매핑(mmap 유사 방식)을 수행합니다.

---

### 3. 실전 구현: Web Worker 기반 WebGPU 추론 파이프라인

이제 메인 스레드와 완전히 격리된 전용 Web Worker에서 `Qwen2.5-1.5B-Instruct` 양자화 모델(ONNX INT4 WebGPU 최적화 버전)을 로드하고, 토큰 단위 스트리밍 디코딩을 수행하는 코드를 작성합니다.

#### (1) `worker.js`: WebGPU 엔진 백엔드 런타임

```javascript
// worker.js: Web Worker 환경에서 가동되는 온디바이스 LLM 엔진
import { pipeline, env, TextStreamer } from '@huggingface/transformers';

// 1. 브라우저 WebGPU 가속 활성화 및 로컬 캐시 엔진 최적화
env.backends.onnx.wasm.numThreads = navigator.hardwareConcurrency || 4;
env.backends.onnx.wasm.simd = true;

// 로컬 환경 및 OPFS 캐싱 우선 정책 적용
env.useBrowserCache = true;
env.allowLocalModels = false;

let generatorPipeline = null;

// 모델 파이프라인 싱글톤 초기화 함수
async function initializePipeline(modelId, progressCallback) {
    if (generatorPipeline) return generatorPipeline;

    progressCallback({ status: 'init', message: 'WebGPU 하드웨어 장치 바인딩 중...' });

    // WebGPU 어댑터 가용성 검증
    if (!navigator.gpu) {
        throw new Error('이 브라우저는 WebGPU를 지원하지 않거나 하드웨어 가속이 꺼져 있습니다.');
    }

    generatorPipeline = await pipeline('text-generation', modelId, {
        device: 'webgpu',       // WebGPU 하드웨어 가속 강제
        dtype: 'q4',            // 4-bit 양자화 가중치 로드 (VRAM 사용량 최소화)
        progress_callback: (data) => {
            // 다운로드 청크 진행도 메인 스레드로 릴레이
            if (data.status === 'progress') {
                progressCallback({
                    status: 'downloading',
                    file: data.file,
                    progress: Math.round((data.loaded / data.total) * 100)
                });
            }
        }
    });

    progressCallback({ status: 'ready', message: '추론 엔진 초기화 완료' });
    return generatorPipeline;
}

// 2. 메시지 수신 핸들러 (메인 스레드와 IPC)
self.onmessage = async (event) => {
    const { type, payload } = event.data;

    if (type === 'LOAD_MODEL') {
        try {
            await initializePipeline(payload.modelId, (statusUpdate) => {
                self.postMessage({ type: 'STATUS_UPDATE', payload: statusUpdate });
            });
        } catch (error) {
            self.postMessage({ type: 'ERROR', payload: error.message });
        }
    }

    if (type === 'GENERATE') {
        if (!generatorPipeline) {
            self.postMessage({ type: 'ERROR', payload: '모델이 로드되지 않았습니다.' });
            return;
        }

        const { messages, maxTokens = 512, temperature = 0.7 } = payload;

        try {
            // 커스텀 텍스트 스트리머 정의: 토큰이 생성될 때마다 메인 스레드로 즉각 푸시
            const streamer = new TextStreamer(generatorPipeline.tokenizer, {
                skip_prompt: true,
                skip_special_tokens: true,
                callback_function: (tokenText) => {
                    self.postMessage({
                        type: 'TOKEN_STREAM',
                        payload: { token: tokenText }
                    });
                }
            });

            // 채팅 템플릿 적용 및 추론 수행
            const output = await generatorPipeline(messages, {
                max_new_tokens: maxTokens,
                temperature: temperature,
                top_p: 0.9,
                do_sample: temperature > 0.0,
                streamer: streamer,
                return_full_text: false
            });

            self.postMessage({
                type: 'GENERATION_COMPLETE',
                payload: { fullResponse: output[0].generated_text }
            });
        } catch (inferenceError) {
            self.postMessage({ type: 'ERROR', payload: inferenceError.message });
        }
    }
};
```

#### (2) `main.js`: 메인 스레드 비동기 제어 인터페이스

```javascript
// main.js: 프론트엔드 UI 연동 및 Worker 수명 주기 관리
class OnDeviceLLMClient {
    constructor(workerPath) {
        this.worker = new Worker(workerPath, { type: 'module' });
        this.onTokenCallback = null;
        this.onStatusCallback = null;
        this.onCompleteCallback = null;

        this._setupListeners();
    }

    _setupListeners() {
        this.worker.onmessage = (event) => {
            const { type, payload } = event.data;
            switch (type) {
                case 'STATUS_UPDATE':
                    if (this.onStatusCallback) this.onStatusCallback(payload);
                    break;
                case 'TOKEN_STREAM':
                    if (this.onTokenCallback) this.onTokenCallback(payload.token);
                    break;
                case 'GENERATION_COMPLETE':
                    if (this.onCompleteCallback) this.onCompleteCallback(payload.fullResponse);
                    break;
                case 'ERROR':
                    console.error('[WebGPU SLM Engine Error]:', payload);
                    break;
            }
        };
    }

    async loadModel(modelId = 'onnx-community/Qwen2.5-1.5B-Instruct') {
        this.worker.postMessage({
            type: 'LOAD_MODEL',
            payload: { modelId }
        });
    }

    generate(messages, options = {}) {
        this.worker.postMessage({
            type: 'GENERATE',
            payload: {
                messages,
                maxTokens: options.maxTokens || 256,
                temperature: options.temperature ?? 0.6
            }
        });
    }

    onToken(callback) { this.onTokenCallback = callback; }
    onStatus(callback) { this.onStatusCallback = callback; }
    onComplete(callback) { this.onCompleteCallback = callback; }
}

// 실전 사용 예시
const client = new OnDeviceLLMClient('./worker.js');

client.onStatus((status) => {
    console.log(`[엔진 상태] ${status.message || status.file + ': ' + status.progress + '%'}`);
});

client.onToken((token) => {
    // 실시간 DOM 스트리밍 업데이트 (렌더링 프레임 드랍 없음)
    const outputElement = document.getElementById('chat-stream');
    outputElement.textContent += token;
});

client.onComplete(() => {
    console.log('[완료] 스트리밍 토큰 생성 종료');
});

// 모델 로드 시작
client.loadModel('onnx-community/Qwen2.5-1.5B-Instruct');

// 사용자 질의 트리거
function askQuestion(userPrompt) {
    const messages = [
        { role: 'system', content: '당신은 브라우저에서 직접 로컬 구동되는 유능한 AI 어시스턴트입니다.' },
        { role: 'user', content: userPrompt }
    ];
    client.generate(messages);
}
```

---

### 4. 프로덕션 운영 최적화 지표: 메모리 바운드 극복 및 Fallback 전략

브라우저 내 WebGPU 추론 엔진을 대규모 사용자를 대상으로 서비스할 때 반드시 점검해야 하는 실전 엔지니어링 체크리스트입니다:

1. **VRAM 고갈 방어(Auto-Garbage Disposal)**:
   브라우저의 탭 간 전환이나 장시간 세션 유지 시 WebGPU 버퍼가 해제되지 않아 다른 앱의 그래픽 드라이버 크래시를 유발할 수 있습니다. `pipeline.dispose()`를 주기적으로 호출하거나 세션 비활성화 시 명시적으로 Worker를 종료(`worker.terminate()`)해야 합니다.
2. **WebGPU 하드웨어 미지원 기기 Fallback 계층**:
   구형 브라우저나 가상 머신 환경에서는 WebGPU 어댑터를 가져올 수 없습니다. 이 경우 `navigator.gpu` 감지 분기를 통해 **WASM(SIMD 다중 스레드) CPU 런타임**으로 스위칭하거나, 최종적으로 경량화된 클라우드 LLM 엔드포인트(API Gateway)로 폴백하는 점진적 향상(Progressive Enhancement) 설계를 갖추어야 합니다.
3. **KV 캐시 메모리 윈도우잉**:
   온디바이스 환경에서는 컨텍스트 윈도우가 커질수록 주의 집중(Attention) 매트릭스의 KV 캐시가 클라이언트 RAM을 기하급수적으로 잠식합니다. `Sliding Window Attention` 파라미터를 강제하여 최대 문맥 길이를 4K 수준으로 바운딩하는 것이 시스템 안정성을 유지하는 핵심입니다.

---

### 결론: 제로 인프라 비용과 진정한 프라이버시의 결합

WebGPU와 최신 브라우저 기반 SLM 런타임의 도래는 엔터프라이즈 프론트엔드 및 AI 아키텍처에 근본적인 패러다임 전환을 가져왔습니다. 서버 비용을 완전히 $0으로 절감하면서도, 유럽의 GDPR이나 의료/금융 분야의 엄격한 데이터 규제를 받는 민감 문서를 클라이언트 내부에서 로컬 처리하는 아키텍처가 실전 영역으로 진입했습니다.

클라우드 거대 모델은 고차원적 복합 추론과 오케스트레이션에 집중시키고, 실시간 에디터 자동완성, 문서 요약, 민감한 개인정보 마스킹과 같은 작업은 WebGPU 기반 온디바이스 파이프라인으로 전면 오프로드하십시오. 인프라 비용의 극적인 절감과 사용자 체감 반응 속도의 즉각적인 개선을 동시에 쟁취할 수 있습니다.