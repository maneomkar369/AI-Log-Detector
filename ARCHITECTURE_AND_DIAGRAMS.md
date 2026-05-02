# Architecture and System Diagrams
**Behavioral Log Anomaly Detection Using Machine Learning**

This document provides high-level architectural, network, data, and flow diagrams for the Edge-Based AI Log Detector.

---

## 1. High-Level Architecture Diagram
This diagram outlines the physical deployment and separation of concerns between the Android Client, Edge Server, and the Dashboard.

```mermaid
architecture-beta
    group edge_network(cloud)[Local Edge Network]

    service android_device(mobile)[Android Device]
    service edge_server(server)[Edge Inference Server]
    service db(database)[PostgreSQL + Redis]
    service dashboard(monitor)[Web Dashboard]
    

    edge_network:L -- R:android_device
    edge_network:R -- L:edge_server
    edge_server:B -- T:db
    edge_server:R -- L:dashboard
```

*(Note: The above diagram uses conceptual routing. The actual architecture involves the Android Device sending WebSocket packets over the local network router to the Edge Server. No external cloud provider is used for telemetry processing).*

---

## 2. System and Network Topology
This illustrates the Localized Edge Air-Gap Architecture. All heavy AI processing is localized to the Edge node, protecting user privacy.

```mermaid
graph TD
    subgraph "Android Target Device"
        AM[Accessibility Monitor]
        PM[Permission Monitor]
        VM[Network VPN Flow Service]
        SM[System Log Monitor]
        WC[WebSocket Client]
        
        AM --> WC
        PM --> WC
        VM --> WC
        SM --> WC
    end

    subgraph "Local Network Router"
        WIFI((Wi-Fi / LAN Bridge))
    end

    subgraph "Edge Computing Node (Dockerized)"
        API[FastAPI Gateway]
        REDIS[(Redis Event Bus)]
        ML[Anomaly Detection Engine]
        DB[(PostgreSQL)]
        DASH[Flask Dashboard]
    end

    WC -- "Secure WebSocket (JSON)" --> WIFI
    WIFI -- "TCP/IP" --> API

    API -- "Publishes Event" --> REDIS
    API -- "Updates Baseline" --> DB
    
    REDIS -- "Consumes Event" --> ML
    ML -- "Scores Vector" --> DB
    
    ML -- "Emits Alert" --> REDIS
    REDIS -- "Streams Live Data" --> DASH
    
    DASH -- "Web UI" --> Admin([Security Admin])
```

---

## 3. Data Flow Diagram (The ML Pipeline)
This diagram maps how raw telemetry is aggregated into a mathematical matrix and processed for anomalies.

```mermaid
sequenceDiagram
    participant AD as Android Device
    participant FE as Feature Extractor
    participant BM as Baseline Manager
    participant ML as Mahalanobis Engine
    participant XAI as Explainability Engine

    AD->>FE: Stream Raw Events (App usage, Network, Keys)
    FE->>FE: Group into 10-second Temporal Windows
    FE->>FE: Construct 72-Dimension Feature Vector (x)
    
    FE->>BM: Request Baseline Profile for Device
    alt Device Age < 24 Hours
        BM-->>FE: Return Generic Baseline (μ₀, Σ₀)
    else Device Age < 8 Days
        BM-->>FE: Return Blended Baseline (αμ₀ + (1-α)μ_p)
    else Mature Device
        BM-->>FE: Return Personalized Baseline (μ_p, Σ_p)
    end
    
    FE->>ML: Pass Vector (x) and Baseline (μ, Σ)
    ML->>ML: Compute Masked Mahalanobis Distance (D_M)
    
    alt D_M > Dynamic Threshold (τ)
        ML->>XAI: Request Deterministic Explanation
        XAI->>XAI: Compute Cholesky Factor L = Σ⁻¹/²
        XAI->>XAI: Whiten Vector z = L(x - μ)
        XAI-->>ML: Return Feature Contributions (z_i²)
        ML-->>AD: Trigger Alert & Dashboard Warning
    else D_M <= Dynamic Threshold (τ)
        ML->>BM: Send Vector for EMA Adaptation
        BM->>BM: Update Mean and Covariance (No Drift)
    end
```

---

## 4. Concept Drift vs. Anomaly Detection Flow
This flowchart demonstrates the logic inside the `SelfTuningCUSUM` module, which handles the "Concept Drift vs. Anomaly" challenge.

```mermaid
flowchart TD
    Start([Incoming Feature Vector x]) --> Extract[Extract Mahalanobis Distance D]
    Extract --> Compare{Is D > Dynamic Threshold τ?}
    
    Compare -- Yes --> PoisonCheck{Is Event Malicious?}
    PoisonCheck -- Yes (Malware) --> Drop[Flag Anomaly. Do NOT update baseline.]
    PoisonCheck -- No (User Drift) --> CUSUM[Feed into CUSUM Accumulator S_t]
    
    Compare -- No --> CUSUM
    
    CUSUM --> DriftCheck{Is S_t > h?}
    
    DriftCheck -- Yes (Behavior Shift) --> Boost[Multiply Adaptation Rate α by 5x]
    Boost --> EMA[Update EMA Baseline with boosted α]
    
    DriftCheck -- No (Stable) --> Standard[Use standard slow Adaptation Rate α]
    Standard --> EMA
    
    EMA --> End([Process Next Window])
    Drop --> End
```
