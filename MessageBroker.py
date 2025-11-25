from pika.exceptions import AMQPConnectionError
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
from uuid import uuid4
from concurrent import futures

import json
import time
import grpc
import pika
import os
import threading
import logging
import itertools
import message_pb2
import message_pb2_grpc

RABBITMQ_HOST = "rabbitmq"
GRPC_PORT = "50051"

app = FastAPI(
    title="Message Broker",
    version="3.0.0",
    description="Python-based durable message broker with gRPC and fair dispatch load balancing"
)


class RegisterRequest(BaseModel):
    service_name: str
    topics: List[str]


class PublishRequest(BaseModel):
    topic: str
    message: dict


def get_channel(retries=5, delay=3):
    """Get RabbitMQ channel with QoS for fair dispatch"""
    for attempt in range(retries):
        try:
            connection = pika.BlockingConnection(
                pika.ConnectionParameters(host=RABBITMQ_HOST)
            )
            channel = connection.channel()

            # Enable fair dispatch - don't give more than 1 message to a worker at a time
            # This ensures round-robin distribution across multiple consumers
            channel.basic_qos(prefetch_count=1)

            return connection, channel
        except AMQPConnectionError:
            print(f"RabbitMQ not ready, retrying... ({attempt + 1}/{retries})")
            time.sleep(delay)
    raise HTTPException(status_code=503, detail="Could not connect to RabbitMQ")


# gRPC Service Implementation
class MessageBrokerService(message_pb2_grpc.MessageBrokerServiceServicer):

    def SendMessage(self, request, context):
        """Handle gRPC message publishing with fair dispatch support"""
        try:
            connection, channel = get_channel()
            queue_name = request.topic

            # Declare queue as durable for persistence
            channel.queue_declare(queue=queue_name, durable=True)

            msg = {
                "id": str(uuid4()),
                "topic": request.topic,
                "payload": json.loads(request.payload),
                "reply_to": request.reply_to if request.reply_to else None
            }

            # Publish message with persistence
            channel.basic_publish(
                exchange="",
                routing_key=queue_name,
                body=json.dumps(msg),
                properties=pika.BasicProperties(
                    delivery_mode=2,  # Make message persistent
                    reply_to=request.reply_to if request.reply_to else None
                )
            )
            connection.close()

            print(f"Message published to queue '{queue_name}' with fair dispatch enabled")

            return message_pb2.SendMessageResponse(
                success=True,
                message_id=msg["id"],
                error_message=""
            )
        except Exception as e:
            print(f"Error publishing message: {str(e)}")
            return message_pb2.SendMessageResponse(
                success=False,
                message_id="",
                error_message=str(e)
            )

    def ReceiveMessage(self, request, context):
        """Handle gRPC message consumption with fair dispatch"""
        try:
            connection, channel = get_channel()

            # Declare queue with fair dispatch QoS
            channel.queue_declare(queue=request.topic, durable=True)

            # Get one message (fair dispatch ensures round-robin)
            method, properties, body = channel.basic_get(queue=request.topic, auto_ack=False)

            if method is None:
                connection.close()
                return message_pb2.ReceiveMessageResponse(
                    has_message=False,
                    message_id="",
                    topic="",
                    payload="",
                    reply_to=""
                )

            msg = json.loads(body.decode())

            # Acknowledge message after retrieval (manual ack for fair dispatch)
            channel.basic_ack(delivery_tag=method.delivery_tag)
            connection.close()

            print(f"Message consumed from queue '{request.topic}' (fair dispatch)")

            return message_pb2.ReceiveMessageResponse(
                has_message=True,
                message_id=msg.get("id", ""),
                topic=msg.get("topic", ""),
                payload=json.dumps(msg.get("payload", {})),
                reply_to=msg.get("reply_to", "")
            )
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return message_pb2.ReceiveMessageResponse()


def serve_grpc():
    """Start gRPC server"""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    message_pb2_grpc.add_MessageBrokerServiceServicer_to_server(
        MessageBrokerService(), server
    )
    server.add_insecure_port(f'[::]:{GRPC_PORT}')
    server.start()
    print(f"gRPC server started on port {GRPC_PORT} with fair dispatch load balancing")
    server.wait_for_termination()


# REST API Endpoints
@app.get("/health")
def health():
    return {"status": "healthy", "load_balancing": "fair_dispatch"}


@app.post("/register")
def register(req: RegisterRequest):
    """Register service topics with fair dispatch"""
    connection, channel = get_channel()
    for topic in req.topics:
        queue_name = f"{topic}.{req.service_name}"
        # Durable queue for persistence
        channel.queue_declare(queue=queue_name, durable=True)
        print(f"Registered queue: {queue_name} with fair dispatch")
    connection.close()
    return {"status": "ok", "registered_topics": req.topics, "load_balancing": "fair_dispatch"}


@app.post("/publish")
def publish(req: PublishRequest):
    """Publish message with fair dispatch"""
    connection, channel = get_channel()
    queue_name = req.topic

    # Declare durable queue
    channel.queue_declare(queue=queue_name, durable=True)

    msg = {
        "id": str(uuid4()),
        "topic": req.topic,
        "payload": req.message
    }

    # Persistent message delivery
    channel.basic_publish(
        exchange="",
        routing_key=queue_name,
        body=json.dumps(msg),
        properties=pika.BasicProperties(
            delivery_mode=2  # Persistent
        )
    )
    connection.close()
    print(f"REST: Message published to '{queue_name}' with fair dispatch")
    return {"status": "ok", "delivered_to": 1, "load_balancing": "fair_dispatch"}


