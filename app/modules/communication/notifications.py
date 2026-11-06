"""Modèles de notifications sans contenu médical et outbox commune aux modules."""
from datetime import timedelta
from sqlalchemy import func, select, update

from app.core.config import get_settings
from app.modules.auth.models.entities import User
from app.modules.auth.services import logic
from .models import Notification, NotificationLog, NotificationPreferences, RealtimeEvent

TEMPLATES = {
    'account_created': ('Compte créé', 'Votre compte FREE & TALK a été créé.'),
    'psychologist_approved': ('Profil professionnel approuvé', 'Votre dossier professionnel a été approuvé.'),
    'psychologist_rejected': ('Dossier à corriger', 'Une décision concernant votre dossier est disponible dans votre compte.'),
    'new_message': ('Nouveau message', 'Vous avez reçu un nouveau message. Connectez-vous pour le consulter.'),
    'appointment_requested': ('Demande de rendez-vous', 'Une demande de rendez-vous a été enregistrée.'),
    'appointment_confirmed': ('Rendez-vous confirmé', 'Votre rendez-vous a été confirmé.'),
    'appointment_rejected': ('Rendez-vous refusé', 'Une demande de rendez-vous a été refusée.'),
    'appointment_cancelled': ('Rendez-vous annulé', 'Votre rendez-vous a été annulé.'),
    'appointment_rescheduled': ('Report de rendez-vous', 'Une demande de report de rendez-vous a été enregistrée.'),
    'appointment_reminder': ('Rappel de rendez-vous', 'Un rendez-vous approche. Consultez votre agenda FREE & TALK.'),
    'consultation_started': ('Consultation démarrée', 'Votre consultation a démarré.'),
    'consultation_completed': ('Consultation terminée', 'Votre consultation est terminée.'),
    'payment_pending': ('Demande de paiement créée', 'Votre demande de paiement est enregistrée en mode test; aucun débit réel n’a été effectué.'),
    'security_alert': ('Sécurité de votre compte', 'Une modification importante de votre compte a été effectuée. Si vous ne la reconnaissez pas, contactez le support.'),
    'system_announcement': ('Information FREE & TALK', 'Une information concernant votre compte est disponible.'),
}
DEFAULT_PREFERENCES = dict(email_notifications=True, message_email_notifications=False,
                           appointment_reminders=True, push_notifications=True)


def preferences(db, user_id):
    item = db.scalar(select(NotificationPreferences).where(NotificationPreferences.user_id == user_id))
    return {key: getattr(item, key) for key in DEFAULT_PREFERENCES} if item else dict(DEFAULT_PREFERENCES)


def email_allowed(db, notification):
    if notification.security_required:
        return True
    prefs = preferences(db, notification.user_id)
    if not prefs['email_notifications']:
        return False
    if notification.type == 'new_message' and not prefs['message_email_notifications']:
        return False
    return notification.type != 'appointment_reminder' or prefs['appointment_reminders']


def emit(db, user_id, event, data):
    db.add(RealtimeEvent(user_id=user_id, event=event, data=data))


def notify(db, user_id, kind, *, data=None, event_key=None, security=False, email=True):
    if event_key:
        existing = db.scalar(select(Notification).where(Notification.user_id == user_id,
            Notification.type == kind, Notification.event_key == event_key))
        if existing:
            return existing
    title, content = TEMPLATES[kind]
    item = Notification(user_id=user_id, type=kind, title=title, content=content,
                        data=data or {}, event_key=event_key, security_required=security)
    db.add(item)
    db.flush()
    db.add(NotificationLog(notification_id=item.id, channel='in_app', status='sent', sent_at=logic.now()))
    if email and email_allowed(db, item):
        db.add(NotificationLog(notification_id=item.id, channel='email', status='pending'))
    if preferences(db, user_id)['push_notifications']:
        emit(db, user_id, 'new_notification', {'notification_id': item.id})
    return item


def notification_view(item):
    return {'id': item.id, 'type': item.type, 'title': item.title, 'content': item.content,
            'data': item.data, 'is_read': item.is_read, 'read_at': logic.utc(item.read_at),
            'created_at': logic.utc(item.created_at)}


def unread_count(db, user_id):
    return db.scalar(select(func.count()).select_from(Notification).where(Notification.user_id == user_id,
                     Notification.is_read.is_(False), Notification.deleted_at.is_(None)))


def list_notifications(db, user, page=1, limit=20, unread_only=False):
    query = select(Notification).where(Notification.user_id == user.id, Notification.deleted_at.is_(None))
    if unread_only:
        query = query.where(Notification.is_read.is_(False))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = db.scalars(query.order_by(Notification.created_at.desc(), Notification.id.desc())
                       .offset((page - 1) * limit).limit(limit))
    return {'items': [notification_view(item) for item in items], 'total': total,
            'unread_count': unread_count(db, user.id), 'page': page, 'limit': limit}


