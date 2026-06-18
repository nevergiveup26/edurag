"""
初始化管理员账号
用法: python scripts\init_admin.py
"""
import sys, os, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.auth import hash_password
from database.mysql_db import MySQLDB

db = MySQLDB()
db.init_tables()

username = "admin"
password = "admin123"

existing = db.get_user_by_username(username)
if existing:
    print(f"管理员 {username} 已存在，跳过创建")
else:
    user_id = f"adm_{uuid.uuid4().hex[:12]}"
    db.create_user(user_id, username, hash_password(password), role="admin", display_name="系统管理员")
    print(f"管理员账号已创建: 用户名={username}, 密码={password}")

stu_username = "2024001"
stu_password = "123456"
existing_stu = db.get_user_by_username(stu_username)
if existing_stu:
    print(f"学生 {stu_username} 已存在，跳过创建")
else:
    stu_id = f"stu_{uuid.uuid4().hex[:12]}"
    db.create_user(stu_id, stu_username, hash_password(stu_password), role="student", display_name="测试学生")
    print(f"学生账号已创建: 学号={stu_username}, 密码={stu_password}")

print("初始化完成！")