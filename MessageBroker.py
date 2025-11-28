from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Deque, Optional
from uuid import uuid4
from concurrent import futures
import uuid
import json
import time
import grpc
import os
import threading
import logging
import itertools
from collections import deque
from pathlib import Path

import message_pb2
import message_pb2_grpc

GRPC_PORT = "50051"

app = FastAPI(
    title="Message Broker",
    version="3.0.0",
    description="Python-based durable message broker with gRPC and fair dispatch load balancing (custom broker)"
)


class RegisterRequest(BaseModel):
    service_name: str
    topics: List[str]


class PublishRequest(BaseModel):
    topic: str
    message: dict



class DurableQueueBroker:
    """
    Very simple, file-backed durable queue broker.

    - Each topic is a separate queue.
    - Messages are kept in memory (deque) and persisted to disk as JSON Lines.
    - Dead letters are persisted under <data_dir>/dead_letters/<topic>.jsonl
    """
    def list_dead_letters_for_topic(self, topic: str, limit: int = 100) -> List[dict]:
        """
        Return up to `limit` dead-letter items for a single topic (most recent first by timestamp_ms).
        """
        items = []
        with self._lock:
            dq = self._dead_letters.get(topic, deque())
            items = list(dq)
        # sort descending by timestamp if present
        try:
            items.sort(key=lambda d: int(d.get("timestamp_ms", 0)), reverse=True)
        except Exception:
            pass
        return items[:limit]
        
    def __init__(self, data_dir: str = "broker_data"):
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)

        # Dead letters directory
        self._dead_dir = self._data_dir / "dead_letters"
        self._dead_dir.mkdir(parents=True, exist_ok=True)

        self._queues: Dict[str, Deque[dict]] = {}
        self._dead_letters: Dict[str, Deque[dict]] = {}
        self._lock = threading.Lock()
        self._load_existing()

    def _topic_file(self, topic: str) -> Path:
        safe_topic = topic.replace("/", "_")
        return self._data_dir / f"{safe_topic}.jsonl"

    def _deadletter_file(self, topic: str) -> Path:
        safe_topic = topic.replace("/", "_")
        return self._dead_dir / f"{safe_topic}.jsonl"

    def _load_existing(self):
        """
        Load existing queues and dead letters from disk at startup.
        """
        # load normal topic queues
        for file in self._data_dir.glob("*.jsonl"):
            topic = file.stem
            dq: Deque[dict] = deque()
            try:
                with file.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        dq.append(json.loads(line))
            except Exception:
                dq = deque()
            self._queues[topic] = dq

        # load existing dead letters, keep them centralized under data_dir/dead_letters
        for file in self._dead_dir.glob("*.jsonl"):
            topic = file.stem
            dq: Deque[dict] = deque()
            try:
                with file.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        dq.append(json.loads(line))
            except Exception:
                dq = deque()
            self._dead_letters[topic] = dq

    def declare_queue(self, name: str):
        with self._lock:
            if name not in self._queues:
                self._queues[name] = deque()
                file = self._topic_file(name)
                if not file.exists():
                    file.touch()

    def _rewrite_file(self, topic: str):
        file = self._topic_file(topic)
        dq = self._queues.get(topic, deque())
        with file.open("w", encoding="utf-8") as f:
            for msg in dq:
                f.write(json.dumps(msg) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def publish(self, topic: str, message: dict):
        with self._lock:
            if topic not in self._queues:
                self._queues[topic] = deque()
            self._queues[topic].append(message)
            file = self._topic_file(topic)
            with file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(message) + "\n")
                f.flush()
                os.fsync(f.fileno())

    def consume_one(self, topic: str) -> Optional[dict]:
        with self._lock:
            if topic not in self._queues or not self._queues[topic]:
                return None
            msg = self._queues[topic].popleft()
            self._rewrite_file(topic)
            return msg

    def consume_many(self, topic: str, max_messages: int) -> List[dict]:
        out: List[dict] = []
        with self._lock:
            if topic not in self._queues:
                self._queues[topic] = deque()
            dq = self._queues[topic]
            for _ in range(max_messages):
                if not dq:
                    break
                out.append(dq.popleft())
            if out:
                self._rewrite_file(topic)
        return out

    # -------- Dead letter operations --------
    def publish_dead_letter(self, topic: str, dead_message: dict):
        """
        Persist a dead-letter message for the given topic (durably).
        dead_message should include at least: id, topic, payload, reason, timestamp_ms, attempt_count
        """
        with self._lock:
            if topic not in self._dead_letters:
                self._dead_letters[topic] = deque()
            self._dead_letters[topic].append(dead_message)
            file = self._deadletter_file(topic)
            with file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(dead_message) + "\n")
                f.flush()
                os.fsync(f.fileno())

    def list_dead_letters(self, limit: int = 100) -> List[dict]:
        """
        Return up to `limit` dead-letter items across all topics, most recent first (by timestamp_ms).
        """
        items = []
        with self._lock:
            for dq in self._dead_letters.values():
                items.extend(list(dq))
        # sort if timestamp present; otherwise preserve insertion order
        try:
            items.sort(key=lambda d: int(d.get("timestamp_ms", 0)), reverse=True)
        except Exception:
            pass
        return items[:limit]


