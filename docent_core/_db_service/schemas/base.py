from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

convention = {
    "ix": "ix_%(table_name)s__%(column_0_N_name)s",
    "uq": "uq_%(table_name)s__%(column_0_N_name)s",
    "ck": "ck_%(table_name)s__%(constraint_name)s",
    "fk": "fk_%(table_name)s__%(column_0_N_name)s__%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class SQLABase(DeclarativeBase):
    metadata = MetaData(naming_convention=convention)

    def dict(self):
        return {c.key: getattr(self, c.key) for c in self.__table__.columns}

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}({', '.join([f'{k}={v}' for k, v in self.dict().items()])})"
        )
