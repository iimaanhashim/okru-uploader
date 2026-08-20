# 1. Isticmaal image horay loogu soo diyaariyay wax kasta
FROM mcr.microsoft.com/playwright/python:v1.45.0-jammy

# 2. Deji meesha shaqada
WORKDIR /app

# 3. Koobbi garee requirements.txt oo kaliya marka hore
COPY requirements.txt .

# 4. Ku rakib packages-ka Python
RUN pip install --no-cache-dir -r requirements.txt

# 5. Koobbi garee dhamaan files-ka kale ee app-kaaga
COPY . .

# 6. Maadaama image-kani horay u lahaa Chromium, uma baahnid inaad mar kale install dhahdo. 
# Kaliya waxaan hubineynaa inuu diyaar yahay.
RUN playwright install chromium

# 7. Amarada lagu bilaabayo app-ka
CMD ["python", "main.py"]
