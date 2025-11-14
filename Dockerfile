FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the FastAPI app
COPY MessageBroker.py .

EXPOSE 8001

CMD ["uvicorn", "MessageBroker:app", "--host", "0.0.0.0", "--port", "8001"]
