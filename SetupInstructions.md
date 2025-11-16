# gRPC Setup Instructions

## Overview
This setup enables gRPC communication between `task-service` and `voting-service` through the message broker using RabbitMQ as the transport layer.

## Architecture Flow
1. Client sends REST request to `task-service` with `characterId` and `gold`
2. `task-service` sends gRPC message to message broker
3. Message broker publishes to RabbitMQ queue `voting-service-character-data`
4. `voting-service` polls the queue via gRPC and processes the message
5. `voting-service` sends response back through message broker to reply queue
6. `task-service` receives response and returns JSON to client

## Setup Steps

### 1. Message Broker Setup

#### File Structure
```
message-broker/
├── MessageBroker.py
├── message.proto
├── requirements.txt
└── Dockerfile (update needed)
```

#### Generate Python gRPC files
```bash
pip install -r requirements.txt
python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. message.proto
```

This generates:
- `message_pb2.py`
- `message_pb2_grpc.py`

#### Update Dockerfile
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Generate gRPC files
RUN python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. message.proto

EXPOSE 8001 50051

CMD ["python", "MessageBroker.py"]
```

### 2. Java Services Setup

#### Directory Structure (for both services)
```
src/
├── main/
│   ├── java/
│   │   └── com/
│   │       ├── taskservice/ or votingservice/
│   │       │   ├── controller/
│   │       │   ├── config/
│   │       │   └── listener/ (voting-service only)
│   └── proto/
│       └── message.proto
```

#### Steps for Task Service:

1. **Copy proto file**
   ```bash
   mkdir -p src/main/proto
   cp message.proto src/main/proto/
   ```

2. **Update pom.xml**
   - Add the dependencies from the provided pom.xml artifact

3. **Generate Java classes**
   ```bash
   mvn clean compile
   ```
   This generates classes in `target/generated-sources/protobuf/`

4. **Add TaskController.java**
   - Place in `src/main/java/com/taskservice/controller/`

5. **Update application.properties**
   - Add message broker configuration

#### Steps for Voting Service:

1. **Copy proto file**
   ```bash
   mkdir -p src/main/proto
   cp message.proto src/main/proto/
   ```

2. **Update pom.xml**
   - Add the same dependencies as task-service

3. **Generate Java classes**
   ```bash
   mvn clean compile
   ```

4. **Add VotingServiceMessageListener.java**
   - Place in `src/main/java/com/votingservice/listener/`

5. **Add SchedulingConfig.java**
   - Place in `src/main/java/com/votingservice/config/`

6. **Update application.properties**
   - Add message broker and scheduling configuration

### 3. Docker Compose Updates

Update the `docker-compose.yml`:

```yaml
message_broker:
  image: livia994/message-broker:latest
  container_name: message_broker_container
  platform: linux/amd64
  depends_on:
    - rabbitmq
  ports:
    - "8001:8001"
    - "50051:50051"  # Add gRPC port
  environment:
    - PYTHONUNBUFFERED=1
    - RABBITMQ_HOST=rabbitmq
  networks:
    - backend
```

### 4. Building and Deployment

#### Message Broker
```bash
cd message-broker
docker build -t livia994/message-broker:latest .
docker push livia994/message-broker:latest
```

#### Task Service
```bash
cd task-service
mvn clean package
docker build -t vladamusin/task_service:latest .
docker push vladamusin/task_service:latest
```

#### Voting Service
```bash
cd voting-service
mvn clean package
docker build -t vladamusin/voting_service:latest .
docker push vladamusin/voting_service:latest
```

### 5. Testing

#### Start services
```bash
docker-compose up -d
```

#### Test the endpoint
```bash
curl -X POST http://localhost:8180/api/tasks/send-character-data \
  -H "Content-Type: application/json" \
  -d '{
    "characterId": 1,
    "gold": 50
  }'
```

#### Expected Response
```json
{
  "success": true,
  "characterId": 1,
  "gold": 50,
  "message": "Data successfully sent to voting-service and received response",
  "messageId": "uuid-here"
}
```

#### Check Logs
```bash
# Task service logs
docker logs task-service

# Voting service logs  
docker logs voting-service

# Message broker logs
docker logs message_broker_container
```

You should see:
- Task Service: "Sending message to voting-service via gRPC"
- Message Broker: Message publishing/consumption
- Voting Service: "Received message", "Processing character data", "Sending response back"
- Task Service: "Received response from voting-service"

## Troubleshooting

### gRPC Connection Issues
- Verify message broker is exposing port 50051
- Check network connectivity: `docker exec task-service ping message_broker`
- Verify gRPC server started: `docker logs message_broker_container | grep "gRPC server started"`

### No Response from Voting Service
- Check if voting service is polling: `docker logs voting-service`
- Verify RabbitMQ queues exist: http://localhost:15672 (guest/guest)
- Increase wait time in TaskController if needed

### Proto Compilation Errors
- Ensure protobuf-maven-plugin is properly configured
- Check proto file syntax
- Verify Maven can download protoc compiler

### Import Errors in Java
- Run `mvn clean compile` to regenerate proto classes
- Check that generated classes are in `target/generated-sources/`
- Ensure IDE recognizes generated-sources as source folder

## Notes

- The voting service polls every 2 seconds for new messages
- Task service waits 1 second for response (adjust as needed)
- Reply queues are unique per request using UUID
- All communication goes through RabbitMQ queues
- gRPC is used only between services and message broker, not end-to-end