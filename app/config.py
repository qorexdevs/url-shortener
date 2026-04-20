import os

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./shortener.db")
SHORT_CODE_LENGTH = 6
