"""Transactions de réservation et transitions centralisées des rendez-vous."""
from datetime import timedelta
from functools import wraps

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import lazyload

from app.core.config import get_settings
from app.modules.auth.models.entities import User, uid
from app.modules.auth.services.logic import fail, now, utc
from app.modules.psychologists import services as professionals
from . import availability, meetings
from .models import (ACTIVE_STATUSES, Appointment, AppointmentHistory, Consultation, Reservation)
from .notifications import queue_notifications
from .schemas import BookingBody, RescheduleBody, instant


def transactional(function):
    @wraps(function)
    def call(db, *args, **kwargs):
        try:
            return function(db, *args, **kwargs)
        except IntegrityError:
            db.rollback()
            fail(409, 'RESERVATION_CONFLICT')
        except OperationalError as exc:
            db.rollback()
            code = exc.orig.args[0] if exc.orig.args else None
            if code in (1205, 1213) or getattr(exc.orig, 'sqlstate', None) in ('40001', '40P01'):
                fail(409, 'RESERVATION_CONFLICT_RETRY')
            raise
    return call


def lock_patient(db, patient_id):
    return db.scalar(select(User).options(lazyload(User.role)).where(User.id == patient_id)
                     .execution_options(populate_existing=True).with_for_update())


def get_appointment(db, appointment_id):
    item = db.get(Appointment, appointment_id)
    if not item:
        fail(404, 'APPOINTMENT_NOT_FOUND')
    return item


def authorize(db, item, actor, *, admin_allowed=True):
    profile = professionals.profile_by_id(db, item.psychologist_id)
    if actor.id != item.patient_id and actor.id != profile.user_id:
        if not admin_allowed or actor.role.code != 'admin':
            fail(403, 'APPOINTMENT_ACCESS_DENIED')
    return profile


def lock_appointment(db, appointment_id, actor):
    item = get_appointment(db, appointment_id)
    authorize(db, item, actor)
    # Ordre commun : patient -> profil -> rendez-vous. Les lectures verrouillées
    # sont courantes même sous REPEATABLE READ (MySQL/MariaDB).
    lock_patient(db, item.patient_id)
    profile = professionals.profile_by_id(db, item.psychologist_id, lock=True)
    item = db.scalar(select(Appointment).where(Appointment.id == item.id)
                     .execution_options(populate_existing=True).with_for_update())
    authorize(db, item, actor)
    return item, profile


def assert_free(db, patient_id, profile_id, start, end, *, exclude=None):
    query = select(Appointment.id).where(Appointment.status.in_(ACTIVE_STATUSES),
        or_(Appointment.patient_id == patient_id, Appointment.psychologist_id == profile_id),
        Appointment.start_datetime < end, Appointment.end_datetime > start)
    if exclude:
        query = query.where(Appointment.id != exclude)
    if db.scalar(query.with_for_update()):
        fail(409, 'SLOT_ALREADY_RESERVED')


def reserve(db, item):
    minute = utc(item.start_datetime)
    while minute < utc(item.end_datetime):
        for kind, resource_id in (('patient', item.patient_id), ('psychologist', item.psychologist_id)):
            db.add(Reservation(appointment_id=item.id, resource_kind=kind, resource_id=resource_id, minute=minute))
        minute += timedelta(minutes=1)
    db.flush()


def release(db, item):
    db.execute(delete(Reservation).where(Reservation.appointment_id == item.id))


def record(db, item, actor, profile, action, *, previous=None, old_start=None, old_end=None, reason=None):
    history = AppointmentHistory(id=uid(), appointment_id=item.id, actor_id=actor.id, action=action,
        previous_status=previous, new_status=item.status, old_start_datetime=old_start,
        old_end_datetime=old_end, new_start_datetime=item.start_datetime,
        new_end_datetime=item.end_datetime, reason=reason)
    db.add(history)
    db.flush()
    queue_notifications(db, item, history, profile.user_id)


