FROM python:3.11-slim

# Install system dependencies including ADB
RUN apt-get update && apt-get install -y --no-install-recommends \
    android-tools-adb \
    android-tools-fastboot \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Verify ADB installation
RUN which adb && adb version || echo "Warning: ADB installation may have issues"

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
