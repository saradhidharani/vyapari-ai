import re
import unicodedata
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field, StringConstraints

from assistant_languages import (
    BUSINESS_LANGUAGES,
    SALES_LANGUAGES,
    localized_business_query,
    localized_sales_period,
    question_language,
)
from auth import ManagerAccount
from database import get_db
from orders import ORDER_COLUMNS, serialize_order
from reports import calculate_sales


router = APIRouter(prefix="/api/assistant", tags=["Assistant"])
SALES_PERIOD = re.compile(
    r"(?:(?:show (?:me )?(?:my )?|what (?:are|were) (?:my )?|how (?:were|are) (?:my )?)?"
    r"(?:net )?sales(?: summary)?(?: (?:for|in))?) "
    r"(today|yesterday|this week|last week|last 7 days|this month|last month)"
)


class AssistantQuestion(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True)] = Field(min_length=1, max_length=300)
    request_id: UUID = Field(default_factory=uuid4)


class AssistantReply(BaseModel):
    answer: str
    language: Literal["en", "hi", "te"]


class AssistantExchange(AssistantReply):
    id: int
    question: str
    created_at: str


class AssistantHistory(BaseModel):
    exchanges: list[AssistantExchange]
    older_before: int | None


HISTORY_PAGE_SIZE = 30
EXCHANGE_COLUMNS = "id, question, answer, language, created_at"