def appointment_view(db, item, actor, *, detailed=False):
    profile = professionals.profile_by_id(db, item.psychologist_id)
    psychologist = db.get(User, profile.user_id)
    patient = db.get(User, item.patient_id)
    result = {'id': item.id, 'patient_id': item.patient_id, 'psychologist_id': profile.id,
              'patient': {'id': patient.id, 'fullname': patient.fullname},
              'psychologist': {'id': profile.id, 'fullname': psychologist.fullname, 'specialty': profile.specialty},
              'start_datetime': utc(item.start_datetime), 'end_datetime': utc(item.end_datetime),
              'timezone': item.timezone, 'consultation_mode': item.consultation_mode, 'status': item.status}
    result['fee'] = ({'amount': item.fee_amount, 'currency': item.fee_currency}
                     if item.fee_amount is not None else None)
    if item.status in {'confirmed', 'in_progress', 'completed'} and item.consultation_mode == 'in_person':
        result['location'] = item.location
    if detailed:
        result.update(cancellation_reason=item.cancellation_reason, cancelled_by=item.cancelled_by,
                      confirmed_at=utc(item.confirmed_at), cancelled_at=utc(item.cancelled_at))
        if actor.role.code != 'admin':
            result.update(reason=item.reason, notes=item.notes)
        history = db.scalars(select(AppointmentHistory).where(AppointmentHistory.appointment_id == item.id)
                             .order_by(AppointmentHistory.created_at, AppointmentHistory.id))
        result['history'] = [{'id': h.id, 'actor_id': h.actor_id, 'action': h.action,
            'previous_status': h.previous_status, 'new_status': h.new_status,
            'old_start_datetime': utc(h.old_start_datetime), 'old_end_datetime': utc(h.old_end_datetime),
            'new_start_datetime': utc(h.new_start_datetime), 'new_end_datetime': utc(h.new_end_datetime),
            'reason': h.reason, 'created_at': utc(h.created_at)} for h in history]
    return result


@transactional
def book(db, patient, body: BookingBody):
    locked = lock_patient(db, patient.id)
    if not locked.is_active or not locked.email_verified:
        fail(403, 'ACCOUNT_DISABLED')
    profile = availability.approved_profile(db, body.psychologist_id, lock=True)
    if profile.user_id == patient.id:
        fail(400, 'SELF_BOOKING_NOT_ALLOWED')
    start = body.start_datetime
    end = start + timedelta(minutes=availability.duration_minutes(body.duration))
    window = availability.find_window(db, profile, start, end, body.consultation_mode, lock=True)
    assert_free(db, patient.id, profile.id, start, end)
    item = Appointment(patient_id=patient.id, psychologist_id=profile.id, availability_id=window.id,
        start_datetime=start, end_datetime=end, consultation_mode=body.consultation_mode,
        timezone=get_settings().appointment_timezone, location=window.location, reason=body.reason, notes=body.notes,
        fee_amount=profile.consultation_fee, fee_currency=profile.consultation_currency)
    db.add(item)
    db.flush()
    reserve(db, item)
    record(db, item, patient, profile, 'REQUESTED')
    db.commit()
    return {'message': 'Demande de rendez-vous enregistrée.', 'appointment': appointment_view(db, item, patient)}


def details(db, actor, appointment_id):
    item = get_appointment(db, appointment_id)
    authorize(db, item, actor)
    return appointment_view(db, item, actor, detailed=True)


def patient_notice(item):
    if utc(item.start_datetime) <= now() + timedelta(minutes=get_settings().appointment_cancel_notice_minutes):
        fail(409, 'PATIENT_CHANGE_NOTICE_EXCEEDED')


def consultation_for(db, item):
    return db.scalar(select(Consultation).where(Consultation.appointment_id == item.id))


