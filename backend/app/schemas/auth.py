from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    mfa_code: str | None = Field(None, pattern=r"^\d{6}$")


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    mfa_required: bool = False
    mfa_enrollment_required: bool = False


class RefreshRequest(BaseModel):
    refresh_token: str = ""  # Optional — cookie-authenticated flow sends token via cookie


class MFAEnrollResponse(BaseModel):
    secret: str
    otpauth_uri: str


class MFAVerifyRequest(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")
