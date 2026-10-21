"""Operator maintenance: expire pending requests and erase their credential hashes."""
from app.db import make_engine
from app.application.account_requests import expire_pending


def main():
    engine=make_engine()
    try:
        with engine.begin() as conn:
            count=expire_pending(conn)
        print('Expired pending account requests:',count)
    finally:engine.dispose()


if __name__=='__main__':main()