# Global broker instance (durable across process restarts via files)
BROKER_DATA_DIR = os.getenv("BROKER_DATA_DIR", "broker_data")
broker = DurableQueueBroker(data_dir=BROKER_DATA_DIR)



class MessageBrokerService(message_pb2_grpc.MessageBrokerServiceServicer):

    def PublishDeadLetter(self, request, context):
        """
        gRPC method for publishing a dead-letter entry.
        Uses fields present in the proto message.
        """
        try:
            # Build dictionary from gRPC request (DeadLetter)
            dl = {
                "id": request.id if hasattr(request, "id") else str(uuid4()),
                "source_service": request.source_service if hasattr(request, "source_service") else "",
                "target_service": request.target_service if hasattr(request, "target_service") else "",
                "topic": request.topic if hasattr(request, "topic") else "",
                "payload": json.loads(request.payload) if request.payload else request.payload,
                "reason": request.reason if hasattr(request, "reason") else "",
                "attempt_count": int(request.attempt_count) if hasattr(request, "attempt_count") else 0,
                "timestamp_ms": int(request.timestamp_ms) if hasattr(request, "timestamp_ms") else int(time.time() * 1000)
            }

            # persist to broker dead letters (topic-based)
            dl_topic = dl.get("topic", "unknown")
            broker.publish_dead_letter(dl_topic, dl)

            return message_pb2.DeadLetterAck(ok=True)
        except Exception as e:
            print(f"Error publishing dead letter: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return message_pb2.DeadLetterAck(ok=False)

    def ListDeadLetters(self, request, context):
        """
        gRPC method to list dead letters.
        """
        try:
            limit = int(request.limit) if hasattr(request, "limit") else 100
            items = broker.list_dead_letters(limit=limit)
            # Build response
            resp = message_pb2.ListDeadLettersResponse()
            for item in items:
                p = message_pb2.DeadLetter(
                    id=item.get("id", ""),
                    source_service=item.get("source_service", ""),
                    target_service=item.get("target_service", ""),
                    topic=item.get("topic", ""),
                    payload=json.dumps(item.get("payload", "")) if item.get("payload") is not None else "",
                    reason=item.get("reason", ""),
                    attempt_count=int(item.get("attempt_count", 0)),
                    timestamp_ms=int(item.get("timestamp_ms", 0))
                )
                resp.items.append(p)
            return resp
        except Exception as e:
            print(f"Error listing deadletters: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return message_pb2.ListDeadLettersResponse()
    
    def SendMessage(self, request, context):
        """Handle gRPC message publishing with fair dispatch support (via custom broker)."""
        try:
            queue_name = request.topic

            # Ensure queue exists (durable)
            broker.declare_queue(queue_name)

            msg = {
                "id": str(uuid4()),
                "topic": request.topic,
                "payload": json.loads(request.payload),
                "reply_to": request.reply_to if request.reply_to else None
            }

            # Publish to custom durable broker
            broker.publish(queue_name, msg)

            print(f"Message published to queue '{queue_name}' with custom durable broker (fair dispatch via FIFO)")

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
        """Handle gRPC message consumption with fair dispatch (FIFO per-topic)."""
        try:
            # Ensure queue exists
            broker.declare_queue(request.topic)

            # Get one message (FIFO for fair-ish dispatch)
            msg = broker.consume_one(request.topic)

            if msg is None:
                return message_pb2.ReceiveMessageResponse(
                    has_message=False,
                    message_id="",
                    topic="",
                    payload="",
                    reply_to=""
                )

            print(f"Message consumed from queue '{request.topic}' (custom broker, FIFO fair dispatch)")

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
    print(f"gRPC server started on port {GRPC_PORT} with fair dispatch load balancing (custom broker)")
    server.wait_for_termination()





@app.get("/health")
def health():
    return {
        "status": "healthy",
        "load_balancing": "fair_dispatch",
        "broker": "custom_durable_file_backed"
    }


@app.post("/register")
def register(req: RegisterRequest):
    """Register service topics with fair dispatch (creates durable queues in custom broker)."""
    for topic in req.topics:
        queue_name = f"{topic}.{req.service_name}"
        broker.declare_queue(queue_name)
        print(f"Registered queue: {queue_name} with custom durable broker (fair dispatch FIFO)")
    return {
        "status": "ok",
        "registered_topics": req.topics,
        "load_balancing": "fair_dispatch",
        "broker": "custom_durable_file_backed"
    }


@app.post("/publish")
def publish(req: PublishRequest):
    """Publish message with fair dispatch using custom durable broker."""
    queue_name = req.topic

    # Ensure durable queue exists in custom broker
    broker.declare_queue(queue_name)

    msg = {
        "id": str(uuid4()),
        "topic": req.topic,
        "payload": req.message
    }

    broker.publish(queue_name, msg)
    print(f"REST: Message published to '{queue_name}' with custom durable broker (FIFO fair dispatch)")
    return {
        "status": "ok",
        "delivered_to": 1,
        "load_balancing": "fair_dispatch",
        "broker": "custom_durable_file_backed"
    }


@app.get("/consume/{topic}")
def consume(topic: str, max_messages: int = 1):
    """Consume messages with fair dispatch using custom broker (FIFO)."""
    broker.declare_queue(topic)
    messages = broker.consume_many(topic, max_messages)
    print(f"REST: Consumed {len(messages)} message(s) from '{topic}' using custom durable broker")
    return {
        "messages": messages,
        "load_balancing": "fair_dispatch",
        "broker": "custom_durable_file_backed"
    }

@app.post("/deadletter/publish")
def publish_deadletter(payload: dict):
    """
    Persist a dead-letter JSON object to the dead-letter store.
    Expected JSON shape:
      {
        "id": "orig-id",
        "source_service": "producer",
        "target_service": "consumer",
        "topic": "topic.name",
        "payload": {...},
        "reason": "description",
        "attempt_count": 3,
        "timestamp_ms": 1234567890
      }
    """
    try:
        # Basic sanity
        topic = payload.get("topic", "unknown")
        # Add fallback fields
        entry = {
            "id": payload.get("id") or str(uuid4()),
            "source_service": payload.get("source_service"),
            "target_service": payload.get("target_service"),
            "topic": topic,
            "payload": payload.get("payload"),
            "reason": payload.get("reason"),
            "attempt_count": int(payload.get("attempt_count") or 0),
            "timestamp_ms": int(payload.get("timestamp_ms") or int(time.time() * 1000))
        }
        broker.publish_dead_letter(topic, entry)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/deadletter/list")
def list_deadletters(limit: int = 100):
    try:
        items = broker.list_dead_letters(limit=limit)
        return {"items": items, "count": len(items)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/deadletter/list/{topic}")
def list_deadletters_for_topic(topic: str, limit: int = 100):
    """
    List dead-letter messages for a specific topic.
    Example: GET /deadletter/list/my.topic?limit=50
    """
    try:
        items = broker.list_dead_letters_for_topic(topic, limit=limit)
        return {"items": items, "count": len(items)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
    import uvicorn

    print("=" * 60)
    print("Message Broker starting with Fair Dispatch Load Balancing")
    print("Backend: Custom Durable File-backed Broker (no RabbitMQ)")
    print("=" * 60)

    # Start gRPC server in a separate thread
    grpc_thread = threading.Thread(target=serve_grpc, daemon=True)
    grpc_thread.start()

    # Start FastAPI server
    uvicorn.run(app, host="0.0.0.0", port=8001)
