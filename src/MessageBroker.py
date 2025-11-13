from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, List
from uuid import uuid4

app = FastAPI(
    title="Message Broker",
    version="1.0.0",
    description="Python-based message broker for microservices"
)

# topic -> service -> list[Message]
queues: Dict[str, Dict[str, List[dict]]] = {}


class RegisterRequest(BaseModel):
    service_name: str
    topics: List[str]


class PublishRequest(BaseModel):
    topic: str
    message: dict  # payload is generic JSON


@app.post("/register")
def register(req: RegisterRequest):
    """
    A service calls this to subscribe to topics.
    """
    for topic in req.topics:
        if topic not in queues:
            queues[topic] = {}
        if req.service_name not in queues[topic]:
            queues[topic][req.service_name] = []

    return {"status": "ok", "registered_topics": req.topics}


@app.post("/publish")
def publish(req: PublishRequest):
    """
    Any service calls this to publish a message to a topic.
    Broker pushes it to all queues of subscribed services.
    """
    if req.topic not in queues:
        # nobody subscribed yet, but not an error
        return {"status": "ok", "delivered_to": 0}

    delivered = 0
    for service_name, q in queues[req.topic].items():
        msg = {
            "id": str(uuid4()),
            "topic": req.topic,
            "payload": req.message,
        }
        q.append(msg)
        delivered += 1

    return {"status": "ok", "delivered_to": delivered}


@app.get("/consume/{service_name}/{topic}")
def consume(service_name: str, topic: str, max_messages: int = 1):
    """
    Service pulls its messages from a topic.
    """
    if topic not in queues or service_name not in queues[topic]:
        raise HTTPException(status_code=404, detail="No subscription for this service/topic")

    q = queues[topic][service_name]
    msgs = q[:max_messages]
    queues[topic][service_name] = q[max_messages:]

    return {"messages": msgs}
