from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL não configurada.")

engine = create_engine(DATABASE_URL)

try:
    with engine.connect() as connection:
        print("Connection successful!")
except Exception as e:
    print(f"Failed to connect: {e}")


def get_db():
    return engine


def execute_select_query(query, parameters=None):
    try:
        with engine.connect() as conn:
            result = conn.execute(text(query), parameters or {})
            return result.mappings().all()
    except Exception as e:
        print(f"Error: {e}")
        return []


def execute_modify_query(query, parameters=None):
    try:
        with engine.begin() as conn:
            result = conn.execute(text(query), parameters or {})
        return result.rowcount
    except Exception as e:
        print(f"Error: {e}")
        return []


def execute_insert_returning_id(query, parameters=None):
    try:
        with engine.begin() as conn:
            result = conn.execute(text(query), parameters or {})
            return result.scalar_one()
    except Exception as e:
        print(f"Error: {e}")
        return None
