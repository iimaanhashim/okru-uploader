# Isticmaal image ka yar (slim) halkii aad ka isticmaali lahayd kan weyn ee Microsoft
FROM python:3.10-slim

# Deji meesha shaqada
WORKDIR /app

# Ku dar files-ka requirements-ka kaliya marka hore si layer-ka loo cache gareeyo
COPY requirements.txt .

# Ku rakib packages-ka Python adigoon cache kaydsaneyn
RUN pip install --no-cache-dir -r requirements.txt

# Ku rakib Playwright iyo inta u baahan yahay ee chromium ah
# Markaad isticmaasho 'install-deps' waxay soo dejineysaa kaliya wixii chromium u baahnaa
RUN playwright install --with-deps chromium

# Hadda koobbi garee files-ka kale ee app-kaaga
COPY . .

# Amarada lagu bilaabayo app-ka
CMD ["python", "main.py"]
