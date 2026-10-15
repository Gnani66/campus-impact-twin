from __future__ import annotations

from typing import Any

from app.repositories.supabase import get_supabase


class CampusRepository:
    def __init__(self) -> None:
        self.client = get_supabase()

    def get_buildings(self) -> list[dict[str, Any]]:
        response = (
            self.client
            .table("buildings")
            .select("*")
            .order("name")
            .execute()
        )

        return response.data

    def get_zones(
        self,
        building_id: str | None = None,
    ) -> list[dict[str, Any]]:
        query = (
            self.client
            .table("zones")
            .select("*")
            .order("name")
        )

        if building_id:
            query = query.eq(
                "building_id",
                building_id,
            )

        response = query.execute()

        return response.data

    def get_open_incidents(
        self,
    ) -> list[dict[str, Any]]:
        response = (
            self.client
            .table("incidents")
            .select("*")
            .in_(
                "status",
                ["open", "under_review"],
            )
            .order(
                "impact_score",
                desc=True,
            )
            .execute()
        )

        return response.data