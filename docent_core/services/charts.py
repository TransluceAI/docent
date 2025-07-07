from uuid import uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from docent_core._db_service.contexts import ViewContext
from docent_core._db_service.schemas.tables import SQLAChart
from docent_core._db_service.service import DBService


class ChartsService:
    def __init__(self, session: AsyncSession, service: DBService):
        self.session = session
        self.service = service

    async def get_charts(self, ctx: ViewContext) -> list[SQLAChart]:
        """Get all charts for a view."""
        result = await self.session.execute(
            select(SQLAChart).where(SQLAChart.view_id == ctx.view_id)
        )
        return list(result.scalars().all())

    async def create_chart(
        self,
        ctx: ViewContext,
        name: str | None = None,
        series_key: str | None = None,
        x_key: str | None = None,
        y_key: str | None = None,
        sql_query: str | None = None,
        chart_type: str = "bar",
    ) -> str:
        """Create a new chart and return its ID."""
        chart_id = str(uuid4())

        if ctx.user is None:
            raise PermissionError("User must be authenticated to create charts")

        # Generate default name if not provided
        if name is None:
            result = await self.session.execute(
                select(SQLAChart.name).where(SQLAChart.view_id == ctx.view_id)
            )
            existing_names = [row[0] for row in result.fetchall()]

            # Find the highest number among existing "Chart X" names
            max_num = 0
            for existing_name in existing_names:
                if existing_name.startswith("Chart "):
                    try:
                        num = int(existing_name[6:])  # Extract number after "Chart "
                        max_num = max(max_num, num)
                    except ValueError:
                        continue

            name = f"Chart {max_num + 1}"

        chart = SQLAChart(
            id=chart_id,
            view_id=ctx.view_id,
            name=name,
            series_key=series_key,
            x_key=x_key,
            y_key=y_key,
            sql_query=sql_query,
            chart_type=chart_type,
            created_by=ctx.user.id,
        )
        self.session.add(chart)

        return chart_id

    async def update_chart(
        self,
        ctx: ViewContext,
        chart_id: str,
        updates: dict[str, str | None],
    ) -> None:
        """Update an existing chart with the provided parameters.

        Only updates fields that are present in the updates dictionary.
        """
        result = await self.session.execute(select(SQLAChart).where(SQLAChart.id == chart_id))
        chart = result.scalar_one_or_none()

        if not chart:
            raise ValueError(f"Chart with ID {chart_id} not found")

        # Verify user has permission to update this chart
        if ctx.user is None or chart.created_by != ctx.user.id:
            raise PermissionError("You can only update charts you created")

        # Only update fields that are present in the updates dictionary
        if updates:
            await self.session.execute(
                update(SQLAChart).where(SQLAChart.id == chart_id).values(**updates)
            )

    async def delete_chart(self, ctx: ViewContext, chart_id: str):
        """Delete a chart.

        Only the creator of the chart can delete it.
        """
        result = await self.session.execute(select(SQLAChart).where(SQLAChart.id == chart_id))
        chart = result.scalar_one_or_none()

        if not chart:
            raise ValueError(f"Chart with ID {chart_id} not found")

        # Verify user has permission to delete this chart
        if ctx.user is None or chart.created_by != ctx.user.id:
            raise PermissionError("You can only delete charts you created")

        await self.session.execute(delete(SQLAChart).where(SQLAChart.id == chart_id))