def initialize_assistant_history():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS assistant_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_id INTEGER NOT NULL REFERENCES businesses(id),
                request_id TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                language TEXT NOT NULL CHECK(language IN ('en', 'hi', 'te')),
                created_at TEXT NOT NULL,
                UNIQUE (business_id, request_id)
            )
        """)
        db.execute("""
            CREATE INDEX IF NOT EXISTS assistant_history_business_id
            ON assistant_history (business_id, id)
        """)


@router.get("/history", response_model=AssistantHistory)
def list_history(account: ManagerAccount, before: Annotated[int | None, Query(gt=0, le=2**63 - 1)] = None):
    with get_db() as db:
        rows = db.execute(f"""
            SELECT {EXCHANGE_COLUMNS} FROM assistant_history
            WHERE business_id = ? AND (? IS NULL OR id < ?)
            ORDER BY id DESC LIMIT ?
        """, (account.business_id, before, before, HISTORY_PAGE_SIZE + 1)).fetchall()
    page = rows[:HISTORY_PAGE_SIZE]
    return {
        "exchanges": [dict(row) for row in reversed(page)],
        "older_before": page[-1]["id"] if len(rows) > HISTORY_PAGE_SIZE else None,
    }


@router.delete("/history", status_code=204)
def clear_history(account: ManagerAccount):
    with get_db() as db:
        db.execute("DELETE FROM assistant_history WHERE business_id = ?", (account.business_id,))
    return Response(status_code=204)


def find_exchange(db, business_id, request_id):
    return db.execute(f"""
        SELECT {EXCHANGE_COLUMNS} FROM assistant_history WHERE business_id = ? AND request_id = ?
    """, (business_id, request_id)).fetchone()


def existing_exchange(row, question):
    if row["question"] != question:
        raise HTTPException(status_code=409, detail="This request ID already belongs to another question")
    return AssistantExchange(**dict(row))


def money(paise: int):
    rupees, remainder = divmod(abs(paise), 100)
    sign = "-" if paise < 0 else ""
    return f"{sign}₹{rupees:,}.{remainder:02d}"


def order_line(order, labels):
    status = labels.get("statuses", {}).get(order["status"], order["status"])
    prefix = labels.get("order_label", "")
    return f"{prefix}#ORD-{order['id']} · {status} · {money(order['amount_paise'])}"


def sales_summary(db, business_id, period=None, language=None):
    translation = SALES_LANGUAGES.get(language)
    report = calculate_sales(db, business_id, period)
    heading = translation["all_time"] if translation else "All-time net sales"
    if period:
        first, last = report.start_date, report.end_date
        if translation:
            dates = first.strftime("%d-%m-%Y")
            if last != first:
                dates += f" – {last:%d-%m-%Y}"
            heading = f"{translation['net_sales']} ({dates}, IST)"
        else:
            dates = first.strftime("%d %b %Y")
            if last != first:
                dates += f" to {last:%d %b %Y}"
            heading = f"Net sales {period} ({dates}, IST)"

    payments_label = translation["payments"] if translation else "Payments"
    refunds_label = translation["refunds"] if translation else "Refunds"
    return (
        f"{heading}: {money(report.net_paise)}.\n"
        f"{payments_label}: {money(report.payments_paise)} ({report.payment_count}) · "
        f"{refunds_label}: {money(report.refunds_paise)} ({report.refund_count})."
    )


@router.post("/ask", response_model=AssistantExchange)
def ask(body: AssistantQuestion, account: ManagerAccount):
    query = " ".join(unicodedata.normalize("NFC", body.question.casefold()).rstrip("?.!।").split())
    language = "en"
    if not query.startswith(("stock for ", "stock of ")):
        language = question_language(query) or "en"
    business_id = account.business_id
    request_id = str(body.request_id)
    with get_db() as db:
        db.execute("PRAGMA query_only = ON")
        previous = find_exchange(db, business_id, request_id)
        if previous:
            return existing_exchange(previous, body.question)
        answer = answer_question(query, business_id, db, language)

    with get_db() as db:
        row = db.execute(f"""
            INSERT INTO assistant_history (business_id, request_id, question, answer, language, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (business_id, request_id) DO NOTHING
            RETURNING {EXCHANGE_COLUMNS}
        """, (business_id, request_id, body.question, answer, language,
              datetime.now(timezone.utc).isoformat())).fetchone()
        if row is not None:
            return AssistantExchange(**dict(row))
        return existing_exchange(find_exchange(db, business_id, request_id), body.question)


def answer_question(query, business_id, db, language):
    if query in {"sales summary", "net sales", "how are my sales doing", "what are my net sales"}:
        return sales_summary(db, business_id)

    period_match = SALES_PERIOD.fullmatch(query)
    if period_match:
        return sales_summary(db, business_id, period_match.group(1))

    labels = {}
    if language != "en":
        period = localized_sales_period(query, language)
        if period:
            return sales_summary(db, business_id, None if period == "all" else period, language)
        localized = localized_business_query(query, language)
        if localized:
            query = localized
            labels = BUSINESS_LANGUAGES[language]

    def reply(key, english, **values):
        return labels.get(key, english).format(**values)

    if query in {"inventory summary", "inventory", "how much stock do i have"}:
        stock = db.execute(
            "SELECT stock, low_stock_threshold FROM products WHERE business_id = ?", (business_id,)
        ).fetchall()
        return reply(
            "inventory", "{count} products · {units} units in stock · {low} products below their stock threshold.",
            count=len(stock), units=f"{sum(row['stock'] for row in stock):,}",
            low=sum(row["stock"] < row["low_stock_threshold"] for row in stock),
        )

    if query in {"low stock", "low stock products", "which products are low in stock"}:
        rows = db.execute("""
            SELECT name, stock FROM products WHERE business_id = ? AND stock < low_stock_threshold
            ORDER BY stock, name, id LIMIT 11
        """, (business_id,)).fetchall()
        if not rows:
            return reply("no_low", "No products are below their stock threshold.")
        heading = (
            reply("low", "Products below their stock threshold") if len(rows) <= 10
            else reply("low_limited", "First 10 products below their stock threshold")
        )
        lines = [reply("stock_line", "{name} · {stock} in stock", **dict(row)) for row in rows[:10]]
        return "\n".join([f"{heading}:", *lines])

    stock_match = re.fullmatch(r"(?:stock for|stock of) (.+)", query)
    if stock_match:
        name = stock_match.group(1)
        rows = db.execute("""
            SELECT name, stock FROM products WHERE business_id = ? ORDER BY id
        """, (business_id,))
        matches = [
            row for row in rows
            if " ".join(unicodedata.normalize("NFC", row["name"].casefold()).split()) == name
        ]
        if not matches:
            return reply("product_missing", "I couldn't find a product with that exact name in your catalog.")
        if len(matches) > 1:
            return reply("product_multiple", "More than one product has that name. Open Products to see the separate stock counts.")
        product = matches[0]
        return reply("product_stock", "{name} has {stock} units in stock.", **dict(product))

    if query in {"customer count", "how many customers do i have"}:
        count = db.execute(
            "SELECT COUNT(*) FROM customers WHERE business_id = ?", (business_id,)
        ).fetchone()[0]
        return reply("customer_count", "Your business has {count} saved customer contacts.", count=count)

    if query in {"recent orders", "show recent orders", "show my recent orders"}:
        rows = db.execute(f"""
            SELECT {ORDER_COLUMNS} FROM orders WHERE business_id = ? ORDER BY id DESC LIMIT 5
        """, (business_id,)).fetchall()
        if not rows:
            return reply("no_orders", "Your business has no recorded orders.")
        heading = reply("recent_orders", "Most recent orders:")
        return "\n".join([heading, *(order_line(serialize_order(db, row), labels) for row in rows)])

    order_match = re.fullmatch(r"order(?: status)? #?(?:ord-)?([0-9]{1,19})", query)
    if order_match:
        order_id = int(order_match.group(1))
        if 1 <= order_id <= 2**63 - 1:
            row = db.execute(f"""
                SELECT {ORDER_COLUMNS} FROM orders WHERE id = ? AND business_id = ?
            """, (order_id, business_id)).fetchone()
            if row:
                return order_line(serialize_order(db, row), labels)
        return reply("order_missing", "That order wasn't found in your business.")

    if language != "en":
        return BUSINESS_LANGUAGES[language]["help"]

    return (
        "Try Sales summary, Sales last week, Inventory summary, Low stock, Recent orders, or Customer count. "
        "For a specific record, ask for Stock for <product name> or Order #ORD-123."
    )
