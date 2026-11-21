# SPDX-License-Identifier: AGPL-3.0-or-later
"""The household, its members (profiles) and its kitchen."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from annona_core.domain import (
    ActivityLevel,
    Allergen,
    Diet,
    Equipment,
    Goal,
    HobType,
    Household,
    Sex,
    UserProfile,
)
from annona_core.domain.models import FoodPreference, ServingGroup
from annona_core.nutrition import ALLERGY_NOTICE, DailyTargets, daily_targets

from ...db.repositories import EquipmentRepository, HouseholdRepository, UserProfileRepository
from ..deps import HouseholdDep, SessionDep
from ..errors import APIError

router = APIRouter(tags=["household"])


class HouseholdIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    weekly_budget_cents: int = Field(ge=0)
    currency: str = "EUR"


@router.get("/household", response_model=Household)
def get_household(household: HouseholdDep) -> Household:
    return household


@router.put("/household", response_model=Household)
def put_household(body: HouseholdIn, session: SessionDep) -> Household:
    repo = HouseholdRepository(session)
    existing = next(iter(repo.list()), None)
    if existing is None:
        return repo.add(Household(**body.model_dump()))
    return repo.update(existing.model_copy(update=body.model_dump()))


class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    sex: Sex
    birth_date: date
    height_cm: Decimal
    weight_kg: Decimal
    activity: ActivityLevel
    goal: Goal = Goal.MAINTAIN
    diet: Diet = Diet.OMNIVORE
    allergies: list[Allergen] = Field(default_factory=list)
    allergies_confirmed: bool = False
    food_preferences: dict[str, FoodPreference] = Field(default_factory=dict)
    weekly_servings: dict[ServingGroup, int] = Field(default_factory=dict)


class ProfileOut(BaseModel):
    profile: UserProfile
    targets: DailyTargets
    allergy_notice: str | None


def _out(profile: UserProfile) -> ProfileOut:
    return ProfileOut(
        profile=profile,
        targets=daily_targets(profile, date.today()),
        allergy_notice=ALLERGY_NOTICE if profile.allergies else None,
    )


def _profile(session, household: Household, profile_id: int) -> UserProfile:
    profile = UserProfileRepository(session).get(profile_id)
    if profile is None or profile.household_id != household.id:
        raise APIError(404, "not_found", f"profile {profile_id} not found")
    return profile


@router.get("/profiles", response_model=list[ProfileOut])
def list_profiles(session: SessionDep, household: HouseholdDep) -> list[ProfileOut]:
    """Members with today's daily targets (informational, not medical advice)."""
    return [_out(p) for p in UserProfileRepository(session).list(household_id=household.id)]


@router.post("/profiles", response_model=ProfileOut, status_code=status.HTTP_201_CREATED)
def create_profile(body: ProfileIn, session: SessionDep, household: HouseholdDep) -> ProfileOut:
    profile = UserProfile(household_id=household.id, **body.model_dump())
    return _out(UserProfileRepository(session).add(profile))


@router.get("/profiles/{profile_id}", response_model=ProfileOut)
def get_profile(profile_id: int, session: SessionDep, household: HouseholdDep) -> ProfileOut:
    return _out(_profile(session, household, profile_id))


@router.put("/profiles/{profile_id}", response_model=ProfileOut)
def update_profile(
    profile_id: int, body: ProfileIn, session: SessionDep, household: HouseholdDep
) -> ProfileOut:
    current = _profile(session, household, profile_id)
    return _out(UserProfileRepository(session).update(current.model_copy(update=body.model_dump())))


@router.delete("/profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_profile(profile_id: int, session: SessionDep, household: HouseholdDep) -> None:
    _profile(session, household, profile_id)
    UserProfileRepository(session).delete(profile_id)


class EquipmentIn(BaseModel):
    hob_type: HobType = HobType.CERAMIC
    burners: int = Field(default=2, ge=0, le=12)
    power_levels: int | None = Field(default=None, ge=1, le=20)
    oven: bool = False
    microwave: bool = False
    air_fryer: bool = False
    calibration_level: int | None = None
    calibration_boil_1l_minutes: Decimal | None = None


@router.get("/equipment", response_model=Equipment | None)
def get_equipment(session: SessionDep, household: HouseholdDep) -> Equipment | None:
    return next(iter(EquipmentRepository(session).list(household_id=household.id)), None)


@router.put("/equipment", response_model=Equipment)
def put_equipment(body: EquipmentIn, session: SessionDep, household: HouseholdDep) -> Equipment:
    repo = EquipmentRepository(session)
    current = next(iter(repo.list(household_id=household.id)), None)
    equipment = Equipment(household_id=household.id, **body.model_dump())
    if current is None:
        return repo.add(equipment)
    return repo.update(equipment.model_copy(update={"id": current.id}))
