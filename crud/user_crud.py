from pymongo.database import Database
from typing import Optional, List
from bson import ObjectId
from datetime import datetime

from schemas import UserCreate, UserInDB
from auth import get_password_hash

def get_user(db: Database, user_id: str) -> Optional[UserInDB]:
    """
    IDを使用して、データベースからユーザーを検索する。
    """
    try:
        user_data = db.users.find_one({"_id": ObjectId(user_id)})
        if user_data:
            user_data["_id"] = str(user_data["_id"])
            return UserInDB(**user_data)
        return None
    except Exception:
        return None

def get_user_by_email(db: Database, email: str) -> Optional[UserInDB]:
    """
    メールアドレスを使用して、データベースからユーザーを検索する。
    """
    user_data = db.users.find_one({"email": email})
    if user_data:
        user_data["_id"] = str(user_data["_id"])
        return UserInDB(**user_data)
    return None

def get_photographers(db: Database) -> List[UserInDB]:
    """
    役割が'photographer'のすべてのユーザーを取得する。
    """
    users = []
    for user_data in db.users.find({"role": "photographer"}):
        user_data["_id"] = str(user_data["_id"])
        users.append(UserInDB(**user_data))
    return users

def create_user(db: Database, user: UserCreate) -> UserInDB:
    """
    新しいユーザーを作成し、データベースに保存する。
    """
    hashed_password = get_password_hash(user.password)
    user_dict = user.model_dump()
    user_dict.pop("password")
    user_dict["hashed_password"] = hashed_password
    user_dict["is_active"] = True
    user_dict["created_at"] = datetime.utcnow()

    result = db.users.insert_one(user_dict)
    created_user = get_user(db, user_id=str(result.inserted_id))
    return created_user


def delete_user_by_id(db: Database, user_id: str) -> bool:
    """
    指定されたIDのユーザーを削除する。
    """
    try:
        result = db.users.delete_one({"_id": ObjectId(user_id)})
        return result.deleted_count > 0
    except Exception:
        return False
