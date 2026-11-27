from pydantic import BaseModel, Field

from app.users.limits import MAX_EMAIL


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=MAX_EMAIL)
    password: str = Field(min_length=8, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
