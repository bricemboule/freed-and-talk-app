"""Outbox transactionnelle : notification durable, envoi par un worker séparé."""
from datetime import timedelta

from sqlalchemy import select

from app.modules.auth.models.entities import User
from app.modules.auth.services import logic as mail
from .models import AppointmentNotification


def queue_notifications(db, appointment, history, psychologist_user_id):
    """Créer les notifications in-app et leur outbox email dans la transaction métier."""
    from app.modules.communication.notifications import notify
    kind = {
        'REQUESTED': 'appointment_requested',
        'CONFIRMED': 'appointment_confirmed',
        'REJECTED': 'appointment_rejected',
        'CANCELLED': 'appointment_cancelled',
        'RESCHEDULE_REQUESTED': 'appointment_rescheduled',
        'CONSULTATION_STARTED': 'consultation_started',
        'CONSULTATION_COMPLETED': 'consultation_completed',
    }.get(history.action)
    if not kind:
        return
    event_key = history.id
    for user_id in {appointment.patient_id, psychologist_user_id}:
        notify(db, user_id, kind, event_key=event_key, email=True,
               data={'appointment_id': appointment.id,
                     'start_datetime': mail.utc(appointment.start_datetime).isoformat(),
                     'status': appointment.status})


def dispatch_legacy_one(db, *, max_attempts=5):
    item = db.scalar(select(AppointmentNotification).where(
        AppointmentNotification.status == 'pending', AppointmentNotification.next_attempt_at <= mail.now(),
        AppointmentNotification.attempts < max_attempts).order_by(AppointmentNotification.created_at)
        .limit(1).with_for_update(skip_locked=True))
    if item is None:
        return None
    user = db.get(User, item.recipient_id)
    item.attempts += 1
    try:
        mail.email_message(user.email, item.body)
        item.status = 'sent'
        item.sent_at = mail.now()
    except Exception:
        item.status = 'failed' if item.attempts >= max_attempts else 'pending'
        item.next_attempt_at = mail.now() + timedelta(minutes=min(2 ** item.attempts, 60))
    db.commit()
    return item.status


def dispatch_one(db, *, max_attempts=5):
    """Garder le point d'entrée historique tout en utilisant la file commune."""
    from app.modules.communication.notifications import dispatch_one as dispatch_common
    return dispatch_common(db, max_attempts=max_attempts)
