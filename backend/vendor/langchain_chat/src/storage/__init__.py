"""存储层。

本包提供可插拔的存储后端：
    - base.py            抽象基类（接口定义）
    - factory.py         工厂模式（Step 3 实现）
    - sqlite_backend.py  SQLite 实现（Step 3 实现）
    - mysql_backend.py   MySQL 实现（Step 11 实现）
    - file_backend.py    文件实现（Step 12 实现）
"""