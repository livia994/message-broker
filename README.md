# Message Broker

This repository contains a lightweight **Message Broker microservice** built with **FastAPI**.  
It enables simple **publish/subscribe (Pub/Sub)** communication between microservices using in-memory queues.

The broker supports:
- Registering services to topics  
- Publishing messages  
- Consuming queued messages  

It is fully containerized with Docker and includes a GitHub Actions workflow for automatic **multi-architecture (amd64 + arm64)** image builds.

---

## Features

- FastAPI-based microservice  
- Simple Pub/Sub messaging model  
- Endpoints:
  - `POST /register`
  - `POST /publish`
  - `GET /consume/{service}/{topic}`
- In-memory message queues  
- Docker support  
- GitHub Actions CI/CD pipeline  

---

## API Endpoints

Below are **clean, copy-ready** examples for each endpoint.

---

### **1. Register a service**

**POST** `/register`

**Body:**
```json
{
  "service_name": "example-service",
  "topics": ["example.topic"]
}
```

---

### **2. Publish a message**

**POST** `/publish`

**Body:**
```json
{
  "topic": "example.topic",
  "message": { "key": "value" }
}
```

---

### **3. Consume messages**

**GET** `/consume/{service_name}/{topic}`

**Example request:**
```
GET /consume/example-service/example.topic
```

Copy-ready URL version:
```
http://localhost:8000/consume/example-service/example.topic
```

---

## Local Development

Install dependencies:
```bash
pip install -r requirements.txt
```

Run the service:
```bash
uvicorn src.MessageBroker:app --reload --host 0.0.0.0 --port 8000
```

Open API docs:
```
http://localhost:8000/docs
```

---

## Running with Docker

Build the image:
```bash
docker build -t message-broker .
```

Run the container:
```bash
docker run -p 8000:8000 message-broker
```

---

## CI/CD Pipeline

A GitHub Actions workflow is included to:

- Build **multi-architecture** Docker images  
- Push the images to Docker Hub automatically  

Workflow file:
```
.github/workflows/docker-image.yml
```
