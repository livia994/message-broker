# Message Broker Service 

A high-performance, durable message broker implementation built with Python, FastAPI, and gRPC. This service provides reliable message delivery with fair dispatch load balancing, circuit breaker patterns, and service high availability.


## Features

### Core Functionality
- **Dual Protocol Support**: REST (FastAPI) and gRPC interfaces
- **Durable Message Storage**: File-backed persistence ensures no message loss across restarts
- **Fair Dispatch Load Balancing**: FIFO-based message distribution
- **Circuit Breaker Pattern**: Automatic fault detection and recovery
- **Service High Availability**: Intelligent request routing across multiple service instances
- **Thread-per-Request Architecture**: Concurrent message processing

### Advanced Capabilities
- **Topic-based Messaging**: Pub/Sub pattern for service-to-service communication
- **Queue-based Messaging**: Direct message routing for gateway-to-service communication
- **Custom Broker Implementation**: No external dependencies (RabbitMQ-free)
- **Health Monitoring**: Built-in health check endpoints

## Architecture

```
┌─────────────────────────────────────────┐
│         Message Broker Service          │
├─────────────────┬───────────────────────┤
│   FastAPI       │      gRPC Server      │
│   (Port 8001)   │      (Port 50051)     │
└────────┬────────┴──────────┬────────────┘
         │                   │
         └─────────┬─────────┘
                   ▼
         ┌──────────────────┐
         │ DurableQueueBroker│
         │  (File-backed)   │
         └──────────────────┘
                   │
         ┌─────────┴─────────┐
         ▼                   ▼
    [Topic Queues]     [Service Queues]
    (.jsonl files)     (Persistent)
```

## 🚀 Getting Started

### Prerequisites
- Python 3.9+
- Docker (optional)
- Protocol Buffers compiler (for gRPC)

### Installation

1. **Clone the repository**
```bash
git clone <your-repo-url>
cd message-broker
```

2. **Install dependencies**
```bash
pip install -r requirements.txt
```

3. **Generate gRPC code** (if not already present)
```bash
python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. message.proto
```

4. **Run the service**
```bash
python MessageBroker.py
```

The service will start on:
- REST API: `http://localhost:8001`
- gRPC: `localhost:50051`

### Docker Deployment

```bash
# Build the image
docker build -t message-broker:latest .

# Run the container
docker run -p 8001:8001 -p 50051:50051 \
  -v $(pwd)/broker_data:/app/broker_data \
  message-broker:latest
```

##  API Reference

### REST Endpoints

#### Health Check
```http
GET /health
```
Returns broker status and configuration.

**Response:**
```json
{
  "status": "healthy",
  "load_balancing": "fair_dispatch",
  "broker": "custom_durable_file_backed"
}
```

#### Register Service
```http
POST /register
Content-Type: application/json

{
  "service_name": "user-service",
  "topics": ["user.created", "user.updated"]
}
```

**Response:**
```json
{
  "status": "ok",
  "registered_topics": ["user.created", "user.updated"],
  "load_balancing": "fair_dispatch",
  "broker": "custom_durable_file_backed"
}
```

#### Publish Message
```http
POST /publish
Content-Type: application/json

{
  "topic": "user.created",
  "message": {
    "user_id": "123",
    "email": "user@example.com"
  }
}
```

**Response:**
```json
{
  "status": "ok",
  "delivered_to": 1,
  "load_balancing": "fair_dispatch",
  "broker": "custom_durable_file_backed"
}
```

#### Consume Messages
```http
GET /consume/{topic}?max_messages=10
```

**Response:**
```json
{
  "messages": [
    {
      "id": "uuid-here",
      "topic": "user.created",
      "payload": {"user_id": "123", "email": "user@example.com"}
    }
  ],
  "load_balancing": "fair_dispatch",
  "broker": "custom_durable_file_backed"
}
```

### gRPC Methods

#### SendMessage
Publishes a message to a specific topic.

