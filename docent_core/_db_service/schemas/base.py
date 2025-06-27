from sqlalchemy.orm import DeclarativeBase


class SQLABase(DeclarativeBase):
    def dict(self):
        return {c.key: getattr(self, c.key) for c in self.__table__.columns}

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}({', '.join([f'{k}={v}' for k, v in self.dict().items()])})"
        )
