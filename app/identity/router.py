from fastapi import APIRouter

from app.identity.schemas_auth import LoginIn, TokenOut
from app.identity.service import login as login_svc
from app.shared.deps import DbSession
from app.shared.errors import OPENAPI_ERROR_RESPONSES

router = APIRouter(tags=["auth"], responses=OPENAPI_ERROR_RESPONSES)


@router.post("/v1/auth/login", response_model=TokenOut)
def login(body: LoginIn, db: DbSession) -> TokenOut:
    token = login_svc(db, email=body.email, password=body.password)
    return TokenOut(access_token=token)
