"""
MongoDB (Motor) and Supabase client initialization.
Clients are created lazily on first access and reused across the application.
"""

import os
from motor.motor_asyncio import AsyncIOMotorClient
from supabase import create_client, Client as SupabaseClient
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# MongoDB
# ---------------------------------------------------------------------------
_mongo_client: AsyncIOMotorClient | None = None


def get_mongo_client() -> AsyncIOMotorClient:
    global _mongo_client
    if _mongo_client is None:
        uri = os.getenv("MONGODB_URI")
        if not uri:
            raise EnvironmentError("MONGODB_URI not set in .env")
        _mongo_client = AsyncIOMotorClient(uri)
    return _mongo_client


def get_database():
    """Return the default database handle."""
    client = get_mongo_client()
    return client.chatpdf_rag


# Convenience accessors for collections
def users_col():
    return get_database().users


def pdfs_col():
    return get_database().pdfs


def chats_col():
    return get_database().chats


# ---------------------------------------------------------------------------
# Supabase
# ---------------------------------------------------------------------------
_supabase_client: SupabaseClient | None = None


def get_supabase() -> SupabaseClient:
    global _supabase_client
    if _supabase_client is None:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        if not url or not key:
            raise EnvironmentError("SUPABASE_URL and SUPABASE_KEY must be set in .env")
        _supabase_client = create_client(url, key)
    return _supabase_client


def get_supabase_bucket() -> str:
    return os.getenv("SUPABASE_BUCKET", "pdfs")