def mutate_notification(db, user, notification_id, *, remove=False):
    item = db.scalar(select(Notification).where(Notification.id == notification_id,
        Notification.user_id == user.id).with_for_update())
    if not item:
        logic.fail(404, 'NOTIFICATION_NOT_FOUND')
    if remove:
        item.deleted_at = item.deleted_at or logic.now()
    else:
        if item.deleted_at:
            logic.fail(404, 'NOTIFICATION_NOT_FOUND')
        item.is_read, item.read_at = True, item.read_at or logic.now()
    db.commit()
    return {'message': 'Notification supprimée.' if remove else 'Notification marquée comme lue.'}


def read_all(db, user):
    result = db.execute(update(Notification).where(Notification.user_id == user.id,
        Notification.deleted_at.is_(None), Notification.is_read.is_(False)).values(is_read=True, read_at=logic.now()))
    db.commit()
    return {'message': 'Toutes les notifications ont été marquées comme lues.', 'updated_count': result.rowcount}


def set_preferences(db, user, body):
    # Sérialiser les créations concurrentes sans verrouiller les conversations.
    db.execute(select(User.id).where(User.id == user.id).with_for_update())
    item = db.scalar(select(NotificationPreferences).where(NotificationPreferences.user_id == user.id).with_for_update())
    if item is None:
        item = NotificationPreferences(user_id=user.id)
        db.add(item)
    for key, value in body.model_dump().items():
        setattr(item, key, value)
    db.commit()
    return {'message': 'Préférences mises à jour.'}


def dispatch_one(db, *, max_attempts=5):
    # Drainer les lignes du module 3 déjà présentes avant cette migration.
    from app.modules.appointments.notifications import dispatch_legacy_one
    previous = dispatch_legacy_one(db, max_attempts=max_attempts)
    if previous is not None:
        return previous
    log = db.scalar(select(NotificationLog).where(NotificationLog.channel == 'email',
        NotificationLog.status == 'pending', NotificationLog.attempts < max_attempts,
        NotificationLog.next_attempt_at <= logic.now()).order_by(NotificationLog.created_at, NotificationLog.id)
        .limit(1).with_for_update(skip_locked=True))
    if log is None:
        return None
    item = db.get(Notification, log.notification_id)
    allowed = email_allowed(db, item)
    if item.type == 'appointment_reminder':
        from app.modules.appointments.models import Appointment
        appointment = db.get(Appointment, item.data.get('appointment_id'))
        allowed = allowed and appointment is not None and appointment.status == 'confirmed' and (
            logic.utc(appointment.start_datetime).isoformat() == item.data.get('start_datetime')) and logic.utc(appointment.start_datetime) > logic.now()
    if not allowed:
        log.status = 'skipped'
    else:
        log.attempts += 1
        try:
            user = db.get(User, item.user_id)
            logic.email_message(user.email, item.content + '\nConnectez-vous à votre compte FREE & TALK.')
            log.status, log.sent_at, log.error_message = 'sent', logic.now(), None
        except Exception as exc:
            # Garder une catégorie technique, jamais le message SMTP ni les secrets.
            log.error_message = type(exc).__name__[:100]
            log.status = 'failed' if log.attempts >= max_attempts else 'pending'
            log.next_attempt_at = logic.now() + timedelta(minutes=min(2 ** log.attempts, 60))
    db.commit()
    return log.status


def enqueue_reminders(db):
    from app.modules.appointments.models import Appointment
    from app.modules.psychologists.models import PsychologistProfile
    timestamp = logic.now()
    rows = list(db.scalars(select(Appointment).where(Appointment.status == 'confirmed',
        Appointment.start_datetime > timestamp,
        Appointment.start_datetime <= timestamp + timedelta(minutes=get_settings().appointment_reminder_minutes))
        .order_by(Appointment.start_datetime).limit(100).with_for_update(skip_locked=True)))
    count = 0
    for item in rows:
        profile = db.get(PsychologistProfile, item.psychologist_id)
        key = item.id + ':' + logic.utc(item.start_datetime).isoformat()
        for user_id in (item.patient_id, profile.user_id):
            if preferences(db, user_id)['appointment_reminders']:
                old = db.scalar(select(Notification.id).where(Notification.user_id == user_id,
                    Notification.type == 'appointment_reminder', Notification.event_key == key))
                if old is None:
                    notify(db, user_id, 'appointment_reminder', event_key=key,
                           data={'appointment_id': item.id, 'start_datetime': logic.utc(item.start_datetime).isoformat()})
                    count += 1
    db.commit()
    return count
