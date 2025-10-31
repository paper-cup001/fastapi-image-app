
import sys
import os
from pymongo import MongoClient
from auth import get_password_hash
from datetime import datetime

def create_system_admin(email, password):
    """
    システム管理者アカウントをデータベースに作成する関数
    """
    # --- データベース接続 ---
    MONGO_URL = os.environ.get("MONGO_URL")
    if not MONGO_URL:
        print("エラー: 環境変数 MONGO_URL が設定されていません。")
        print("例: export MONGO_URL='mongodb://localhost:27017/'")
        sys.exit(1)

    try:
        client = MongoClient(MONGO_URL)
        db = client["image_db"]
        users_collection = db["users"]
    except Exception as e:
        print(f"データベース接続エラー: {e}")
        sys.exit(1)

    # --- ユーザーの存在チェック ---
    if users_collection.find_one({"email": email}):
        print(f"エラー: メールアドレス '{email}' は既に使用されています。")
        client.close()
        sys.exit(1)

    # --- パスワードのハッシュ化 ---
    hashed_password = get_password_hash(password)

    # --- ユーザー情報の作成 ---
    new_system_admin = {
        "email": email,
        "hashed_password": hashed_password,
        "role": "system_admin", # 役割をsystem_adminに設定
        "is_active": True, # デフォルトで有効
        "created_at": datetime.utcnow()
    }

    # --- データベースへの挿入 ---
    try:
        users_collection.insert_one(new_system_admin)
        print(f"システム管理者アカウント '{email}' を作成しました。")
    except Exception as e:
        print(f"データベース挿入エラー: {e}")
    finally:
        client.close()

if __name__ == "__main__":
    # コマンドライン引数からemailとpasswordを取得
    if len(sys.argv) != 3:
        print("使用法: python create_system_admin.py <email> <password>")
        sys.exit(1)

    email_arg = sys.argv[1]
    password_arg = sys.argv[2]

    create_system_admin(email_arg, password_arg)
