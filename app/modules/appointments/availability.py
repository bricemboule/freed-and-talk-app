"""Horaires, exceptions et calcul commun des créneaux réservables."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.auth.services.logic import fail, now, utc
from app.modules.psychologists import services as professionals
from .models import ACTIVE_STATUSES, Appointment, Availability, Unavailability
from .schemas import AvailabilityBody, UnavailabilityBody, local_instant


def approved_profile(db: Session, profile_id: str, *, lock=False):
    profile = professionals.profile_by_id(db, profile_id, lock=lock)
    # Le statut vient de la lecture verrouillée, pas d'un ancien snapshot MySQL.
    from app.modules.auth.models.entities import Role, User
    query = select(User.is_active, User.email_verified, Role.is_active, Role.code).join(
        Role, Role.id == User.role_id).where(User.id == profile.user_id)
    user = db.execute(query.with_for_update() if lock else query).one()
    if profile.verification_status != 'approved' or not all(user[:3]) or user[3] != 'psychologist':
        fail(403, 'PSYCHOLOGIST_NOT_BOOKABLE')
    return profile


def availability_view(item: Availability):
    return {'id': item.id, 'day_of_week': item.day_of_week,
            'start_time': item.start_time.strftime('%H:%M'), 'end_time': item.end_time.strftime('%H:%M'),
            'consultation_mode': item.consultation_mode, 'location': item.location, 'is_active': item.is_active}


def own_item(db, model, profile, item_id):
    item = db.scalar(select(model).where(model.id == item_id, model.psychologist_id == profile.id).with_for_update())
    if not item:
        fail(404, 'SCHEDULE_NOT_FOUND')
    return item


def list_availability(db, user):
    profile = professionals.own_profile(db, user)
    items = db.scalars(select(Availability).where(Availability.psychologist_id == profile.id)
                       .order_by(Availability.day_of_week, Availability.start_time))
    return {'timezone': get_settings().appointment_timezone, 'items': [availability_view(item) for item in items]}


def public_availability(db, profile_id):
    profile = approved_profile(db, profile_id)
    items = db.scalars(select(Availability).where(
        Availability.psychologist_id == profile.id, Availability.is_active.is_(True))
        .order_by(Availability.day_of_week, Availability.start_time))
    # Do not publish exact office addresses from the schedule. The booked
    # appointment reveals its location to participants after confirmation.
    return {'psychologist_id': profile.id, 'timezone': get_settings().appointment_timezone,
            'items': [{'id': item.id, 'day_of_week': item.day_of_week,
                       'start_time': item.start_time.strftime('%H:%M'),
                       'end_time': item.end_time.strftime('%H:%M'),
                       'consultation_mode': item.consultation_mode}
                      for item in items]}


def future_appointments(db, profile):
    return list(db.scalars(select(Appointment).where(Appointment.psychologist_id == profile.id,
                           Appointment.status.in_(ACTIVE_STATUSES), Appointment.end_datetime > now()).with_for_update()))


def save_availability(db, user, body: AvailabilityBody, item_id=None):
    profile = professionals.own_profile(db, user, lock=True)
    item = own_item(db, Availability, profile, item_id) if item_id else None
    if body.is_active:
        approved_profile(db, profile.id, lock=True)
        if body.consultation_mode not in profile.consultation_modes:
            fail(400, 'CONSULTATION_MODE_NOT_ALLOWED')
        overlap = select(Availability.id).where(
            Availability.psychologist_id == profile.id, Availability.is_active.is_(True),
            Availability.day_of_week == body.day_of_week,
            Availability.start_time < body.end_time, Availability.end_time > body.start_time)
        if item:
            overlap = overlap.where(Availability.id != item.id)
        if db.scalar(overlap.with_for_update()):
            fail(409, 'AVAILABILITY_OVERLAP')
    if item:
        if any(appointment.availability_id == item.id for appointment in future_appointments(db, profile)):
            fail(409, 'AVAILABILITY_HAS_APPOINTMENTS')
        for key, value in body.model_dump().items():
            setattr(item, key, value)
    else:
        item = Availability(psychologist_id=profile.id, **body.model_dump())
        db.add(item)
    db.commit()
    return {'message': 'Disponibilité enregistrée.', 'availability': availability_view(item)}


def delete_availability(db, user, item_id):
    profile = professionals.own_profile(db, user, lock=True)
    item = own_item(db, Availability, profile, item_id)
    if any(appointment.availability_id == item.id for appointment in future_appointments(db, profile)):
        fail(409, 'AVAILABILITY_HAS_APPOINTMENTS')
    db.delete(item)
    db.commit()
    return {'message': 'Disponibilité supprimée.'}


def unavailability_view(item):
    return {'id': item.id, 'start_datetime': utc(item.start_datetime), 'end_datetime': utc(item.end_datetime),
            'reason': item.reason, 'is_active': item.is_active}


def list_unavailability(db, user):
    profile = professionals.own_profile(db, user)
    items = db.scalars(select(Unavailability).where(Unavailability.psychologist_id == profile.id)
                       .order_by(Unavailability.start_datetime))
    return {'items': [unavailability_view(item) for item in items]}


def save_unavailability(db, user, body: UnavailabilityBody, item_id=None):
    profile = professionals.own_profile(db, user, lock=True)
    item = own_item(db, Unavailability, profile, item_id) if item_id else None
    if body.is_active:
        query = select(Unavailability.id).where(Unavailability.psychologist_id == profile.id,
                    Unavailability.is_active.is_(True), Unavailability.start_datetime < body.end_datetime,
                    Unavailability.end_datetime > body.start_datetime)
        if item:
            query = query.where(Unavailability.id != item.id)
        if db.scalar(query.with_for_update()):
            fail(409, 'UNAVAILABILITY_OVERLAP')
        if any(utc(appointment.start_datetime) < body.end_datetime and utc(appointment.end_datetime) > body.start_datetime
               for appointment in future_appointments(db, profile)):
            fail(409, 'UNAVAILABILITY_HAS_APPOINTMENTS')
    if item:
        for key, value in body.model_dump().items():
            setattr(item, key, value)
    else:
        item = Unavailability(psychologist_id=profile.id, **body.model_dump())
        db.add(item)
    db.commit()
    return {'message': "Période d'indisponibilité enregistrée.", 'unavailability': unavailability_view(item)}


def delete_unavailability(db, user, item_id):
    profile = professionals.own_profile(db, user, lock=True)
    db.delete(own_item(db, Unavailability, profile, item_id))
    db.commit()
    return {'message': "Période d'indisponibilité supprimée."}


def duration_minutes(value=None):
    settings = get_settings()
    duration = value if value is not None else settings.consultation_default_minutes
    if duration not in {int(item.strip()) for item in settings.consultation_allowed_minutes.split(',')}:
        fail(422, 'CONSULTATION_DURATION_NOT_ALLOWED')
    return duration


def ranges(db, profile, day: date, mode: str, duration: int, *, lock=False):
    """Générer les plages UTC sur une grille locale, sans ambiguïté DST."""
    if mode not in profile.consultation_modes:
        fail(400, 'CONSULTATION_MODE_NOT_ALLOWED')
    settings = get_settings()
    current_date = now().astimezone(ZoneInfo(settings.appointment_timezone)).date()
    if day > current_date + timedelta(days=settings.appointment_max_advance_days):
        fail(422, 'DATE_OUTSIDE_BOOKING_HORIZON')
    if day < current_date:
        return []
    query = select(Availability).where(Availability.psychologist_id == profile.id,
                Availability.day_of_week == (day.weekday() + 1) % 7,
                Availability.consultation_mode == mode, Availability.is_active.is_(True))
    schedule = db.scalars(query.with_for_update() if lock else query)
    result = []
    for window in schedule:
        start = datetime.combine(day, window.start_time)
        end = datetime.combine(day, window.end_time)
        while start + timedelta(minutes=duration) <= end:
            try:
                first = local_instant(start)
                last = local_instant(start + timedelta(minutes=duration))
                if last - first == timedelta(minutes=duration) and first > now():
                    result.append((first, last, window))
            except ValueError:
                pass
            start += timedelta(minutes=settings.appointment_slot_step_minutes)
    return sorted(result, key=lambda item: item[0])


def unavailable_intervals(db, profile, *, lock=False):
    query = select(Unavailability).where(Unavailability.psychologist_id == profile.id,
                                         Unavailability.is_active.is_(True))
    return list(db.scalars(query.with_for_update() if lock else query))


def overlaps(start, end, other_start, other_end):
    return start < utc(other_end) and end > utc(other_start)


def find_window(db, profile, start, end, mode, *, lock=False):
    day = start.astimezone(ZoneInfo(get_settings().appointment_timezone)).date()
    duration = int((end - start).total_seconds() // 60)
    window = next((item for first, last, item in ranges(db, profile, day, mode, duration, lock=lock)
                   if first == start and last == end), None)
    if not window:
        fail(400, 'SLOT_NOT_IN_AVAILABILITY')
    if any(overlaps(start, end, item.start_datetime, item.end_datetime)
           for item in unavailable_intervals(db, profile, lock=lock)):
        fail(409, 'SLOT_UNAVAILABLE')
    return window


def available_slots(db, profile_id, day, mode, duration=None):
    profile = approved_profile(db, profile_id)
    minutes = duration_minutes(duration)
    periods = unavailable_intervals(db, profile)
    appointments = list(db.scalars(select(Appointment).where(Appointment.psychologist_id == profile.id,
                                    Appointment.status.in_(ACTIVE_STATUSES))))
    slots = []
    for start, end, _ in ranges(db, profile, day, mode, minutes):
        if any(overlaps(start, end, item.start_datetime, item.end_datetime) for item in [*periods, *appointments]):
            continue
        slots.append({'start_datetime': start, 'end_datetime': end, 'available': True})
    return {'psychologist_id': profile.id, 'date': day, 'consultation_mode': mode,
            'duration': minutes, 'timezone': get_settings().appointment_timezone, 'slots': slots}
