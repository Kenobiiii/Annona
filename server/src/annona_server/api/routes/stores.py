# SPDX-License-Identifier: AGPL-3.0-or-later
"""Using a store plugin from the app: connection (postal code, accepted notice), search, add one
product. Opt-in plugins (Mercadona) only answer after the person accepted their notice."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field

from ...stores import (
    NotConnected,
    NoticeRequired,
    StoreAccess,
    StoreNotFound,
    StoreUnavailable,
    get_connection,
    store_info,
)
from ..deps import HouseholdDep, SessionDep
from ..errors import APIError
from .products import ProductOut, _out

router = APIRouter(tags=["stores"])


class ConnectionOut(BaseModel):
    store_id: str
    name: str
    opt_in: bool
    notice: str | None  # what the person must accept (opt-in plugins)
    notice_accepted_at: datetime | None
    supports_postcode: bool
    postal_code: str | None
    ready: bool  # it can be searched


class ConnectionIn(BaseModel):
    postal_code: str | None = Field(default=None, max_length=10)
    accept_notice: bool = False


class FoundOut(BaseModel):
    store_sku: str
    name: str
    brand: str | None
    package_amount: str | None
    package_unit: str | None
    image_url: str | None
    product_id: int | None  # already in your catalogue


class AddIn(BaseModel):
    store_sku: str = Field(min_length=1, max_length=100)


def _access(request: Request) -> StoreAccess:
    return request.app.state.store_access


def _errors(error: Exception) -> APIError:
    if isinstance(error, StoreNotFound):
        return APIError(404, "not_found", str(error))
    if isinstance(error, NoticeRequired):
        return APIError(409, "notice_required", str(error))
    if isinstance(error, NotConnected):
        return APIError(409, "not_connected", str(error))
    if isinstance(error, StoreUnavailable):
        return APIError(502, "store_error", str(error)[:300])
    raise error


def _connection_out(session, household, store_id: str) -> ConnectionOut:
    info = store_info(store_id)
    c = get_connection(session, household, store_id)
    accepted = c.notice_accepted_at if c else None
    postal = c.postal_code if c else None
    ready = (not info.opt_in or accepted is not None) and (
        not info.supports_postcode or bool(postal)
    )
    return ConnectionOut(
        store_id=info.id,
        name=info.name,
        opt_in=info.opt_in,
        notice=info.notice,
        notice_accepted_at=accepted,
        supports_postcode=info.supports_postcode,
        postal_code=postal,
        ready=ready,
    )


@router.get("/stores/{store_id}/connection", response_model=ConnectionOut)
def get_store_connection(store_id: str, session: SessionDep, household: HouseholdDep):
    try:
        return _connection_out(session, household, store_id)
    except StoreNotFound as error:
        raise _errors(error) from error


@router.put("/stores/{store_id}/connection", response_model=ConnectionOut)
def put_store_connection(
    store_id: str,
    body: ConnectionIn,
    request: Request,
    session: SessionDep,
    household: HouseholdDep,
):
    """Accept the notice (opt-in plugins) and say where you shop. One request to the store
    resolves the postal code."""
    try:
        _access(request).connect(
            session,
            household,
            store_id,
            postal_code=body.postal_code,
            accept_notice=body.accept_notice,
        )
        return _connection_out(session, household, store_id)
    except (StoreNotFound, NoticeRequired, NotConnected, StoreUnavailable) as error:
        raise _errors(error) from error


@router.delete("/stores/{store_id}/connection", status_code=status.HTTP_204_NO_CONTENT)
def delete_store_connection(
    store_id: str, request: Request, session: SessionDep, household: HouseholdDep
) -> Response:
    """Withdraw the accepted notice and forget the postal code."""
    try:
        _access(request).disconnect(session, household, store_id)
    except StoreNotFound as error:
        raise _errors(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/stores/{store_id}/search", response_model=list[FoundOut])
def search_store(
    store_id: str, q: str, request: Request, session: SessionDep, household: HouseholdDep
):
    """Search the store for ONE thing you bought (a few results, cached for a day)."""
    try:
        found = _access(request).search(session, household, store_id, q)
    except (StoreNotFound, NoticeRequired, NotConnected, StoreUnavailable) as error:
        raise _errors(error) from error
    return [FoundOut(**f.__dict__) for f in found]


@router.post("/stores/{store_id}/products", response_model=ProductOut, status_code=201)
def add_store_product(
    store_id: str, body: AddIn, request: Request, session: SessionDep, household: HouseholdDep
):
    """Add one product of the store to your catalogue, with its price and, by barcode, Open
    Food Facts nutrition and allergens."""
    off = request.app.state.off_factory(session)
    try:
        product = _access(request).add_product(
            session, household, store_id, body.store_sku, off=off
        )
    except (StoreNotFound, NoticeRequired, NotConnected, StoreUnavailable) as error:
        raise _errors(error) from error
    finally:
        if off is not None and hasattr(off, "close"):
            off.close()
    return _out(session, product)
