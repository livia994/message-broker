import json
import time
import pika
from pika.exceptions import AMQPConnectionError
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
from uuid import uuid4

RABBITMQ_HOST = "rabbitmq"

app = FastAPI(
    title="Message Broker",
    version="2.0.0",
    description="Python-based durable message broker for microservices"
)


class RegisterRequest(BaseModel):
    service_name: str
    topics: List[str]


class PublishRequest(BaseModel):
    topic: str
    message: dict


def get_channel(retries=5, delay=3):
    for attempt in range(retries):
        try:
            connection = pika.BlockingConnection(
                pika.ConnectionParameters(host=RABBITMQ_HOST)
            )
            channel = connection.channel()
            return connection, channel
        except AMQPConnectionError:
            print(f"RabbitMQ not ready, retrying... ({attempt+1}/{retries})")
            time.sleep(delay)

    raise HTTPException(status_code=503, detail="Could not connect to RabbitMQ")


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/register")
def register(req: RegisterRequest):
    connection, channel = get_channel()

    for topic in req.topics:
        queue_name = f"{topic}.{req.service_name}"
        channel.queue_declare(queue=queue_name, durable=True)

    connection.close()
    return {"status": "ok", "registered_topics": req.topics}


@app.post("/publish")
def publish(req: PublishRequest):
    connection, channel = get_channel()

    queue_name = req.topic
    channel.queue_declare(queue=queue_name, durable=True)

    msg = {
        "id": str(uuid4()),
        "topic": req.topic,
        "payload": req.message
    }

    channel.basic_publish(
        exchange="",
        routing_key=queue_name,
        body=json.dumps(msg),
        properties=pika.BasicProperties(
            delivery_mode=2
        )
    )

    connection.close()
    return {"status": "ok", "delivered_to": 1}


@app.get("/consume/{topic}")
def consume(topic: str, max_messages: int = 1):
    connection, channel = get_channel()

    channel.queue_declare(queue=topic, durable=True)

    messages = []

    for _ in range(max_messages):
        method, properties, body = channel.basic_get(queue=topic, auto_ack=False)

        if method is None:
            break

        msg = json.loads(body.decode())
        messages.append(msg)

        channel.basic_ack(delivery_tag=method.delivery_tag)

    connection.close()
    return {"messages": messages}
