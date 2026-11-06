"""Accès Jitsi JWT : salle aléatoire et jeton court limité à une seule salle."""
from datetime import timedelta
import secrets

import jwt

from app.core.config import get_settings
from app.modules.auth.services.logic import fail, now, utc


def new_room():
    return 'ft-' + secrets.token_hex(24)


def room_url(room):
    base = get_settings().jitsi_base_url
    return base.rstrip('/') + '/' + room if base else None


def access_window(appointment):
    settings = get_settings()
    earliest = utc(appointment.start_datetime) - timedelta(minutes=settings.consultation_early_join_minutes)
    latest = utc(appointment.end_datetime) + timedelta(minutes=settings.consultation_access_grace_minutes)
    if not earliest <= now() < latest:
        fail(403, 'CONSULTATION_OUTSIDE_ACCESS_WINDOW')
    return latest


def meeting_access(appointment, consultation, user):
    settings = get_settings()
    latest = access_window(appointment)
    if not all((settings.jitsi_base_url, settings.jitsi_app_id, settings.jitsi_jwt_secret, settings.jitsi_jwt_subject)):
        fail(503, 'MEETING_PROVIDER_NOT_CONFIGURED')
    timestamp = now()
    expires = min(latest, timestamp + timedelta(minutes=settings.meeting_token_minutes))
    claims = {'iss': settings.jitsi_app_id, 'aud': settings.jitsi_jwt_audience or settings.jitsi_app_id,
              'sub': settings.jitsi_jwt_subject, 'room': consultation.meeting_room,
              'iat': timestamp, 'nbf': timestamp, 'exp': expires,
              'context': {'user': {'id': user.id, 'name': user.fullname}}}
    token = jwt.encode(claims, settings.jitsi_jwt_secret, algorithm='HS256')
    return {'appointment_id': appointment.id, 'consultation_mode': 'online', 'provider': 'jitsi',
            'meeting_url': room_url(consultation.meeting_room), 'access_token': token, 'expires_at': expires}
