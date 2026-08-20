FROM python:3.10-slim

# Deji meesha shaqada
WORKDIR /app

# 1. Cusboonaysii nidaamka oo ku rakib agabka aasaasiga ah
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# 2. Koobbi garee requirements.txt
COPY requirements.txt .

# 3. Ku rakib packages-ka Python
RUN pip install --no-cache-dir -r requirements.txt

# 4. Ku rakib Playwright Chromium kaliya
RUN playwright install chromium

# 5. Ku rakib dependencies-ka muhiimka ah (tani waxay xallineysaa khaladaadka fonts-ka)
RUN apt-get update && playwright install-deps chromium && rm -rf /var/lib/apt/lists/*

# 6. Koobbi garee files-ka kale ee app-kaaga
COPY . .

# Amarada lagu bilaabayo app-ka
CMD ["python", "main.py"]