```protobuf
message SendMessageRequest {
  string topic = 1;
  string payload = 2;
  string reply_to = 3;
}

message SendMessageResponse {
  bool success = 1;
  string message_id = 2;
  string error_message = 3;
}
```

#### ReceiveMessage
Consumes a message from a topic.

```protobuf
message ReceiveMessageRequest {
  string topic = 1;
}

message ReceiveMessageResponse {
  bool has_message = 1;
  string message_id = 2;
  string topic = 3;
  string payload = 4;
  string reply_to = 5;
}
```

## ⚙️ Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `BROKER_DATA_DIR` | Directory for persistent storage | `broker_data` |
| `BACKEND_TARGETS` | Comma-separated backend instances | `localhost:50051` |
| `BACKEND_CIRCUIT_MAX_FAILURES` | Circuit breaker failure threshold | `5` |
| `BACKEND_CIRCUIT_RESET_SECS` | Circuit breaker reset timeout | `30` |

### Example Configuration

```bash
export BROKER_DATA_DIR=/var/lib/broker
export BACKEND_TARGETS=service1:50051,service2:50051,service3:50051
export BACKEND_CIRCUIT_MAX_FAILURES=3
export BACKEND_CIRCUIT_RESET_SECS=60
```

## 🔧 How It Works

### Durable Queue Mechanism

1. **Message Publishing**
   - Message added to in-memory deque
   - Immediately persisted to `.jsonl` file
   - Atomic write with `fsync()` for durability

2. **Message Consumption**
   - FIFO pop from in-memory queue
   - File rewritten without consumed messages
   - Ensures consistency across restarts

3. **Recovery on Restart**
   - All `.jsonl` files loaded at startup
   - Queues reconstructed in memory
   - Undelivered messages preserved

### Circuit Breaker States

- **CLOSED**: Normal operation, requests flow through
- **OPEN**: Service unhealthy, requests blocked
- **HALF_OPEN**: Testing recovery, limited requests allowed

### Fair Dispatch Load Balancing

The broker implements FIFO (First In, First Out) message distribution to ensure fair dispatch across consumers:
- Messages are queued in order of arrival
- Consumers receive messages in strict FIFO order
- Prevents message starvation
- Ensures predictable message ordering

### Service High Availability

```python
# Round-robin with circuit breaker awareness
ServiceHA → Instance 1 (healthy) → Success ✓
         → Instance 2 (circuit OPEN) → Skip
         → Instance 3 (healthy) → Fallback
```

## Integration Examples

### Service Registration (Python)
```python
import requests

response = requests.post("http://localhost:8001/register", json={
    "service_name": "payment-service",
    "topics": ["payment.processed", "payment.failed"]
})
print(response.json())
```

### Publishing Events (Python with gRPC)
```python
import grpc
import json
import message_pb2
import message_pb2_grpc

# Create channel and stub
channel = grpc.insecure_channel('localhost:50051')
stub = message_pb2_grpc.MessageBrokerServiceStub(channel)

# Prepare message
payload = json.dumps({
    "order_id": "ORD-123",
    "total": 99.99,
    "customer_id": "CUST-456"
})

request = message_pb2.SendMessageRequest(
    topic="order.created",
    payload=payload,
    reply_to="order-service"
)

# Send message
response = stub.SendMessage(request)
if response.success:
    print(f"Message sent! ID: {response.message_id}")
else:
    print(f"Error: {response.error_message}")
```

### Publishing Events (Python with REST)
```python
import requests

response = requests.post("http://localhost:8001/publish", json={
    "topic": "order.created",
    "message": {
        "order_id": "ORD-123",
        "total": 99.99,
        "customer_id": "CUST-456"
    }
})
print(response.json())
```

### Consuming Messages (Python with gRPC)
```python
import grpc
import json
import message_pb2
import message_pb2_grpc

channel = grpc.insecure_channel('localhost:50051')
stub = message_pb2_grpc.MessageBrokerServiceStub(channel)

# Poll for messages
request = message_pb2.ReceiveMessageRequest(topic="order.created")
response = stub.ReceiveMessage(request)

if response.has_message:
    payload = json.loads(response.payload)
    print(f"Received message {response.message_id}")
    print(f"Topic: {response.topic}")
    print(f"Payload: {payload}")
else:
    print("No messages available")
```

