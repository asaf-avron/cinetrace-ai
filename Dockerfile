FROM python:3.13-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir .

ENV PORT=8080
ENV PYTHONUNBUFFERED=1
ENV GOOGLE_GENAI_USE_VERTEXAI=TRUE
ENV GOOGLE_CLOUD_PROJECT=cinetrace-ai
ENV GOOGLE_CLOUD_LOCATION=us-central1

EXPOSE 8080
CMD ["sh", "-c", "uvicorn cinetrace.web.app:app --host 0.0.0.0 --port ${PORT}"]