@transactional
def reschedule(db, patient, appointment_id, body: RescheduleBody):
    item, profile = lock_appointment(db, appointment_id, patient)
    if item.patient_id != patient.id:
        fail(403, 'APPOINTMENT_ACCESS_DENIED')
    if item.status not in {'pending', 'confirmed'}:
        fail(409, 'INVALID_APPOINTMENT_TRANSITION')
    patient_notice(item)
    availability.approved_profile(db, profile.id, lock=True)
    old_start, old_end, previous = utc(item.start_datetime), utc(item.end_datetime), item.status
    start, end = body.new_start_datetime, body.new_start_datetime + (old_end - old_start)
    if start == old_start:
        fail(400, 'RESCHEDULE_SAME_SLOT')
    window = availability.find_window(db, profile, start, end, item.consultation_mode, lock=True)
    assert_free(db, patient.id, profile.id, start, end, exclude=item.id)
    release(db, item)
    item.start_datetime, item.end_datetime = start, end
    item.availability_id, item.location = window.id, window.location
    item.status, item.confirmed_at = 'reschedule_requested', None
    consultation = consultation_for(db, item)
    if consultation:
        # Invalider la salle précédente ; aucun ancien JWT ne donne accès à la nouvelle.
        consultation.status = 'cancelled'
        consultation.meeting_room = None
        consultation.meeting_url = None
    reserve(db, item)
    record(db, item, patient, profile, 'RESCHEDULE_REQUESTED', previous=previous,
           old_start=old_start, old_end=old_end, reason=body.reason)
    db.commit()
    return {'message': 'Demande de report enregistrée.', 'appointment': appointment_view(db, item, patient)}


@transactional
def accept(db, psychologist, appointment_id):
    item, profile = lock_appointment(db, appointment_id, psychologist)
    if profile.user_id != psychologist.id:
        fail(403, 'APPOINTMENT_ACCESS_DENIED')
    if item.status not in {'pending', 'reschedule_requested'}:
        fail(409, 'INVALID_APPOINTMENT_TRANSITION')
    availability.approved_profile(db, profile.id, lock=True)
    window = availability.find_window(db, profile, utc(item.start_datetime), utc(item.end_datetime), item.consultation_mode, lock=True)
    assert_free(db, item.patient_id, profile.id, utc(item.start_datetime), utc(item.end_datetime), exclude=item.id)
    previous, item.status = item.status, 'confirmed'
    item.confirmed_at = now()
    item.location = window.location
    consultation = consultation_for(db, item)
    if not consultation:
        consultation = Consultation(appointment_id=item.id)
        db.add(consultation)
    consultation.status = 'scheduled'
    consultation.consultation_type = 'video' if item.consultation_mode == 'online' else 'in_person'
    consultation.started_at = consultation.ended_at = None
    if item.consultation_mode == 'online':
        consultation.provider = 'jitsi'
        consultation.meeting_room = meetings.new_room()
        consultation.meeting_url = meetings.room_url(consultation.meeting_room)
    record(db, item, psychologist, profile, 'CONFIRMED', previous=previous)
    db.commit()
    return {'message': 'Rendez-vous confirmé.', 'appointment_id': item.id, 'status': item.status}


@transactional
def cancel(db, actor, appointment_id, reason, *, reject=False, patient_action=False):
    item, profile = lock_appointment(db, appointment_id, actor)
    if patient_action and actor.id != item.patient_id:
        fail(403, 'APPOINTMENT_ACCESS_DENIED')
    if reject and actor.id != profile.user_id:
        fail(403, 'APPOINTMENT_ACCESS_DENIED')
    allowed = {'pending', 'reschedule_requested'} if reject else {'pending', 'confirmed', 'reschedule_requested'}
    if item.status not in allowed:
        fail(409, 'INVALID_APPOINTMENT_TRANSITION')
    if patient_action:
        patient_notice(item)
    previous, item.status = item.status, 'rejected' if reject else 'cancelled'
    item.cancellation_reason, item.cancelled_by, item.cancelled_at = reason, actor.id, now()
    release(db, item)
    consultation = consultation_for(db, item)
    if consultation:
        consultation.status = 'cancelled'
        consultation.meeting_room = consultation.meeting_url = None
    record(db, item, actor, profile, 'REJECTED' if reject else 'CANCELLED', previous=previous, reason=reason)
    db.commit()
    return {'message': 'Demande refusée.' if reject else 'Rendez-vous annulé.',
            'appointment_id': item.id, 'status': item.status}


def consultation_view(item, consultation):
    return {'id': consultation.id, 'appointment_id': item.id, 'consultation_mode': item.consultation_mode,
            'type': consultation.consultation_type,
            'status': consultation.status, 'start_datetime': utc(item.start_datetime),
            'end_datetime': utc(item.end_datetime), 'started_at': utc(consultation.started_at),
            'ended_at': utc(consultation.ended_at)}


