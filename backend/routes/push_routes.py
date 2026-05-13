"""Push token registration routes (June 2025).

Frontend registers the device's Expo push token on app launch (after
auth), and unregisters on logout. The backend uses these tokens to send
push notifications via expo-server-sdk when admin Notification Config
has push enabled for the event.
"""
from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field


class PushTokenIn(BaseModel):
    user_id: str
    token: str = Field(..., description="ExponentPushToken[...]")
    platform: str | None = Field(None, description="ios | android | web")


class PushTokenDeleteIn(BaseModel):
    user_id: str
    token: str


def make_push_router(db):
    r = APIRouter()

    @r.post("/push/register")
    async def register_push(body: PushTokenIn = Body(...)):
        from push_provider import register_push_token
        try:
            return await register_push_token(
                db, body.user_id, token=body.token, platform=body.platform
            )
        except ValueError as ve:
            raise HTTPException(400, str(ve))

    @r.post("/push/unregister")
    async def unregister_push(body: PushTokenDeleteIn = Body(...)):
        from push_provider import unregister_push_token
        return await unregister_push_token(db, body.user_id, body.token)

    return r
