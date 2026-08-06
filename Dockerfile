# Playwright va Python tayyor o'rnatilgan rasmiy obraz
FROM mcr.microsoft.com/playwright/python:v1.42.0-jammy

# Ishchi papkani belgilash
WORKDIR /app

# Kutubxonalarni ko'chirish va o'rnatish
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Loyihaning qolgan fayllarini ko'chirish
COPY . .

# Botni ishga tushirish buyrug'i
CMD ["python", "main.py"]
