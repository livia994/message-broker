FROM python:3.11-slim

RUN apt-get update && apt-get install -y curl

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY MessageBroker.py /app/MessageBroker.py

EXPOSE 8001

CMD ["uvicorn", "MessageBroker:app", "--host", "0.0.0.0", "--port", "8001"]
