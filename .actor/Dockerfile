# Dockerfile for Apify Actor — Python 3.11 + Playwright/Chromium
FROM apify/actor-python-playwright:3.11

# Copy source code
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./

# Run the Actor
CMD ["python3", "-m", "src.main"]
