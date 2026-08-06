# 1. Playwright va Python 3.10+ tayyor o'rnatilgan rasmiy Ubuntu (Jammy) obrazi
FROM mcr.microsoft.com/playwright/python:v1.42.0-jammy

# 2. Python print() loglarini kutib o'tirmasdan real-vaqt rejimida konsolga chiqarish
ENV PYTHONUNBUFFERED=1

# 3. Konteyner ichidagi ishchi katalog
WORKDIR /app

# 4. Avval kutubxonalar ro'yxatini ko'chirib, ularni o'rnatamiz (Cache samadorligi uchun)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Loyihaning barcha qolgan fayllarini (main.py va h.k.) ko'chirish
COPY . .

# 6. Botni real-time loglar bilan ishga tushirish buyrug'i
CMD ["python", "-u", "main.py"]
