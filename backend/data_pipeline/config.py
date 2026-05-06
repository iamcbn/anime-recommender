# each service's own config.py
import os
from dotenv import load_dotenv

load_dotenv()

def config() -> dict:
    return {
        "host": os.getenv("DB_HOST"),
        "port": os.getenv("DB_PORT"),
        "database": os.getenv("DB_NAME"),
        "user": os.getenv("DB_USER"),
        "password": os.getenv("DB_PASSWORD"),
    }

if __name__ == "__main__":
    config()