### Consuming Messages (Python with REST)
```python
import requests

response = requests.get("http://localhost:8001/consume/order.created?max_messages=5")
data = response.json()

for message in data["messages"]:
    print(f"Message ID: {message['id']}")
    print(f"Payload: {message['payload']}")
```

## 📊 Monitoring

### Health Check Response
```json
{
  "status": "healthy",
  "load_balancing": "fair_dispatch",
  "broker": "custom_durable_file_backed"
}
```

### Logs
The broker logs all significant events:
- Message publications
- Message consumptions
- Circuit breaker state changes
- Service instance failures
- Queue declarations

Example log output:
```
Message published to queue 'order.created' with custom durable broker (fair dispatch via FIFO)
Message consumed from queue 'order.created' (custom broker, FIFO fair dispatch)
Instance service2:50051 circuit OPEN; skipping
```

## Lab Requirements Coverage

| Grade | Requirement | Status |
|-------|-------------|--------|
| 1 | Message Broker in Python | ✅ |
| 1 | Service-to-Service communication | ✅ |
| 2 | Load Balancing in Message Broker | ✅ |
| 2 | Circuit Breakers | ✅ |
| 2 | Thread-per-Request architecture | ✅ |
| 3 | Subscriber-based queues | ✅ |
| 3 | Topic-based queues | ✅ |
| 4 | Service High Availability | ✅ |
| 5 | gRPC for service communication | ✅ |
| 6 | Durable Queues | ✅ |


## Docker Hub

### Build and Push
```bash
# Build the image
docker build -t <your-dockerhub-username>/message-broker:latest .

# Push to Docker Hub
docker login
docker push <your-dockerhub-username>/message-broker:latest
```

### Pull and Run
```bash
# Pull the image
docker pull <your-dockerhub-username>/message-broker:latest

# Run with persistence
docker run -d \
  --name message-broker \
  -p 8001:8001 \
  -p 50051:50051 \
  -v broker-data:/app/broker_data \
  <your-dockerhub-username>/message-broker:latest
```

### Docker Compose Example
```yaml
version: '3.8'
services:
  message-broker:
    image: <your-dockerhub-username>/message-broker:latest
    ports:
      - "8001:8001"
      - "50051:50051"
    volumes:
      - broker-data:/app/broker_data
    environment:
      - BROKER_DATA_DIR=/app/broker_data
      - BACKEND_CIRCUIT_MAX_FAILURES=3
      - BACKEND_CIRCUIT_RESET_SECS=60
    restart: unless-stopped

volumes:
  broker-data:
```

## Security Considerations

- **No authentication implemented**: Add JWT/API keys for production use
- **gRPC uses insecure channels**: Enable TLS for production environments
- **File permissions**: Restrict access to `broker_data/` directory
- **Input validation**: Ensure message payloads are sanitized
- **Rate limiting**: Consider adding rate limits for publish endpoints

## Troubleshooting

### Messages not persisting
- Check that `BROKER_DATA_DIR` is writable
- Verify disk space availability
- Check logs for file I/O errors

### Circuit breaker constantly tripping
- Reduce `BACKEND_CIRCUIT_MAX_FAILURES`
- Increase `BACKEND_CIRCUIT_RESET_SECS`
- Check backend service health

### gRPC connection refused
- Ensure port 50051 is not in use
- Check firewall rules
- Verify `BACKEND_TARGETS` configuration

### High memory usage
- Large queues are held in memory
- Consider implementing message TTL
- Archive old `.jsonl` files periodically

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request


## Acknowledgments

- FastAPI for the excellent web framework
- gRPC for high-performance RPC
- Course instructors for the challenging requirements
- Python community for excellent libraries

---
