"""Les 27 routes du module 3, avec permissions explicites et services partagés."""
from datetime import date as CalendarDate
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.rate_limit import rate_limit
from app.modules.auth.api.routes import current_user, require_role
from app.modules.auth.models.entities import User
from app.modules.psychologists.schemas import ConsultationMode
from . import availability, services
from .schemas import (AdminAppointmentFilters, AppointmentFilters, AvailabilityBody, BookingBody,
                      CancellationBody, ConsultationFilters, ConsultationStart, RescheduleBody,
                      UnavailabilityBody)

router = APIRouter()
psychologists = APIRouter(prefix='/api/psychologists', tags=['Planning psychologue'])
appointments = APIRouter(prefix='/api/appointments', tags=['Rendez-vous et consultations'])
administration = APIRouter(prefix='/api/admin', tags=['Administration des rendez-vous'])
consultations = APIRouter(prefix='/api/consultations', tags=['Consultations'])
Db = Annotated[Session, Depends(get_db)]
Patient = Annotated[User, Depends(require_role('patient'))]
Psychologist = Annotated[User, Depends(require_role('psychologist'))]
Administrator = Annotated[User, Depends(require_role('admin'))]
Participant = Annotated[User, Depends(current_user)]


@psychologists.get('/me/availability')
def get_availability(user: Psychologist, db: Db):
    return availability.list_availability(db, user)


@psychologists.post('/me/availability', status_code=201)
def create_availability(body: AvailabilityBody, user: Psychologist, db: Db):
    return availability.save_availability(db, user, body)


@psychologists.put('/me/availability/{availability_id}')
def update_availability(availability_id: str, body: AvailabilityBody, user: Psychologist, db: Db):
    return availability.save_availability(db, user, body, availability_id)


@psychologists.delete('/me/availability/{availability_id}')
def remove_availability(availability_id: str, user: Psychologist, db: Db):
    return availability.delete_availability(db, user, availability_id)


@psychologists.get('/me/unavailability')
def get_unavailability(user: Psychologist, db: Db):
    return availability.list_unavailability(db, user)


@psychologists.post('/me/unavailability', status_code=201)
def create_unavailability(body: UnavailabilityBody, user: Psychologist, db: Db):
    return availability.save_unavailability(db, user, body)


@psychologists.put('/me/unavailability/{unavailability_id}')
def update_unavailability(unavailability_id: str, body: UnavailabilityBody, user: Psychologist, db: Db):
    return availability.save_unavailability(db, user, body, unavailability_id)


@psychologists.delete('/me/unavailability/{unavailability_id}')
def remove_unavailability(unavailability_id: str, user: Psychologist, db: Db):
    return availability.delete_unavailability(db, user, unavailability_id)


@psychologists.get('/{psychologist_id}/available-slots')
def get_available_slots(psychologist_id: str, date: CalendarDate, db: Db,
                        consultation_mode: ConsultationMode = 'online',
                        duration: int | None = Query(default=None, ge=5, le=240)):
    return availability.available_slots(db, psychologist_id, date, consultation_mode, duration)


@psychologists.get('/{psychologist_id}/availability')
def get_public_availability(psychologist_id: str, db: Db):
    return availability.public_availability(db, psychologist_id)


@appointments.post('', status_code=201)
def create_appointment(body: BookingBody, user: Patient, db: Db, request: Request):
    rate_limit(request, 'book-appointment', user.id, 20, 600)
    return services.book(db, user, body)


@appointments.get('')
def list_my_appointments(user: Patient, db: Db, filters: Annotated[AppointmentFilters, Query()]):
    return services.list_appointments(db, user, **filters.model_dump())


@appointments.get('/me')
def get_my_appointments(user: Patient, db: Db, filters: Annotated[AppointmentFilters, Query()]):
    return services.list_appointments(db, user, **filters.model_dump())


@appointments.get('/{appointment_id}')
def get_appointment(appointment_id: str, user: Participant, db: Db):
    return services.details(db, user, appointment_id)


@appointments.put('/{appointment_id}/reschedule')
def reschedule_appointment(appointment_id: str, body: RescheduleBody, user: Patient, db: Db, request: Request):
    rate_limit(request, 'reschedule-appointment', user.id, 20, 600)
    return services.reschedule(db, user, appointment_id, body)


