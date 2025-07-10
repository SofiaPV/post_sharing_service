import psycopg2
from psycopg2 import pool
from typing import TypeVar, Generic, Optional, Generator
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from contextlib import contextmanager

import json
import traceback
import requests

from dotenv import load_dotenv
import os

load_dotenv()
T = TypeVar("T")  # some abstract data type


@dataclass
class Post:
    url: str
    expires_at: datetime
    status: str  # pending/saved/error
    data: Optional[str] = None

    def to_dict(self):
        return {
            "url": self.url,
            "expires_at": self.expires_at.isoformat(),
            "status": self.status,
            "data": self.data
        }


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
            print("Connecting to DB with:")
            print(f"host={os.getenv('POSTGRES_HOST')}, dbname={os.getenv('POSTGRES_DB')}, user={os.getenv('POSTGRES_USER')}, port={os.getenv('POSTGRES_PORT')}")

            self.pool = psycopg2.pool.ThreadedConnectionPool(1, 20,
                                                             host=os.getenv("POSTGRES_HOST"),
                                                             dbname=os.getenv("POSTGRES_DB"),
                                                             user=os.getenv("POSTGRES_USER"),
                                                             password=os.getenv("POSTGRES_PASSWORD"),
                                                             port=int(os.getenv("POSTGRES_PORT", "5432"))
                                                             )
            self._create_table()
        except Exception as e:
            print(f"UrlDB: Creation error: {e}")
            traceback.print_exc()
            self.pool = None
            raise RuntimeError("UrlDB: Failed to create DB connection pool")

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
                    expires_at TIMESTAMPTZ,
                    status VARCHAR(255)  
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

            return Post(url=post[0], expires_at=post[1], status=post[2])

    def add(self, url: str, expires_at: datetime) -> bool:
        with self.get_cursor() as cur:
            try:
                cur.execute("""
                    INSERT INTO posts (url, expires_at, status) VALUES 
                    (%s, %s, %s)
                """, (url, expires_at, "pending"))
            except Exception as e:
                print(f"UrlDB: InsertError: {e}")
                return False
            return True

    def change_status(self, url: str, status: str) -> bool:
        with self.get_cursor() as cur:
            try:
                cur.execute("""
                UPDATE posts SET status = %s WHERE url = %s
                """, (status, url))
            except Exception as e:
                print(f"UrlDB: change_status: {e}")
                return False
            return True

    def delete(self, url: str) -> bool:
        with self.get_cursor() as cur:
            cur.execute("""
                DELETE FROM posts WHERE url = %s
            """, (url,))
            return cur.rowcount == 1

    def get_expired(self) -> Generator[str, None, None]:  # YieldType, SendType, ReturnType
        """
        :return: list of expired url's
        """
        with self.get_cursor() as cur:
            cur.execute("""
                SELECT url FROM posts WHERE expires_at <= %s
            """, (datetime.now(timezone.utc),))
            for row in cur:
                yield row[0]


