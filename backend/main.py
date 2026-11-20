"""Vyapari AI API with local SQLite storage."""
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from activity import initialize_activity, router as activity_router
from agencies import client_router as agency_access_router, initialize_agencies, router as agencies_router
from assistant import initialize_assistant_history, router as assistant_router
from auth import initialize_accounts, router as auth_router
from customers import initialize_customers, router as customers_router
from invitations import auth_router as invitation_auth_router, initialize_invitations, router as invitations_router
from inquiries import initialize_inquiries, router as inquiries_router
from inventory import initialize_inventory, router as inventory_router
from orders import initialize_orders, router as orders_router
from platform_admin import router as platform_router
from products import initialize_database, router as products_router
from purchasing import initialize_purchasing, router as purchasing_router
from reports import router as reports_router
from storefront import initialize_storefronts, router as storefront_router
from notifications import check_email_configuration
from verification import initialize_verification, router as verification_router
from website_requests import initialize_website_requests, platform_router as platform_requests_router, router as website_requests_router
from workspaces import router as workspaces_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    check_email_configuration()
    initialize_accounts()
    initialize_verification()
    initialize_database()
    initialize_inventory()
    initialize_purchasing()
    initialize_customers()
    initialize_orders()
    initialize_storefronts()
    initialize_inquiries()
    initialize_website_requests()
    initialize_assistant_history()
    initialize_activity()
    initialize_invitations()
    initialize_agencies()
    yield


app = FastAPI(title="Vyapari AI API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization", "X-Business-Id"],
)
app.include_router(products_router)
app.include_router(auth_router)
app.include_router(verification_router)
app.include_router(customers_router)
app.include_router(orders_router)
app.include_router(storefront_router)
app.include_router(assistant_router)
app.include_router(reports_router)
app.include_router(workspaces_router)
app.include_router(platform_router)
app.include_router(website_requests_router)
app.include_router(platform_requests_router)
app.include_router(activity_router)
app.include_router(invitations_router)
app.include_router(inquiries_router)
app.include_router(inventory_router)
app.include_router(purchasing_router)
app.include_router(invitation_auth_router)
app.include_router(agencies_router)
app.include_router(agency_access_router)


@app.exception_handler(RequestValidationError)
async def validate_request(request: Request, error: RequestValidationError):
    if request.url.path.startswith("/api/auth/"):
        details = [
            {key: item[key] for key in ("loc", "msg", "type")}
            for item in error.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": details})
    return await request_validation_exception_handler(request, error)


class Health(BaseModel):
    status: str
    service: str
    timestamp: str

@app.get("/health", response_model=Health)
def health():
    return Health(status="ok", service="vyapari-ai-api", timestamp=datetime.now(timezone.utc).isoformat())

@app.get("/")
def root():
    return {"message": "Vyapari AI starter backend", "docs": "/docs"}
