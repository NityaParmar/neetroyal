# 👑 NEET Royale v1.0 | Gamified Platform: Compete. Analyze. Improve

<div align="center">
  <img src="https://img.shields.io/badge/Status-Live_v1.0-emerald?style=for-the-badge" alt="Status" />
  <img src="https://img.shields.io/badge/Architecture-Microservices-blue?style=for-the-badge" alt="Architecture" />
  <img src="https://img.shields.io/badge/Stack-React_|_Node_|_Python-black?style=for-the-badge" alt="Stack" />
</div>

> **Eliminate high-stakes exam burnout.** NEET Royale is a distributed, AI-powered platform that transforms passive NEET preparation into competitive, real-time 1v1 survival battles driven by a live Retrieval-Augmented Generation (RAG) engine.

---

## 🚀 The Vision
Preparing for competitive exams like NEET is isolating and mentally exhausting. NEET Royale introduces a **Gamified Telemetry Engine** where aspirants face off in live 1v1 duels, answering verified NTA past-paper questions extracted and evaluated dynamically by AI. 

---

## 🏛️ Enterprise System Architecture

Built as a highly scalable **Turborepo Monorepo**, the system decouples the frontend, real-time sync, HTTP routing, and heavy AI processing across four independent microservices.

```text
                      +-------------------------+
                      |  React 19 / Vite Arena  | (Port 5173 - The Frontend)
                      +------------+------------+
                                   | HTTP / WebSockets
                                   v
                      +-------------------------+
                      | Node.js / Express Gateway| (Port 3001 & 8080 - The Manager)
                      +------------+------------+
                                   | REST API / IPC
                                   v
                      +-------------------------+
                      |   FastAPI Python Engine | (Port 8000 - The RAG AI Brain)
                      +-------------------------+
