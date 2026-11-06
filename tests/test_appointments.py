"""Parcours du module 3, frontières temporelles et conflits de réservation."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import os
from threading import Barrier

import jwt
import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.modules.auth.models.entities import User
from app.modules.auth.services import logic
from app.modules.appointments import availability, meetings, services
from app.modules.appointments.models import Appointment, Consultation, Reservation
from app.modules.communication.models import Notification
from app.modules.appointments.notifications import dispatch_one
from app.modules.appointments.schemas import BookingBody
from app.modules.psychologists.models import PsychologistProfile
from tests.test_auth import client
from tests.test_profiles import system

DAY = date(2030, 1, 10)


@pytest.fixture
def planning(system, monkeypatch):
    tc, h, ids, session, root, delivered, users = system
    settings = get_settings()
    for key, value in {'appointment_timezone': 'Africa/Douala', 'consultation_default_minutes': 45,
        'consultation_allowed_minutes': '30,45,60', 'appointment_slot_step_minutes': 15,
        'appointment_max_advance_days': 180, 'appointment_cancel_notice_minutes': 60,
        'consultation_early_join_minutes': 15, 'consultation_access_grace_minutes': 15,
        'jitsi_base_url': 'https://video.example.com', 'jitsi_app_id': 'free-and-talk',
        'jitsi_jwt_subject': 'meet.jitsi', 'jitsi_jwt_secret': 'test-meeting-secret-' * 3}.items():
        monkeypatch.setattr(settings, key, value)
    clock = {'now': datetime(2030, 1, 8, 8, tzinfo=timezone.utc)}
    for module in (availability, services, meetings):
        monkeypatch.setattr(module, 'now', lambda: clock['now'])
    with session() as db:
        for key in ('psy', 'other'):
            profile = db.get(PsychologistProfile, ids[key])
            profile.verification_status = 'approved'
            profile.approved_at = logic.now()
        other = User(fullname='Autre patient', email='patient2@example.com', role_id=1,
                     password_hash='not-used', email_verified=True)
        db.add(other)
        db.flush()
        users['patient2'] = other.id
        tokens, _ = logic.issue_tokens(db, other)
        h['patient2'] = {'Authorization': 'Bearer ' + tokens['access_token']}
        db.commit()
    result = (*system, clock)
    for who in ('psy', 'other'):
        for day in (DAY, DAY + timedelta(days=1)):
            add_window(result, who=who, day=day)
    return result


def add_window(planning, *, who='psy', day=DAY, start='09:00', end='17:00', mode='online', location=None):
    tc, h, *_ = planning
    response = tc.post('/api/psychologists/me/availability', headers=h[who], json={
        'day_of_week': (day.weekday() + 1) % 7, 'start_time': start, 'end_time': end,
        'consultation_mode': mode, 'location': location})
    assert response.status_code == 201, response.text
    return response.json()['availability']


def body(planning, start='2030-01-10T09:00:00+01:00', **extra):
    return {'psychologist_id': planning[2]['psy'], 'start_datetime': start,
            'consultation_mode': 'online', 'reason': 'Motif privé du patient', 'notes': 'Notes confidentielles', **extra}


def book(planning, start='2030-01-10T09:00:00+01:00', *, patient='patient', **extra):
    tc, h, *_ = planning
    response = tc.post('/api/appointments', headers=h[patient], json=body(planning, start, **extra))
    assert response.status_code == 201, response.text
    return response.json()['appointment']


def accept(planning, item):
    tc, h, *_ = planning
    response = tc.post(f'/api/psychologists/me/appointments/{item["id"]}/accept', headers=h['psy'])
    assert response.status_code == 200, response.text


def test_availability_crud_overlap_and_ownership(planning):
    tc, h, ids, session, *_ = planning
    day = DAY + timedelta(days=2)
    item = add_window(planning, day=day, start='10:00', end='12:00')
    payload = {'day_of_week': (day.weekday() + 1) % 7, 'start_time': '11:00', 'end_time': '13:00', 'consultation_mode': 'online'}
    assert tc.post('/api/psychologists/me/availability', headers=h['psy'], json=payload).status_code == 409
    route = '/api/psychologists/me/availability/' + item['id']
    assert tc.put(route, headers=h['other'], json=payload).status_code == 404
    assert tc.put(route, headers=h['psy'], json=payload).status_code == 200
    assert tc.delete(route, headers=h['other']).status_code == 404
    assert tc.delete(route, headers=h['psy']).status_code == 200
    assert tc.post('/api/psychologists/me/availability', headers=h['patient'], json=payload).status_code == 403
    with session() as db:
        db.get(PsychologistProfile, ids['psy']).verification_status = 'suspended'
        db.commit()
    assert tc.post('/api/psychologists/me/availability', headers=h['psy'], json=payload).status_code == 403


def test_invalid_hours_and_unauthorized_mode(planning):
    tc, h, ids, session, *_ = planning
    for start, end in (('12:00', '10:00'), ('10:00:01', '12:00'), ('10:00+01:00', '12:00')):
        assert tc.post('/api/psychologists/me/availability', headers=h['psy'], json={
            'day_of_week': 0, 'start_time': start, 'end_time': end, 'consultation_mode': 'online'}).status_code == 422
    with session() as db:
        db.get(PsychologistProfile, ids['psy']).consultation_modes = ['online']
        db.commit()
    assert tc.post('/api/psychologists/me/availability', headers=h['psy'], json={
        'day_of_week': 0, 'start_time': '09:00', 'end_time': '12:00', 'consultation_mode': 'in_person',
        'location': 'Cabinet professionnel'}).status_code == 400


def test_unavailability_crud_and_slot_exclusion(planning):
    tc, h, ids, *_ = planning
    payload = {'start_datetime': '2030-01-10T09:00:00+01:00', 'end_datetime': '2030-01-10T10:00:00+01:00', 'reason': 'Congé privé'}
    response = tc.post('/api/psychologists/me/unavailability', headers=h['psy'], json=payload)
    assert response.status_code == 201
    item = response.json()['unavailability']
    route = '/api/psychologists/me/unavailability/' + item['id']
    assert tc.post('/api/psychologists/me/unavailability', headers=h['psy'], json=payload).status_code == 409
    assert tc.put(route, headers=h['other'], json=payload).status_code == 404
    assert tc.put(route, headers=h['psy'], json=payload).status_code == 200
    slots = tc.get(f'/api/psychologists/{ids["psy"]}/available-slots', params={'date': str(DAY)}).json()
    assert slots['timezone'] == 'Africa/Douala'
    assert datetime.fromisoformat(slots['slots'][0]['start_datetime']) == datetime.fromisoformat('2030-01-10T09:00:00+00:00')
    assert 'Congé privé' not in str(slots)
    assert tc.post('/api/appointments', headers=h['patient'], json=body(planning)).status_code == 409
    assert tc.delete(route, headers=h['other']).status_code == 404
    assert tc.delete(route, headers=h['psy']).status_code == 200
    assert tc.get('/api/psychologists/me/unavailability', headers=h['psy']).json()['items'] == []


def test_booking_reserves_pending_slots_and_patient_time(planning):
    tc, h, ids, session, *_ = planning
    first = book(planning)
    assert first['status'] == 'pending'
    assert datetime.fromisoformat(first['start_datetime']) == datetime.fromisoformat('2030-01-10T08:00:00+00:00')
    assert tc.post('/api/appointments', headers=h['patient2'], json=body(planning)).status_code == 409
    assert tc.post('/api/appointments', headers=h['patient'], json=body(planning, psychologist_id=ids['other'])).status_code == 409
    assert tc.post('/api/appointments', headers=h['patient2'], json=body(planning, '2030-01-10T09:15:00+01:00')).status_code == 409
    book(planning, '2030-01-10T09:45:00+01:00', patient='patient2')
    with session() as db:
        assert db.scalar(select(func.count()).select_from(Reservation)) == 180
        assert db.scalar(select(func.count()).select_from(Notification).where(
            Notification.type == 'appointment_requested')) == 4
    assert tc.get('/api/appointments/me', headers=h['patient']).json()['total'] == 1
    assert tc.get('/api/psychologists/me/appointments', headers=h['psy']).json()['total'] == 2


def test_booking_requires_valid_slot_and_verified_approved_account(planning):
    tc, h, ids, session, *_ = planning
    assert tc.post('/api/appointments', json=body(planning)).status_code == 401
    assert tc.post('/api/appointments', headers=h['psy'], json=body(planning)).status_code == 403
    assert tc.post('/api/appointments', headers=h['patient'], json={**body(planning), 'patient_id': 'other'}).status_code == 422
    for start in ('2030-01-10T08:00:00+01:00', '2030-01-10T09:07:00+01:00', '2029-01-01T09:00:00+01:00'):
        assert tc.post('/api/appointments', headers=h['patient'], json=body(planning, start)).status_code == 400
    assert tc.post('/api/appointments', headers=h['patient'], json=body(planning, duration=37)).status_code == 422
    for status in ('pending_documents', 'rejected', 'suspended'):
        with session() as db:
            db.get(PsychologistProfile, ids['psy']).verification_status = status
            db.commit()
        assert tc.post('/api/appointments', headers=h['patient'], json=body(planning)).status_code == 403
    with session() as db:
        profile = db.get(PsychologistProfile, ids['psy'])
        profile.verification_status = 'approved'
        db.get(User, profile.user_id).is_active = False
        db.commit()
    assert tc.post('/api/appointments', headers=h['patient'], json=body(planning)).status_code == 403


def test_changes_to_schedule_require_treating_bookings(planning):
    tc, h, *_ = planning
    item = book(planning)
    accept(planning, item)
    windows = tc.get('/api/psychologists/me/availability', headers=h['psy']).json()['items']
    window = next(row for row in windows if row['day_of_week'] == (DAY.weekday() + 1) % 7)
    payload = {key: window[key] for key in ('day_of_week', 'start_time', 'end_time', 'consultation_mode', 'location', 'is_active')}
    route = '/api/psychologists/me/availability/' + window['id']
    assert tc.put(route, headers=h['psy'], json=payload).status_code == 409
    assert tc.delete(route, headers=h['psy']).status_code == 409
    assert tc.post('/api/psychologists/me/unavailability', headers=h['psy'], json={
        'start_datetime': '2030-01-10T09:00:00+01:00', 'end_datetime': '2030-01-10T10:00:00+01:00'}).status_code == 409
    assert tc.post(f'/api/psychologists/me/appointments/{item["id"]}/cancel', headers=h['psy'], json={'reason': 'Empêchement'}).status_code == 200
    assert tc.delete(route, headers=h['psy']).status_code == 200


def test_rescheduling_history_new_slot_and_second_confirmation(planning):
    tc, h, _, session, *_ = planning
    item = book(planning)
    accept(planning, item)
    with session() as db:
        old_room = db.scalar(select(Consultation)).meeting_room
    route = '/api/appointments/' + item['id']
    response = tc.put(route + '/reschedule', headers=h['patient'], json={
        'new_start_datetime': '2030-01-11T10:00:00+01:00', 'reason': 'Changement personnel'})
    assert response.status_code == 200, response.text
    assert response.json()['appointment']['status'] == 'reschedule_requested'
    assert tc.get(route + '/consultation/access', headers=h['patient']).status_code == 409
    book(planning, patient='patient2')  # ancien créneau libéré atomiquement
    assert tc.post('/api/appointments', headers=h['patient2'], json=body(planning, '2030-01-11T10:00:00+01:00')).status_code == 409
    accept(planning, item)
    detail = tc.get(route, headers=h['patient']).json()
    event, = [row for row in detail['history'] if row['action'] == 'RESCHEDULE_REQUESTED']
    assert datetime.fromisoformat(event['old_start_datetime']) == datetime.fromisoformat('2030-01-10T08:00:00+00:00')
    assert datetime.fromisoformat(event['new_start_datetime']) == datetime.fromisoformat('2030-01-11T09:00:00+00:00')
    with session() as db:
        assert db.scalar(select(Consultation)).meeting_room != old_room
        assert db.scalar(select(func.count()).select_from(Consultation)) == 1


def test_conflicting_reschedule_keeps_original_reservation(planning):
    tc, h, *_ = planning
    first = book(planning)
    book(planning, '2030-01-10T11:00:00+01:00', patient='patient2')
    response = tc.put(f'/api/appointments/{first["id"]}/reschedule', headers=h['patient'], json={
        'new_start_datetime': '2030-01-10T11:00:00+01:00', 'reason': 'Report'})
    assert response.status_code == 409
    original = tc.get(f'/api/appointments/{first["id"]}', headers=h['patient']).json()
    assert datetime.fromisoformat(original['start_datetime']) == datetime.fromisoformat('2030-01-10T08:00:00+00:00') and original['status'] == 'pending'
    assert tc.post('/api/appointments', headers=h['patient2'], json=body(planning)).status_code == 409


@pytest.mark.parametrize('actor,route', [('patient', '/api/appointments'), ('psy', '/api/psychologists/me/appointments'), ('admin', '/api/admin/appointments')])
def test_cancellation_permissions_and_atomic_release(planning, actor, route):
    tc, h, _, session, *_ = planning
    item = book(planning)
    assert tc.post(route + f'/{item["id"]}/cancel', headers=h[actor], json={'reason': 'Annulation'}).status_code == 200
    with session() as db:
        assert db.scalar(select(func.count()).select_from(Reservation)) == 0
        assert db.get(Appointment, item['id']).cancelled_by is not None
    assert tc.post(route + f'/{item["id"]}/cancel', headers=h[actor], json={'reason': 'Annulation'}).status_code == 409
    book(planning, patient='patient2')


def test_cancellation_cutoff_and_rejection(planning):
    tc, h, _, _, _, _, _, clock = planning
    item = book(planning)
    clock['now'] = datetime(2030, 1, 10, 7, 30, tzinfo=timezone.utc)
    assert tc.post(f'/api/appointments/{item["id"]}/cancel', headers=h['patient'], json={'reason': 'Annuler'}).status_code == 409
    assert tc.post(f'/api/psychologists/me/appointments/{item["id"]}/reject', headers=h['psy'], json={'reason': 'Non disponible'}).status_code == 200
    assert tc.post(f'/api/psychologists/me/appointments/{item["id"]}/accept', headers=h['psy']).status_code == 409


def test_private_details_and_admin_metadata(planning):
    tc, h, ids, *_ = planning
    item = book(planning)
    route = f'/api/appointments/{item["id"]}'
    for who in ('patient2', 'other'):
        assert tc.get(route, headers=h[who]).status_code == 403
        assert tc.post(route + '/consultation/start', headers=h[who]).status_code == 403
        assert tc.put(route + '/reschedule', headers=h[who], json={
            'new_start_datetime': '2030-01-11T10:00:00+01:00', 'reason': 'Report'}).status_code == 403
    assert tc.get(route, headers=h['patient']).json()['notes'] == 'Notes confidentielles'
    admin = tc.get('/api/admin/appointments/' + item['id'], headers=h['admin'])
    assert admin.status_code == 200
    assert 'notes' not in admin.json() and 'reason' not in admin.json()
    assert tc.get('/api/admin/appointments', headers=h['patient']).status_code == 403
    listed = tc.get('/api/admin/appointments', headers=h['admin'], params={'psychologist_id': ids['psy'], 'status': 'pending'})
    assert listed.json()['total'] == 1
    assert tc.get('/api/appointments/me', headers=h['patient2']).json()['total'] == 0


def test_consultation_lifecycle_timing_and_jitsi_token(planning):
    tc, h, _, _, _, _, users, clock = planning
    item = book(planning)
    route = f'/api/appointments/{item["id"]}/consultation'
    assert tc.post(route + '/start', headers=h['patient']).status_code == 409
    accept(planning, item)
    assert tc.post(route + '/start', headers=h['patient']).status_code == 403
    assert tc.get(route + '/access', headers=h['patient']).status_code == 403
    clock['now'] = datetime(2030, 1, 10, 7, 50, tzinfo=timezone.utc)
    response = tc.get(route + '/access', headers=h['patient'])
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'private, no-store'
    result = response.json()
    settings = get_settings()
    claims = jwt.decode(result['access_token'], settings.jitsi_jwt_secret, algorithms=['HS256'],
                        audience=settings.jitsi_app_id, issuer=settings.jitsi_app_id,
                        options={'verify_exp': False, 'verify_iat': False, 'verify_nbf': False})
    assert claims['room'] == result['meeting_url'].rsplit('/', 1)[-1]
    assert claims['room'] != '*' and len(claims['room']) > 40
    assert claims['context']['user']['id'] == users['patient']
    assert claims['exp'] - claims['iat'] <= 300
    assert tc.get(route + '/access', headers=h['patient2']).status_code == 403
    assert tc.get(route + '/access', headers=h['admin']).status_code == 403
    assert tc.post(route + '/start', headers=h['admin']).status_code == 403
    assert tc.post(route + '/start', headers=h['patient']).status_code == 200
    assert tc.post(route + '/start', headers=h['psy']).status_code == 409
    assert tc.post(route + '/end', headers=h['psy']).status_code == 200
    assert tc.get(route + '/access', headers=h['patient']).status_code == 409
    assert tc.post(route + '/start', headers=h['patient']).status_code == 409
    history = tc.get('/api/admin/consultations', headers=h['admin']).json()
    assert history['items'][0]['status'] == 'completed'
    assert 'meeting_url' not in str(history) and 'access_token' not in str(history)


def test_unconfigured_provider_fails_closed(planning, monkeypatch):
    tc, h, _, _, _, _, _, clock = planning
    item = book(planning)
    accept(planning, item)
    clock['now'] = datetime(2030, 1, 10, 7, 50, tzinfo=timezone.utc)
    monkeypatch.setattr(get_settings(), 'jitsi_jwt_secret', '')
    response = tc.get(f'/api/appointments/{item["id"]}/consultation/access', headers=h['patient'])
    assert response.status_code == 503
    assert response.json()['detail']['code'] == 'MEETING_PROVIDER_NOT_CONFIGURED'


def test_in_person_location_is_private_until_confirmed(planning):
    tc, h, _, _, _, _, _, clock = planning
    day = DAY + timedelta(days=2)
    add_window(planning, day=day, mode='in_person', location='Cabinet professionnel, Douala')
    item = book(planning, day.isoformat() + 'T09:00:00+01:00', consultation_mode='in_person')
    route = f'/api/appointments/{item["id"]}'
    assert 'location' not in tc.get(route, headers=h['patient']).json()
    accept(planning, item)
    assert tc.get(route, headers=h['patient']).json()['location'] == 'Cabinet professionnel, Douala'
    clock['now'] = datetime(2030, 1, 12, 7, 50, tzinfo=timezone.utc)
    assert tc.get(route + '/consultation/access', headers=h['patient']).status_code == 400
    assert tc.post(route + '/consultation/start', headers=h['psy']).status_code == 200
    assert tc.post(f'/api/psychologists/me/appointments/{item["id"]}/complete', headers=h['psy']).status_code == 200


def test_timezone_and_dst_boundaries(planning, monkeypatch):
    tc, h, ids, *_ = planning
    # Un horaire sans offset est interprété dans le fuseau configuré.
    item = book(planning, '2030-01-10T09:00:00')
    assert datetime.fromisoformat(item['start_datetime']) == datetime.fromisoformat('2030-01-10T08:00:00+00:00')
    monkeypatch.setattr(get_settings(), 'appointment_timezone', 'Europe/Paris')
    from app.modules.appointments.schemas import local_instant
    with pytest.raises(ValueError):
        local_instant(datetime(2030, 3, 31, 2, 30))
    with pytest.raises(ValueError):
        local_instant(datetime(2030, 10, 27, 2, 30))
    assert local_instant(datetime(2030, 1, 10, 9)).hour == 8


def test_notification_outbox_delivery_retry_and_no_private_content(planning, monkeypatch):
    tc, h, _, session, *_ = planning
    book(planning)
    sent = []
    monkeypatch.setattr(logic, 'email_message', lambda to, content: sent.append((to, content)))
    with session() as db:
        assert dispatch_one(db) == 'sent'
        assert dispatch_one(db) == 'sent'
        assert dispatch_one(db) is None
    assert len(sent) == 2
    assert all('Notes confidentielles' not in content and 'Motif privé' not in content for _, content in sent)
    book(planning, '2030-01-10T11:00:00+01:00')
    def failed(*args):
        raise RuntimeError('SMTP unavailable')
    monkeypatch.setattr(logic, 'email_message', failed)
    with session() as db:
        assert dispatch_one(db, max_attempts=1) == 'failed'
        assert db.scalar(select(func.count()).select_from(Appointment)) == 2


def test_locked_read_refreshes_cached_professional_status(planning):
    from fastapi import HTTPException
    _, _, ids, session, *_ = planning
    with session() as reader:
        cached = reader.get(PsychologistProfile, ids['psy'])
        assert cached.verification_status == 'approved'
        with session() as writer:
            writer.get(PsychologistProfile, ids['psy']).verification_status = 'suspended'
            writer.commit()
        with pytest.raises(HTTPException) as error:
            availability.approved_profile(reader, ids['psy'], lock=True)
        assert error.value.status_code == 403


def test_database_constraint_prevents_duplicate_reserved_minute(planning):
    from sqlalchemy.exc import IntegrityError
    _, _, ids, session, *_ = planning
    item = book(planning, duration=60)
    assert datetime.fromisoformat(item['end_datetime']) - datetime.fromisoformat(item['start_datetime']) == timedelta(minutes=60)
    with session() as db:
        existing = db.scalar(select(Reservation).where(Reservation.resource_kind == 'psychologist'))
        db.add(Reservation(appointment_id=item['id'], resource_kind='psychologist',
                           resource_id=ids['psy'], minute=existing.minute))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
        assert db.scalar(select(func.count()).select_from(Reservation)) == 120


@pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'), reason='Concurrence testée sur MySQL/MariaDB isolé')
@pytest.mark.parametrize('same_patient', [False, True])
def test_concurrent_reservations_are_serialized(planning, same_patient):
    tc, h, ids, session, _, _, users, _ = planning
    barrier = Barrier(2)
    def run(index):
        patient_id = users['patient'] if same_patient or index == 0 else users['patient2']
        profile_id = ids['psy'] if not same_patient or index == 0 else ids['other']
        with session() as db:
            patient = db.get(User, patient_id)
            payload = BookingBody(**body(planning, psychologist_id=profile_id))
            barrier.wait(timeout=10)
            try:
                services.book(db, patient, payload)
                return 201
            except Exception as exc:
                from fastapi import HTTPException
                if isinstance(exc, HTTPException):
                    return exc.status_code
                raise
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, (0, 1)))
    assert sorted(results) == [201, 409]
    with session() as db:
        assert db.scalar(select(func.count()).select_from(Appointment)) == 1
        assert db.scalar(select(func.count()).select_from(Reservation)) == 90