class CloudManager(DataBase[dict]):
    """
    Works with cloud storage (Yandex Disk).
    Adds posts in json format.
    Returns posts by link.
    Deletes posts on request.
    """
    def __init__(self):
        self._headers = {
            "Authorization": f"OAuth {os.getenv('YANDEX_DISK_TOKEN')}",
        }

        for i in range(5):
            if self._create_folder("/posts"):
                break
        else:
            raise RuntimeError("CloudManager: could not create /posts")

    def get(self, url: str) -> Optional[dict]:

        # Step 1: get URL to download file
        try:
            r = requests.get("https://cloud-api.yandex.net/v1/disk/resources/download",
                             headers=self._headers,
                             params={"path": f"/post_sharing_service/posts/{url}/{url}"},
                             timeout=5)
            r.raise_for_status()
            download_url = r.json().get("href")
            if not download_url:
                print(f"CloudManager: get: No href")
                return None
        except Exception as e:
            print(f"CloudManager: get {url}: {e}")
            return None

        # Step 2: download
        try:
            r = requests.get(download_url, timeout=5)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print(f"CloudManager: get {url}: {e}")
            return None

    def _create_folder(self, name: str) -> bool:
        try:
            r = requests.put("https://cloud-api.yandex.net/v1/disk/resources",
                             headers=self._headers,
                             params={"path": f"/post_sharing_service{name}"},
                             timeout=5)
            if r.status_code not in (201, 409):
                print(f"CloudManager: _create_folder: {r.status_code}")
                return False
            return True
        except Exception as e:
            print(f"CloudManager: _create_folder: {e}")
            return False

    def add(self, url: str, data: dict) -> bool:

        # 0: Create folder if not exists
        if not self._create_folder(f"/posts/{url}"):
            print(f"CloudManager: add: folder creation failed")
            return False

        # 1: Get url to upload
        try:
            r = requests.get("https://cloud-api.yandex.net/v1/disk/resources/upload",
                             headers=self._headers,
                             params={"path": f"/post_sharing_service/posts/{url}/{url}",
                                     "overwrite": "true",
                                     },
                             timeout=5)
            r.raise_for_status()  # if status code not ok (2xx), then raise an error
            upload_url = r.json().get("href")
            if not upload_url:
                print(f"CloudManager: add: No url to upload")
                return False
        except Exception as e:
            print(f"CloudManager: add: {e}")
            return False

        # 2: upload using URL
        try:
            r = requests.put(upload_url,
                         headers={"Content-Type": "application/json"},
                         data=json.dumps(data))
            r.raise_for_status()
        except Exception as e:
            print(f"CloudManager: add (URL stage): {e}")
            return False
        return True

    def delete(self, url: str) -> bool:
        """
        Deletes all resources assosiated with the post
        :param url: posts' url
        :return: True if success, False otherwise
        """
        # step 0: figure out if folder exists
        try:
            r = requests.get("https://cloud-api.yandex.net/v1/disk/resources",
                             headers=self._headers,
                             params={"path": f"/post_sharing_service/posts/{url}"},
                             timeout=5)
        except Exception as e:
            print(f"CloudManager: delete: {e}")
            return False
        if r.status_code == 404:
            raise FileNotFoundError("CloudManager: delete: File not found")

        # step 1: delete folder
        try:
            r = requests.delete("https://cloud-api.yandex.net/v1/disk/resources",
                                headers=self._headers,
                                params={"path": f"/post_sharing_service/posts/{url}",
                                        "permanently": "true",
                                        },
                                timeout=5)
            if r.status_code not in (204, 200, 202):  # 204 according to documentation
                print(f"CloudManager: delete: {r.status_code}")
                return False
            return True
        except Exception as e:
            print(f"CloudManager: delete {url}: {e}")
            return False


class DataManager(DataBase[Post]):
    """
    Main data class, manages incoming data.
    Gets add, get, delete requests, uses local
    database and cloud storage.
    """

    def __init__(self):
        self._db = UrlDB()
        self._cloud_storage = CloudManager()

    def get(self, url: str) -> Optional[Post]:
        post_info = self._db.get(url)
        if post_info is None or post_info.expires_at <= datetime.now(timezone.utc):
            return None
        data = self._cloud_storage.get(url)
        post_info.data = data
        return post_info

    def delete(self, url: str) -> bool:
        try:
            response = self._cloud_storage.delete(url)
        except FileNotFoundError:
            if self._db.delete(url):
                return True
            return False
        except Exception as e:
            print(f"DataManager: delete: {e}")
            return False

        if response:
            if self._db.delete(url):
                return True
        return False

    def add(self, url: str, expires_at: datetime, data: dict) -> bool:
        if self._db.add(url, expires_at):  # saved to DB
            if self._cloud_storage.add(url, data):  # saved to cloud
                if self._db.change_status(url, "saved"):  # status changed correctly
                    return True
            self._db.delete(url)
        return False

    def delete_expired(self) -> bool:
        """
        Deletes expired posts.
        :return: True if all is deleted, False if some post info is still present
        (a post deletes both from DB and cloud, or it's not deleted at all)
        """
        result = True
        for url in self._db.get_expired():
            result = self.delete(url) and result  # if >=1 post is not deleted -- False
        return result
