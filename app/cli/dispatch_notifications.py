"""Envoyer les notifications en attente : python -m app.cli.dispatch_notifications."""
import argparse
import time
from app.core.database import SessionLocal
from app.modules.communication.notifications import dispatch_one, enqueue_reminders


def main():
    parser = argparse.ArgumentParser(description='Envoyer les notifications de rendez-vous en attente')
    parser.add_argument('--limit', type=int, default=100)
    parser.add_argument('--max-attempts', type=int, default=5)
    parser.add_argument('--watch', action='store_true', help='Traiter la file en continu')
    parser.add_argument('--interval', type=int, default=5, help='Pause entre deux lots, en secondes')
    args = parser.parse_args()
    if not 1 <= args.limit <= 10000 or not 1 <= args.max_attempts <= 20 or not 1 <= args.interval <= 60:
        parser.error('Limites invalides')
    try:
        while True:
            counts = {'sent': 0, 'pending': 0, 'failed': 0, 'skipped': 0}
            with SessionLocal() as db:
                counts['pending'] += enqueue_reminders(db)
            for _ in range(args.limit):
                with SessionLocal() as db:
                    result = dispatch_one(db, max_attempts=args.max_attempts)
                if result is None:
                    break
                counts[result] = counts.get(result, 0) + 1
            if any(counts.values()) or not args.watch:
                print('Notifications :', counts, flush=True)
            if not args.watch:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print('Worker arrêté.')


if __name__ == '__main__':
    main()