@appointments.patch('/{appointment_id}')
def patch_appointment(appointment_id: str, body: RescheduleBody, user: Patient, db: Db, request: Request):
    rate_limit(request, 'reschedule-appointment', user.id, 20, 600)
    return services.reschedule(db, user, appointment_id, body)


@appointments.post('/{appointment_id}/cancel')
def cancel_appointment(appointment_id: str, body: CancellationBody, user: Patient, db: Db):
    return services.cancel(db, user, appointment_id, body.reason, patient_action=True)


@psychologists.get('/me/appointments')
def get_psychologist_appointments(user: Psychologist, db: Db, filters: Annotated[AppointmentFilters, Query()]):
    return services.list_appointments(db, user, scope='psychologist', **filters.model_dump())


@psychologists.post('/me/appointments/{appointment_id}/accept')
def accept_appointment(appointment_id: str, user: Psychologist, db: Db):
    return services.accept(db, user, appointment_id)


@appointments.post('/{appointment_id}/accept')
def accept_appointment_alias(appointment_id: str, user: Psychologist, db: Db):
    return services.accept(db, user, appointment_id)


@psychologists.post('/me/appointments/{appointment_id}/reject')
def reject_appointment(appointment_id: str, body: CancellationBody, user: Psychologist, db: Db):
    return services.cancel(db, user, appointment_id, body.reason, reject=True)


@appointments.post('/{appointment_id}/reject')
def reject_appointment_alias(appointment_id: str, body: CancellationBody, user: Psychologist, db: Db):
    return services.cancel(db, user, appointment_id, body.reason, reject=True)


@appointments.post('/{appointment_id}/complete')
def complete_appointment_alias(appointment_id: str, user: Psychologist, db: Db):
    return services.end_consultation(db, user, appointment_id, complete=True)


@psychologists.post('/me/appointments/{appointment_id}/complete')
def complete_appointment(appointment_id: str, user: Psychologist, db: Db):
    return services.end_consultation(db, user, appointment_id, complete=True)


@psychologists.post('/me/appointments/{appointment_id}/cancel')
def cancel_psychologist_appointment(appointment_id: str, body: CancellationBody, user: Psychologist, db: Db):
    return services.cancel(db, user, appointment_id, body.reason)


@appointments.get('/{appointment_id}/consultation')
def get_consultation(appointment_id: str, user: Participant, db: Db):
    return services.get_consultation(db, user, appointment_id)


@consultations.post('', status_code=201)
def start_consultation_resource(body: ConsultationStart, user: Participant, db: Db):
    return services.start_consultation_resource(
        db, user, body.appointment_id, body.consultation_type)


@consultations.get('')
def get_my_consultations(user: Participant, db: Db, filters: Annotated[ConsultationFilters, Query()]):
    return services.participant_consultations(db, user, status=filters.status,
        page=filters.page, page_size=filters.page_size)


@consultations.get('/{consultation_id}')
def get_consultation_resource(consultation_id: str, user: Participant, db: Db):
    return services.participant_consultation(db, user, consultation_id)


@appointments.post('/{appointment_id}/consultation/start')
def start_consultation(appointment_id: str, user: Participant, db: Db):
    return services.start_consultation(db, user, appointment_id)


@appointments.post('/{appointment_id}/consultation/end')
def end_consultation(appointment_id: str, user: Participant, db: Db):
    return services.end_consultation(db, user, appointment_id)


@appointments.get('/{appointment_id}/consultation/access')
def get_consultation_access(appointment_id: str, user: Participant, db: Db, response: Response):
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['Pragma'] = 'no-cache'
    return services.access_consultation(db, user, appointment_id)


@administration.get('/appointments')
def list_admin_appointments(user: Administrator, db: Db, filters: Annotated[AdminAppointmentFilters, Query()]):
    return services.list_appointments(db, user, scope='admin', **filters.model_dump())


@administration.get('/appointments/{appointment_id}')
def get_admin_appointment(appointment_id: str, user: Administrator, db: Db):
    return services.details(db, user, appointment_id)


@administration.post('/appointments/{appointment_id}/cancel')
def cancel_admin_appointment(appointment_id: str, body: CancellationBody, user: Administrator, db: Db):
    return services.cancel(db, user, appointment_id, body.reason)


@administration.get('/consultations')
def list_admin_consultations(user: Administrator, db: Db, filters: Annotated[ConsultationFilters, Query()]):
    return services.list_consultations(db, **filters.model_dump())


router.include_router(psychologists)
router.include_router(appointments)
router.include_router(administration)
router.include_router(consultations)
