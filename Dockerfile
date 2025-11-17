FROM python:3.11-slim

RUN apt-get update && apt-get install -y curl

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY MessageBroker.py /app/MessageBroker.py
COPY message.proto .


RUN python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. message.proto

EXPOSE 8001 50051
CMD ["python", "MessageBroker.py"]