def require_consultation(db, item):
    consultation = consultation_for(db, item)
    if not consultation:
        fail(404, 'CONSULTATION_NOT_FOUND')
    return consultation


def get_consultation(db, actor, appointment_id):
    item = get_appointment(db, appointment_id)
    authorize(db, item, actor)
    return consultation_view(item, require_consultation(db, item))


@transactional
def start_consultation(db, actor, appointment_id):
    item, profile = lock_appointment(db, appointment_id, actor)
    authorize(db, item, actor, admin_allowed=False)
    if item.status != 'confirmed':
        fail(409, 'INVALID_APPOINTMENT_TRANSITION')
    availability.approved_profile(db, profile.id, lock=True)
    meetings.access_window(item)
    if now() >= utc(item.end_datetime):
        fail(409, 'CONSULTATION_TIME_EXPIRED')
    consultation = require_consultation(db, item)
    if consultation.status != 'scheduled':
        fail(409, 'INVALID_CONSULTATION_TRANSITION')
    consultation.status, consultation.started_at = 'in_progress', now()
    item.status = 'in_progress'
    record(db, item, actor, profile, 'CONSULTATION_STARTED', previous='confirmed')
    db.commit()
    return {'message': 'Consultation démarrée.', 'consultation': consultation_view(item, consultation)}


@transactional
def end_consultation(db, actor, appointment_id, *, complete=False):
    item, profile = lock_appointment(db, appointment_id, actor)
    authorize(db, item, actor, admin_allowed=False)
    if complete and profile.user_id != actor.id:
        fail(403, 'APPOINTMENT_ACCESS_DENIED')
    allowed = {'confirmed', 'in_progress'} if complete else {'in_progress'}
    if item.status not in allowed:
        fail(409, 'INVALID_APPOINTMENT_TRANSITION')
    if item.status == 'confirmed' and now() < utc(item.end_datetime):
        fail(409, 'CONSULTATION_NOT_FINISHED')
    consultation = require_consultation(db, item)
    if consultation.status not in ({'scheduled', 'in_progress'} if complete else {'in_progress'}):
        fail(409, 'INVALID_CONSULTATION_TRANSITION')
    previous = item.status
    item.status, consultation.status, consultation.ended_at = 'completed', 'completed', now()
    release(db, item)
    record(db, item, actor, profile, 'CONSULTATION_COMPLETED', previous=previous)
    db.commit()
    return {'message': 'Consultation terminée.', 'appointment_id': item.id, 'status': item.status,
            'consultation': consultation_view(item, consultation)}


def access_consultation(db, actor, appointment_id):
    item, _ = lock_appointment(db, appointment_id, actor)
    authorize(db, item, actor, admin_allowed=False)
    if item.status not in {'confirmed', 'in_progress'}:
        fail(409, 'CONSULTATION_NOT_ACCESSIBLE')
    availability.approved_profile(db, item.psychologist_id, lock=True)
    consultation = require_consultation(db, item)
    if item.consultation_mode != 'online':
        fail(400, 'CONSULTATION_IS_IN_PERSON')
    if consultation.status not in {'scheduled', 'in_progress'} or not consultation.meeting_room:
        fail(409, 'CONSULTATION_NOT_ACCESSIBLE')
    return meetings.meeting_access(item, consultation, actor)


def list_appointments(db, actor, *, scope='patient', status=None, patient_id=None, psychologist_id=None,
                      date_from=None, date_to=None, consultation_mode=None, page=1, page_size=20):
    query = select(Appointment)
    if scope == 'patient':
        query = query.where(Appointment.patient_id == actor.id)
    elif scope == 'psychologist':
        profile = professionals.own_profile(db, actor)
        query = query.where(Appointment.psychologist_id == profile.id)
    if status:
        query = query.where(Appointment.status == status)
    if patient_id:
        query = query.where(Appointment.patient_id == patient_id)
    if psychologist_id:
        query = query.where(Appointment.psychologist_id == psychologist_id)
    if consultation_mode:
        query = query.where(Appointment.consultation_mode == consultation_mode)
    query = filter_dates(query, Appointment.start_datetime, date_from, date_to)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = db.scalars(query.order_by(Appointment.start_datetime, Appointment.id)
                       .offset((page - 1) * page_size).limit(page_size))
    return {'items': [appointment_view(db, item, actor) for item in items],
            'total': total, 'page': page, 'page_size': page_size}