@app.get("/consume/{topic}")
def consume(topic: str, max_messages: int = 1):
    """Consume messages with fair dispatch"""
    connection, channel = get_channel()
    channel.queue_declare(queue=topic, durable=True)

    messages = []
    for _ in range(max_messages):
        method, properties, body = channel.basic_get(queue=topic, auto_ack=False)
        if method is None:
            break
        msg = json.loads(body.decode())
        messages.append(msg)
        # Manual acknowledgment for fair dispatch
        channel.basic_ack(delivery_tag=method.delivery_tag)

    connection.close()
    print(f"REST: Consumed {len(messages)} message(s) from '{topic}'")
    return {"messages": messages, "load_balancing": "fair_dispatch"}


# --- Service High Availability / Circuit Breaker implementation ---

class CircuitBreaker:
    def __init__(self, max_failures: int = 5, reset_timeout: int = 30):
        self._max_failures = int(max_failures)
        self._reset_timeout = float(reset_timeout)
        self._failures = 0
        self._state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self._opened_at = 0.0
        self._lock = threading.Lock()

    def is_available(self) -> bool:
        with self._lock:
            if self._state == "CLOSED":
                return True
            if self._state == "OPEN":
                if time.time() - self._opened_at >= self._reset_timeout:
                    self._state = "HALF_OPEN"
                    return True
                return False
            return True

    def record_success(self):
        with self._lock:
            self._failures = 0
            self._state = "CLOSED"
            self._opened_at = 0.0

    def record_failure(self):
        with self._lock:
            self._failures += 1
            if self._failures >= self._max_failures:
                self._state = "OPEN"
                self._opened_at = time.time()


class ServiceInstance:
    def __init__(self, target: str, max_failures: int = 5, reset_timeout: int = 30):
        self.target = target.strip()
        self.breaker = CircuitBreaker(max_failures=max_failures, reset_timeout=reset_timeout)
        self.channel = None
        self.stub = None
        self._lock = threading.Lock()

        try:
            if hasattr(grpc, "insecure_channel"):
                self.channel = grpc.insecure_channel(self.target)
            for name, obj in vars(message_pb2_grpc).items():
                if name.endswith("Stub") and isinstance(obj, type):
                    self.stub = obj(self.channel)
                    break
        except Exception:
            self.channel = None
            self.stub = None

    def call_rpc(self, rpc_name: str, request, timeout: float = 5.0):
        if not self.stub:
            raise RuntimeError(f"No stub class available in message_pb2_grpc for target {self.target}")

        method = getattr(self.stub, rpc_name, None)
        if method is None:
            raise AttributeError(f"RPC '{rpc_name}' not found on stub for {self.target}")

        return method(request, timeout=timeout)


class ServiceHA:
    def __init__(self, targets: list[str], max_failures: int = 5, reset_timeout: int = 30):
        self.instances = [ServiceInstance(t, max_failures=max_failures, reset_timeout=reset_timeout) for t in (targets or [])]
        self._idx = itertools.cycle(range(len(self.instances))) if self.instances else iter([])
        self._global_lock = threading.Lock()
        self._logger = logging.getLogger("ServiceHA")

    def call(self, rpc_name: str, request, timeout: float = 5.0, tries: int | None = None):
        if not self.instances:
            raise RuntimeError("No backend targets configured for ServiceHA")

        total_instances = len(self.instances)
        tries = tries or total_instances

        last_exc = None
        attempted = set()

        for _ in range(tries):
            with self._global_lock:
                idx = next(self._idx)
            inst = self.instances[idx]

            if idx in attempted:
                continue
            attempted.add(idx)

            if not inst.breaker.is_available():
                self._logger.debug(f"Instance {inst.target} circuit OPEN; skipping")
                continue

            try:
                resp = inst.call_rpc(rpc_name, request, timeout=timeout)
                inst.breaker.record_success()
                return resp
            except grpc.RpcError as e:
                self._logger.warning(f"RPC failed to {inst.target}: {e}; marking failure")
                inst.breaker.record_failure()
                last_exc = e
            except Exception as e:
                self._logger.warning(f"Call to {inst.target} raised: {e}; marking failure")
                inst.breaker.record_failure()
                last_exc = e

        if last_exc:
            raise last_exc

        raise RuntimeError("No healthy backend instances available")


# --- Initialize global ServiceHA from env variable ---
# BACKEND_TARGETS should be comma-separated list like "localhost:50051,localhost:50052"
_targets_env = os.getenv("BACKEND_TARGETS", "localhost:50051").split(",")
BACKEND_MAX_FAILURES = int(os.getenv("BACKEND_CIRCUIT_MAX_FAILURES", "5"))
BACKEND_RESET_TIMEOUT = int(os.getenv("BACKEND_CIRCUIT_RESET_SECS", "30"))

_service_ha = ServiceHA([t.strip() for t in _targets_env if t.strip()],
                        max_failures=BACKEND_MAX_FAILURES,
                        reset_timeout=BACKEND_RESET_TIMEOUT)

def call_rpc_with_ha(rpc_name: str, request, timeout: float = 5.0):
    return _service_ha.call(rpc_name, request, timeout=timeout)

if __name__ == "__main__":
    import threading
    import uvicorn

    print("=" * 60)
    print("Message Broker starting with Fair Dispatch Load Balancing")
    print("Fair Dispatch: prefetch_count=1 (round-robin distribution)")
    print("=" * 60)

    # Start gRPC server in a separate thread
    grpc_thread = threading.Thread(target=serve_grpc, daemon=True)
    grpc_thread.start()

    # Start FastAPI server
    uvicorn.run(app, host="0.0.0.0", port=8001)