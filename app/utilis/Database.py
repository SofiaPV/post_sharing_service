import psycopg2
from psycopg2 import pool
from typing import TypeVar, Generic, Optional
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from contextlib import contextmanager


T = TypeVar("T")  # some abstract data type


@dataclass
class Post:
    url: str
    content_link: str
    expires_at: datetime


class DataBase(ABC, Generic[T]):
    @abstractmethod
    def get(self, url: str) -> Optional[T]:
        raise NotImplementedError

    @abstractmethod
    def add(self, **kwargs: object) -> None:
        raise NotImplementedError

    @abstractmethod
    def delete(self, url: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def delete_expired(self) -> None:
        raise NotImplementedError


class UrlDB(DataBase[Post]):  # class for Post objects
    def __init__(self):
        self.pool = psycopg2.pool.ThreadedConnectionPool(1, 20,
                                                         host='localhost', dbname='post_sharing_service',
                                                         user='postgres', password='12345', port=5432
                                                         )
        self._create_table()

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
                    content_link VARCHAR(255),
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

            return Post(url=post[0], content_link=post[1], expires_at=post[2])

    def add(self, **kwargs: object) -> None:  # TODO: perhaps **kwargs is not an option
        with self.get_cursor() as cur:
            cur.execute("""
                INSERT INTO posts (url, content_link, expires_at) VALUES 
                (%s, %s, %s)
            """, (kwargs['url'], kwargs['content_link'], kwargs['expires_at']))

    def delete(self, url: str) -> None:
        with self.get_cursor() as cur:
            cur.execute("""
                DELETE FROM posts WHERE url = %s
            """, (url,))

    def delete_expired(self) -> None:
        with self.get_cursor() as cur:
            cur.execute("""
                DELETE FROM posts WHERE expires_at <= %s
            """, (datetime.now(timezone.utc)))  # TODO: how to calculate dates correctly?