def filter_dates(query, column, date_from, date_to):
    try:
        first, last = instant(date_from) if date_from else None, instant(date_to) if date_to else None
    except ValueError:
        fail(422, 'INVALID_LOCAL_TIME')
    if first and last and first > last:
        fail(422, 'INVALID_DATE_RANGE')
    if first:
        query = query.where(column >= first)
    if last:
        query = query.where(column <= last)
    return query


def list_consultations(db, *, status=None, patient_id=None, psychologist_id=None,
                       date_from=None, date_to=None, page=1, page_size=20):
    query = select(Consultation, Appointment).join(Appointment, Appointment.id == Consultation.appointment_id)
    if status:
        query = query.where(Consultation.status == status)
    if patient_id:
        query = query.where(Appointment.patient_id == patient_id)
    if psychologist_id:
        query = query.where(Appointment.psychologist_id == psychologist_id)
    query = filter_dates(query, Appointment.start_datetime, date_from, date_to)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.execute(query.order_by(Appointment.start_datetime, Appointment.id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {'items': [{**consultation_view(item, consultation), 'patient_id': item.patient_id,
                       'psychologist_id': item.psychologist_id} for consultation, item in rows],
            'total': total, 'page': page, 'page_size': page_size}


@transactional
def start_consultation_resource(db, actor, appointment_id, consultation_type):
    item, profile = lock_appointment(db, appointment_id, actor)
    authorize(db, item, actor, admin_allowed=False)
    consultation = require_consultation(db, item)
    consultation_type = consultation_type or consultation.consultation_type
    if consultation_type == 'in_person' and item.consultation_mode != 'in_person':
        fail(400, 'CONSULTATION_TYPE_MISMATCH')
    if consultation_type in {'video', 'audio', 'phone'} and item.consultation_mode != 'online':
        fail(400, 'CONSULTATION_TYPE_MISMATCH')
    if item.status != 'confirmed' or consultation.status != 'scheduled':
        fail(409, 'INVALID_CONSULTATION_TRANSITION')
    consultation.consultation_type = consultation_type
    availability.approved_profile(db, profile.id, lock=True)
    meetings.access_window(item)
    if now() >= utc(item.end_datetime):
        fail(409, 'CONSULTATION_TIME_EXPIRED')
    consultation.status, consultation.started_at = 'in_progress', now()
    item.status = 'in_progress'
    record(db, item, actor, profile, 'CONSULTATION_STARTED', previous='confirmed')
    db.commit()
    return {'message': 'Consultation démarrée.', 'consultation': consultation_view(item, consultation)}


def participant_consultations(db, actor, *, status=None, page=1, page_size=20):
    query = select(Consultation, Appointment).join(
        Appointment, Appointment.id == Consultation.appointment_id)
    if actor.role.code == 'patient':
        query = query.where(Appointment.patient_id == actor.id)
    elif actor.role.code == 'psychologist':
        profile = professionals.own_profile(db, actor)
        query = query.where(Appointment.psychologist_id == profile.id)
    else:
        fail(403, 'INSUFFICIENT_PERMISSIONS')
    if status:
        query = query.where(Consultation.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.execute(query.order_by(Appointment.start_datetime, Appointment.id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {'items': [{**consultation_view(item, consultation),
                       'patient_id': item.patient_id,
                       'psychologist_id': item.psychologist_id}
                      for consultation, item in rows],
            'total': total, 'page': page, 'page_size': page_size}


def participant_consultation(db, actor, consultation_id):
    row = db.execute(select(Consultation, Appointment).join(
        Appointment, Appointment.id == Consultation.appointment_id).where(
            Consultation.id == consultation_id)).one_or_none()
    if not row:
        fail(404, 'CONSULTATION_NOT_FOUND')
    consultation, item = row
    authorize(db, item, actor, admin_allowed=False)
    return consultation_view(item, consultation)
