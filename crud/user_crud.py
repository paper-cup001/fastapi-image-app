from pymongo.database import Database
from typing import Optional

from schemas import UserInDB

def get_user_by_email(db: Database, email: str) -> Optional[UserInDB]:
    """
    メールアドレスを使用して、データベースからユーザーを検索する。

    Args:
        db: Pymongoのデータベースオブジェクト。
        email: 検索するユーザーのメールアドレス。

    Returns:
        ユーザーが見つかった場合はUserInDBモデルのインスタンス、見つからない場合はNone。
    """
    user_data = db.users.find_one({"email": email})
    if user_data:
        # MongoDBの_idをidに変換してモデルを作成
        user_data["_id"] = str(user_data["_id"])
        return UserInDB(**user_data)
    return None
