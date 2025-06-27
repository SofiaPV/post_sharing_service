import psycopg2
from psycopg2 import pool
from typing import TypeVar, Generic, Optional
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from contextlib import contextmanager

import firebase_admin
from firebase_admin import credentials, storage

import json
import traceback


T = TypeVar("T")  # some abstract data type


@dataclass
class Post:
    url: str
    expires_at: datetime
    data: Optional[str] = None


class DataBase(ABC, Generic[T]):
    @abstractmethod
    def get(self, url: str) -> Optional[T]:
        raise NotImplementedError

    @abstractmethod
    def add(self, **kwargs: object) -> bool:
        raise NotImplementedError

    @abstractmethod
    def delete(self, url: str) -> bool:
        raise NotImplementedError

    #@abstractmethod
    #def delete_expired(self) -> None:
    #    raise NotImplementedError


class UrlDB(DataBase[Post]):  # class for Post objects
    def __init__(self):
        try:
            self.pool = psycopg2.pool.ThreadedConnectionPool(1, 20,
                                                             host='127.0.0.1', dbname='Post_sharing_service',
                                                             user='postgres', password='12345', port=5432
                                                             )
            self._create_table()
        except Exception as e:
            print(f"UrlDB: Creation error: {e}")
            traceback.print_exc()
            self.pool = None

    @contextmanager
    def get_cursor(self):
        conn = self.pool.getconn()
        cursor = conn.cursor()
        try:
            # TODO: figure out if connection liveliness should be checked
            yield cursor
            conn.commit()
        finally:
            cursor.close()
            self.pool.putconn(conn)

    def _create_table(self):
        with self.get_cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS posts (
                    url VARCHAR(255) PRIMARY KEY,
                    expires_at TIMESTAMPTZ  
                );
            """)

    def get(self, url: str) -> Optional[Post]:
        with self.get_cursor() as cur:
            cur.execute(""" 
                SELECT * FROM posts WHERE url = %s
            """, (url,))
            post = cur.fetchone()
            if post is None:
                return None

            return Post(url=post[0], expires_at=post[1])

    def add(self, **kwargs: object) -> bool:  # TODO: perhaps **kwargs is not an option
        with self.get_cursor() as cur:
            if 'url' not in kwargs or 'expires_at' not in kwargs:
                return False

            try:
                cur.execute("""
                    INSERT INTO posts (url, expires_at) VALUES 
                    (%s, %s)
                """, (kwargs['url'], kwargs['expires_at']))
            except Exception as e:
                print(f"UrlDB: InsertError: {e}")
                return False
            return True

    def delete(self, url: str) -> bool:
        with self.get_cursor() as cur:
            cur.execute("""
                DELETE FROM posts WHERE url = %s
            """, (url,))
            return True
        # TODO: return False if not deleted

    def delete_expired(self) -> None:
        with self.get_cursor() as cur:
            cur.execute("""
                DELETE FROM posts WHERE expires_at <= %s
            """, (datetime.now(timezone.utc)))  # TODO: how to calculate dates correctly?


class CloudManager(DataBase[dict]):
    """
    Works with cloud storage.
    Adds posts in json format, returns link to them.
    Returns posts by link.
    Deletes posts on request.
    """
    def __init__(self):
        if not firebase_admin._apps:
            cred = credentials.Certificate("key.json")
            firebase_admin.initialize_app(cred, {
                'storageBucket': 'post-sharing-service.appspot.com'
            })

    def get(self, url: str) -> Optional[dict]:
        bucket = storage.bucket()
        blob = bucket.blob(f'posts/{url}')  # /posts -- all posts, /images -- data for posts, even temporary

        data = None
        if not blob.exists():
            return data

        try:
            data = json.loads(blob.download_as_text())
        except Exception as e:
            print(f"CloudManager: FileGettingError {url}")
        return data

    def add(self, **kwargs: object) -> bool:
        if 'url' not in kwargs or 'data' not in kwargs:
            return False
        bucket = storage.bucket()
        blob = bucket.blob(f"posts/{kwargs['url']}")

        if blob.exists():
            print(f"CloudManager: add: FileAlreadyExists")
            return False

        try:
            blob.upload_from_string(json.dumps(kwargs['data']))
        except Exception as e:
            print(f"CloudManager: FileAddingError: {e}")
            return False
        return True

    def delete(self, url: str) -> bool:
        bucket = storage.bucket()
        blob = bucket.blob(f"posts/{url}")

        try:
            blob.delete()
        except Exception as e:
            print(f"CloudManager: DeleteError: {e}")
            return False
        return True


class DataManager(DataBase[dict]):
    """
    Main data class, manages incoming data.
    Gets add, get, delete requests, uses local
    database and cloud storage.
    """

    def __init__(self):
        self._db = UrlDB()
        self._cloud_storage = CloudManager()

    def get(self, url: str) -> Optional[dict]:
        post_info = self._db.get(url)
        if post_info is None:
            return None
        data = self._cloud_storage.get(url)
        return data

    def delete(self, url: str) -> bool:
        if self._cloud_storage.delete(url):
            if self._db.delete(url):
                return True
        return False

    def add(self, **kwargs: object) -> bool:
        if self._db.add(**kwargs):
            if self._cloud_storage.add(**kwargs):
                return True
            if 'url' in kwargs:
                self._db.delete(kwargs['url'])
        return False
