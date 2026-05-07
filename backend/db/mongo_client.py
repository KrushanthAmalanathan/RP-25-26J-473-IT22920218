import os
import logging
from typing import Optional, Dict, Any
from datetime import datetime

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase, AsyncIOMotorCollection

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

logger = logging.getLogger(__name__)


class MongoDBClient:
    def __init__(self):
        self.mongo_uri: Optional[str] = os.getenv("MONGO_URI")
        self.db_name: Optional[str] = os.getenv("DB_NAME")
        self.collection_name: Optional[str] = os.getenv("COLLECTION_NAME", "detections")

        self.client: Optional[AsyncIOMotorClient] = None
        self.db: Optional[AsyncIOMotorDatabase] = None
        self.collection: Optional[AsyncIOMotorCollection] = None
        self.connected: bool = False

        print("[MONGO DEBUG] __init__ called")
        print(f"[MONGO DEBUG] MONGO_URI set: {bool(self.mongo_uri)}")
        print(f"[MONGO DEBUG] DB_NAME: {self.db_name}")
        print(f"[MONGO DEBUG] COLLECTION_NAME: {self.collection_name}")

    def is_configured(self) -> bool:
        return bool(self.mongo_uri and self.db_name and self.collection_name)

    async def connect(self) -> bool:
        print(f"[MONGO DEBUG] connect() called, already_connected={self.connected}")

        if self.connected:
            return True

        if not self.is_configured():
            print("[MONGO DEBUG] MongoDB not configured correctly")
            return False

        try:
            self.client = AsyncIOMotorClient(self.mongo_uri)
            self.db = self.client[self.db_name]
            self.collection = self.db[self.collection_name]

            await self.client.admin.command("ping")
            self.connected = True

            print(f"[MONGO DEBUG] Connection SUCCESS - will insert to: {self.db_name}.{self.collection_name}")
            logger.info(f"MongoDB connected: {self.db_name}.{self.collection_name}")
            return True
        except Exception as e:
            print(f"[MONGO DEBUG] Connection FAILED: {type(e).__name__}: {e}")
            logger.error(f"Failed to connect to MongoDB: {e}", exc_info=True)
            self.connected = False
            self.client = None
            self.db = None
            self.collection = None
            return False

    async def disconnect(self) -> None:
        if self.client is not None:
            try:
                self.client.close()
            finally:
                self.connected = False
                self.client = None
                self.db = None
                self.collection = None
                logger.info("MongoDB disconnected")

    async def insert_detection(self, record: Dict[str, Any]) -> bool:
        print(f"[MONGO DEBUG] insert_detection called connected={self.connected}")

        if not self.connected:
            print("[MONGO DEBUG] insert skipped - not connected")
            return False

        if self.collection is None:
            print("[MONGO DEBUG] insert skipped - collection is None")
            return False

        try:
            if "timestamp" not in record:
                record["timestamp"] = datetime.utcnow().isoformat() + "Z"

            print(f"[MONGO DEBUG] inserting record: {record}")
            result = await self.collection.insert_one(record)
            print(f"[MONGO DEBUG] insert success id={result.inserted_id}")
            return True
        except Exception as e:
            print(f"[MONGO DEBUG] insert failed: {type(e).__name__}: {e}")
            logger.error(f"Failed to insert detection record: {e}", exc_info=True)
            return False


mongo_client = MongoDBClient()