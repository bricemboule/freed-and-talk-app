from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
from app.core.config import get_settings
from app.core.database import Base
from app.modules.auth.models import entities  # noqa: F401
from app.modules.psychologists import models  # noqa: F401
from app.modules.appointments import models as appointment_models  # noqa: F401
from app.modules.communication import models as communication_models  # noqa: F401
from app.modules.content import models as content_models  # noqa: F401
from app.modules.reviews import models as review_models  # noqa: F401
from app.modules.administration import models as administration_models  # noqa: F401
from app.modules.payments import models as payment_models  # noqa: F401

config=context.config
config.set_main_option('sqlalchemy.url',get_settings().database_url.replace('%','%%'))
target_metadata=Base.metadata

def run_migrations_offline():
    context.configure(url=get_settings().database_url,target_metadata=target_metadata,literal_binds=True)
    with context.begin_transaction():context.run_migrations()

def run_migrations_online():
    engine=engine_from_config(config.get_section(config.config_ini_section),prefix='sqlalchemy.',poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection,target_metadata=target_metadata,compare_type=True)
        with context.begin_transaction():context.run_migrations()
    engine.dispose()

if context.is_offline_mode():run_migrations_offline()
else:run_migrations_online()
