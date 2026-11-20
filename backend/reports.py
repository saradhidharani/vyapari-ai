from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from auth import ManagerAccount
from database import get_db


router = APIRouter(prefix="/api/reports", tags=["Reports"])
IST = timezone(timedelta(hours=5, minutes=30), "IST")
DAY = timedelta(days=1)
SalesPeriod = Literal["today", "yesterday", "this week", "last week", "last 7 days", "this month", "last month"]


class SalesDay(BaseModel):
    date: date
    payments_paise: int = 0
    refunds_paise: int = 0
    net_paise: int = 0


class SalesChannel(BaseModel):
    kind: Literal["all", "direct", "website"]
    website_id: int | None = None
    label: str


class EnquiryConversion(BaseModel):
    received: int
    linked: int
    converted: int


class SalesReport(BaseModel):
    start_date: date | None
    end_date: date | None
    payments_paise: int
    refunds_paise: int
    net_paise: int
    payment_count: int
    refund_count: int
    daily: list[SalesDay]
    channel: SalesChannel
    enquiries: EnquiryConversion | None = None


def sales_period(period: SalesPeriod, today: date):
    tomorrow = today + DAY
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    return {
        "today": (today, tomorrow),
        "yesterday": (today - DAY, today),
        "this week": (week_start, tomorrow),
        "last week": (week_start - timedelta(days=7), week_start),
        "last 7 days": (today - timedelta(days=6), tomorrow),
        "this month": (month_start, tomorrow),
        "last month": ((month_start - DAY).replace(day=1), month_start),
    }[period]


def utc_midnight(day: date):
    return datetime.combine(day, time.min, IST).astimezone(timezone.utc).isoformat()


def calculate_sales(
    db, business_id: int, period: SalesPeriod | None = None, *,
    today: date | None = None, channel: SalesChannel | None = None,
):
    channel = channel or SalesChannel(kind="all", label="All channels")
    first = last = start = end = None
    daily = {}
    if period:
        first, after_last = sales_period(period, today or datetime.now(IST).date())
        last = after_last - DAY
        start, end = utc_midnight(first), utc_midnight(after_last)
        for offset in range((after_last - first).days):
            day = first + timedelta(days=offset)
            daily[day] = SalesDay(date=day)

    rows = db.execute("""
        SELECT amount_paise, paid_at, refunded_at FROM orders
        WHERE business_id = ? AND paid_at IS NOT NULL
          AND (? != 'direct' OR source_website_id IS NULL)
          AND (? IS NULL OR source_website_id = ?)
          AND (? IS NULL OR (paid_at >= ? AND paid_at < ?)
                         OR (refunded_at >= ? AND refunded_at < ?))
    """, (business_id, channel.kind, channel.website_id, channel.website_id,
          start, start, end, start, end))

    payments = refunds = payment_count = refund_count = 0
    for row in rows:
        paid_at, refunded_at, amount = row["paid_at"], row["refunded_at"], row["amount_paise"]
        if start is None or start <= paid_at < end:
            payments += amount
            payment_count += 1
            if daily:
                day = daily[datetime.fromisoformat(paid_at).astimezone(IST).date()]
                day.payments_paise += amount
                day.net_paise += amount
        if refunded_at and (start is None or start <= refunded_at < end):
            refunds += amount
            refund_count += 1
            if daily:
                day = daily[datetime.fromisoformat(refunded_at).astimezone(IST).date()]
                day.refunds_paise += amount
                day.net_paise -= amount

    return SalesReport(
        start_date=first,
        end_date=last,
        payments_paise=payments,
        refunds_paise=refunds,
        net_paise=payments - refunds,
        payment_count=payment_count,
        refund_count=refund_count,
        daily=list(daily.values()),
        channel=channel,
    )


def enquiry_conversion(db, business_id, report):
    row = db.execute("""
        SELECT COUNT(*) AS received, COUNT(i.customer_id) AS linked, COUNT(o.id) AS converted
        FROM website_inquiries AS i
        LEFT JOIN orders AS o ON o.business_id = i.business_id AND o.source_inquiry_id = i.id
        WHERE i.business_id = ? AND i.created_at >= ? AND i.created_at < ?
          AND (? IS NULL OR i.website_id = ?)
    """, (business_id, utc_midnight(report.start_date), utc_midnight(report.end_date + DAY),
          report.channel.website_id, report.channel.website_id)).fetchone()
    return EnquiryConversion(**dict(row))


@router.get("/sales", response_model=SalesReport)
def get_sales_report(
    account: ManagerAccount,
    period: SalesPeriod = "last 7 days",
    website_id: Annotated[int | None, Query(gt=0, le=2**63 - 1)] = None,
    direct: bool = False,
):
    if direct and website_id is not None:
        raise HTTPException(status_code=422, detail="Choose either direct orders or a website")
    with get_db() as db:
        db.execute("BEGIN")
        channel = SalesChannel(kind="direct", label="Direct orders") if direct else None
        if website_id is not None:
            site = db.execute("""
                SELECT label FROM storefront_websites WHERE id = ? AND business_id = ?
            """, (website_id, account.business_id)).fetchone()
            if site is None:
                raise HTTPException(status_code=404, detail="Website not found")
            channel = SalesChannel(kind="website", website_id=website_id, label=site["label"])
        report = calculate_sales(db, account.business_id, period, channel=channel)
        if not direct:
            report.enquiries = enquiry_conversion(db, account.business_id, report)
        return report
