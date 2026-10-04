"""Async SQLAlchemy unit of work with explicit commit and rollback semantics."""

from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class UnitOfWork:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions
        self.session: AsyncSession | None = None

    async def __aenter__(self) -> Self:
        self.session = self._sessions()
        await self.session.begin()
        return self

    async def __aexit__(self, exception_type: object, *_: object) -> None:
        if self.session is None:
            return
        try:
            if exception_type is None:
                await self.session.commit()
            else:
                await self.session.rollback()
        finally:
            await self.session.close()
            self.session = None
