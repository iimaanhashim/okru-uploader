FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app
COPY . /app

RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium

# Koyeb wuxuu u baahan yahay inuu arko Port furan
EXPOSE 8080

CMD ["python", "main.py"]
