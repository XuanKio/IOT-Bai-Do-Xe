import getpass
from sqlalchemy import select
from app.main import Base, User, Sessions, engine, hasher


def main():
    Base.metadata.create_all(engine)
    username = input("Admin username: ").strip()
    password = getpass.getpass("Admin password (at least 10 characters): ")
    if len(username) < 3 or len(password) < 10:
        raise SystemExit("Username must have at least 3 characters and password at least 10")
    with Sessions() as db:
        if db.scalar(select(User).where(User.username == username)):
            raise SystemExit("Username already exists")
        db.add(User(username=username, password_hash=hasher.hash(password), role="admin"))
        db.commit()
    print("Admin created")


if __name__ == "__main__":
    main()
