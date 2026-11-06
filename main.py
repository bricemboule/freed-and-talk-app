"""Démarrage local : python main.py (migration puis serveur)."""
from pathlib import Path
import argparse
import os


def main():
    parser = argparse.ArgumentParser(description='FREE & TALK : migrations et serveur local')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    # Resolve local paths consistently, including when launched by an IDE.
    os.chdir(Path(__file__).resolve().parent)
    from alembic import command
    from alembic.config import Config
    import uvicorn

    command.upgrade(Config('alembic.ini'), 'head')
    uvicorn.run('app.main:app', host='127.0.0.1', port=args.port)


if __name__ == '__main__':
    main()
