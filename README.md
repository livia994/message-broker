# Message Broker

This repository contains a lightweight Message Broker microservice built with FastAPI.
It provides simple publish/subscribe communication between microservices using in-memory queues.

The broker supports:
* registering services to topics
* publishing messages
* consuming queued messages

It is containerized with Docker and includes a GitHub Actions workflow for automatic multi-architecture image builds.

------------------------------------------------------------

## Features

* FastAPI-based message broker
* Simple Pub/Sub message flow
* Endpoints:
  * POST /register
  * POST /publish
  * GET /consume/{service}/{topic}
* In-memory message queues
* Docker build support
* CI/CD using GitHub Actions

------------------------------------------------------------

## Project Structure

message-broker/
├─ src/
│  └─ MessageBroker.py
├─ requirements.txt
├─ Dockerfile
└─ .github/
   └─ workflows/
      └─ docker-image.yml

------------------------------------------------------------

## API Endpoints

### Register a service
POST /register

Body:
{
  "service_name": "example-service",
  "topics": ["example.topic"]
}

------------------------------------------------------------

### Publish a message
POST /publish

Body:
{
  "topic": "example.topic",
  "message": { "key": "value" }
}

------------------------------------------------------------

### Consume messages
GET /consume/{service_name}/{topic}

Example:
GET /consume/example-service/example.topic

------------------------------------------------------------

## Local Development

Install dependencies:
pip install -r requirements.txt

Run the service:
uvicorn src.MessageBroker:app --reload --host 0.0.0.0 --port 8000

API docs:
http://localhost:8000/docs

------------------------------------------------------------

## Running with Docker

Build image:
docker build -t message-broker .

Run container:
docker run -p 8000:8000 message-broker

------------------------------------------------------------

## CI/CD

A GitHub Actions workflow is included to:
* build multi-architecture Docker images
* push them to Docker Hub automatically

Workflow file:
.github/workflows/docker-image.yml
