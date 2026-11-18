"""In-memory stand-ins for the repositories, so services can be tested without MongoDB."""

import itertools
from datetime import UTC, datetime
from typing import Any

from app.core.constants import WELLNESS_LOG_KEY
from app.db.base import DuplicateKeyError
from app.integrations.email import EmailDeliveryError
from app.services.push_service import PushSendResult

_ids = itertools.count(1)
ALL_DAYS = [0, 1, 2, 3, 4, 5, 6]


def _object_id() -> str:
    """A unique 24-hex-character id, the shape of a real MongoDB ObjectId."""
    return f"{next(_ids):024x}"


def med_doc(
    user_id: str,
    name: str,
    times: list[str],
    days: list[int] | None = None,
    enabled: bool = True,
) -> dict[str, Any]:
    return {
        "_id": _object_id(),
        "userId": user_id,
        "name": name,
        "description": "",
        "instructions": "",
        "scheduleTimes": times,
        "daysOfWeek": days if days is not None else list(ALL_DAYS),
        "enabled": enabled,
    }


class FakeMedications:
    def __init__(self, docs: list[dict[str, Any]] | None = None) -> None:
        self.docs = docs or []

    async def list_for_user(self, user_id: str, only_enabled: bool = False) -> list[dict[str, Any]]:
        rows = [
            d
            for d in self.docs
            if str(d["userId"]) == str(user_id) and (d["enabled"] or not only_enabled)
        ]
        return sorted(rows, key=lambda d: d["name"])

    async def list_enabled_for_users(self, user_ids: Any) -> list[dict[str, Any]]:
        ids = {str(u) for u in user_ids}
        return [d for d in self.docs if str(d["userId"]) in ids and d["enabled"]]

    async def create(self, user_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        if any(d["userId"] == user_id and d["name"] == fields["name"] for d in self.docs):
            raise DuplicateKeyError("duplicate")
        doc = {"_id": _object_id(), "userId": user_id, **fields, "enabled": True}
        self.docs.append(doc)
        return doc

    async def update(
        self, user_id: str, medication_id: str, fields: dict[str, Any]
    ) -> dict[str, Any] | None:
        for d in self.docs:
            if d["_id"] == medication_id and d["userId"] == user_id:
                if "name" in fields and any(
                    o is not d and o["userId"] == user_id and o["name"] == fields["name"]
                    for o in self.docs
                ):
                    raise DuplicateKeyError("duplicate")
                d.update(fields)
                return d
        return None

    async def delete(self, user_id: str, medication_id: str) -> bool:
        before = len(self.docs)
        self.docs = [
            d for d in self.docs if not (d["_id"] == medication_id and d["userId"] == user_id)
        ]
        return len(self.docs) < before

    async def delete_all_for_user(self, user_id: str) -> int:
        before = len(self.docs)
        self.docs = [d for d in self.docs if str(d["userId"]) != str(user_id)]
        return before - len(self.docs)


class FakeDailyLogs:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def delete_all_for_user(self, user_id: str) -> int:
        before = len(self.rows)
        self.rows = [r for r in self.rows if r["userId"] != str(user_id)]
        return before - len(self.rows)

    # ---- helpers for tests -----------------------------------------------------------------

    def add_dose(
        self,
        user_id: str,
        date: str,
        name: str,
        time: str,
        completed: bool = True,
        completed_at: datetime | None = None,
    ) -> None:
        self.rows.append(
            {
                "userId": user_id,
                "date": date,
                "medicationName": name,
                "scheduledTime": time,
                "completed": completed,
                "completedAt": completed_at if completed else None,
            }
        )

    def _doses(self, user_id: str) -> list[dict[str, Any]]:
        return [
            r
            for r in self.rows
            if r["userId"] == str(user_id) and r["medicationName"] != WELLNESS_LOG_KEY
        ]

    # ---- dose logs -------------------------------------------------------------------------

    async def set_dose_completion(
        self,
        user_id: str,
        date: str,
        medication_name: str,
        scheduled_time: str,
        completed: bool,
        moment: datetime,
    ) -> None:
        for r in self._doses(user_id):
            if (r["date"], r["medicationName"], r["scheduledTime"]) == (
                date,
                medication_name,
                scheduled_time,
            ):
                r["completed"] = completed
                r["completedAt"] = moment if completed else None
                return
        self.add_dose(user_id, date, medication_name, scheduled_time, completed, moment)

    async def is_dose_completed(
        self, user_id: str, date: str, medication_name: str, scheduled_time: str
    ) -> bool:
        return any(
            r["completed"]
            for r in self._doses(user_id)
            if (r["date"], r["medicationName"], r["scheduledTime"])
            == (date, medication_name, scheduled_time)
        )

    async def find_doses_for_day(self, user_id: str, date: str) -> list[dict[str, Any]]:
        return [r for r in self._doses(user_id) if r["date"] == date]

    async def find_doses_in_range(self, user_id: str, start: str, end: str) -> list[dict[str, Any]]:
        return [r for r in self._doses(user_id) if start <= r["date"] <= end]

    async def _group(self, user_id: str, start: str, end: str, key: str) -> list[dict[str, Any]]:
        groups: dict[str, dict[str, Any]] = {}
        for r in await self.find_doses_in_range(user_id, start, end):
            g = groups.setdefault(r[key], {"_id": r[key], "total": 0, "completed": 0})
            g["total"] += 1
            g["completed"] += 1 if r["completed"] else 0
        return list(groups.values())

    async def completion_by_date(self, user_id: str, start: str, end: str) -> list[dict[str, Any]]:
        return await self._group(user_id, start, end, "date")

    async def completion_by_medication(
        self, user_id: str, start: str, end: str
    ) -> list[dict[str, Any]]:
        return await self._group(user_id, start, end, "medicationName")

    async def count_missed_before(self, user_id: str, date: str) -> int:
        return sum(1 for r in self._doses(user_id) if not r["completed"] and r["date"] < date)

    # ---- wellness --------------------------------------------------------------------------

    def _wellness_row(self, user_id: str, day: str) -> dict[str, Any]:
        for r in self.rows:
            if (
                r["userId"] == str(user_id)
                and r["date"] == day
                and r["medicationName"] == WELLNESS_LOG_KEY
            ):
                return r
        row = {
            "userId": str(user_id),
            "date": day,
            "medicationName": WELLNESS_LOG_KEY,
            "scheduledTime": WELLNESS_LOG_KEY,
            "completed": False,
            "completedAt": None,
            "count": 0,
            "notes": "",
        }
        self.rows.append(row)
        return row

    async def find_wellness_range(self, user_id: str, start: str, end: str) -> list[dict[str, Any]]:
        rows = [
            r
            for r in self.rows
            if r["userId"] == str(user_id)
            and r["medicationName"] == WELLNESS_LOG_KEY
            and start <= r["date"] <= end
        ]
        return sorted(rows, key=lambda r: r["date"])

    async def adjust_wellness_count(
        self, user_id: str, day: str, delta: int, moment: datetime
    ) -> int:
        row = self._wellness_row(user_id, day)
        row["count"] = max(0, row["count"] + delta)
        return row["count"]

    async def reset_wellness_count(self, user_id: str, day: str, moment: datetime) -> None:
        self._wellness_row(user_id, day)["count"] = 0

    async def set_wellness_notes(
        self, user_id: str, day: str, notes: str, moment: datetime
    ) -> None:
        self._wellness_row(user_id, day)["notes"] = notes


# ---- auth ----------------------------------------------------------------------------------


class FakeUsers:
    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}

    async def exists_by_email(self, email: str) -> bool:
        return email in self.docs

    async def find_by_email(self, email: str) -> dict[str, Any] | None:
        return self.docs.get(email)

    async def find_by_id(self, user_id: str) -> dict[str, Any] | None:
        return next((u for u in self.docs.values() if u["_id"] == str(user_id)), None)

    async def create(self, email: str) -> dict[str, Any]:
        if email in self.docs:
            raise DuplicateKeyError("duplicate")
        self.docs[email] = {"_id": f"user{next(_ids)}", "email": email}
        return self.docs[email]

    async def delete(self, user_id: str) -> bool:
        found = await self.find_by_id(user_id)
        if found is None:
            return False
        del self.docs[found["email"]]
        return True


class FakeOtps:
    def __init__(self) -> None:
        self.docs: dict[tuple[str, str], dict[str, Any]] = {}

    async def find(self, email: str, purpose: str) -> dict[str, Any] | None:
        return self.docs.get((email, purpose))

    async def upsert(
        self, email: str, purpose: str, code_hash: str, sent_at: datetime, expires_at: datetime
    ) -> None:
        existing = self.docs.get((email, purpose), {"_id": f"otp{next(_ids)}"})
        self.docs[(email, purpose)] = {
            **existing,
            "email": email,
            "purpose": purpose,
            "codeHash": code_hash,
            "attempts": 0,
            "sentAt": sent_at,
            "expiresAt": expires_at,
        }

    async def delete(self, email: str, purpose: str) -> None:
        self.docs.pop((email, purpose), None)

    async def delete_for_email(self, email: str) -> None:
        self.docs = {k: v for k, v in self.docs.items() if k[0] != email}

    async def delete_by_id(self, otp_id: str) -> None:
        self.docs = {k: v for k, v in self.docs.items() if v["_id"] != otp_id}

    async def increment_attempts(self, otp_id: str) -> int | None:
        for v in self.docs.values():
            if v["_id"] == otp_id:
                v["attempts"] += 1
                return v["attempts"]
        return None

    async def consume(self, otp_id: str) -> bool:
        before = len(self.docs)
        await self.delete_by_id(otp_id)
        return len(self.docs) < before


class FakeSessions:
    def __init__(self) -> None:
        self.docs: list[dict[str, Any]] = []

    async def create(self, token_hash: str, user_id: str, expires_at: datetime) -> None:
        self.docs.append(
            {
                "_id": f"sess{next(_ids)}",
                "tokenHash": token_hash,
                "userId": user_id,
                "expiresAt": expires_at,
            }
        )

    async def find_active_by_token_hash(self, token_hash: str) -> dict[str, Any] | None:
        now = datetime.now(UTC)
        return next(
            (s for s in self.docs if s["tokenHash"] == token_hash and s["expiresAt"] > now), None
        )

    async def delete_by_token_hash(self, token_hash: str) -> dict[str, Any] | None:
        found = next((s for s in self.docs if s["tokenHash"] == token_hash), None)
        if found:
            self.docs.remove(found)
        return found

    async def delete_all_for_user(self, user_id: str) -> int:
        before = len(self.docs)
        self.docs = [s for s in self.docs if s["userId"] != user_id]
        return before - len(self.docs)

    async def active_ids_for_user(self, user_id: str) -> list[str]:
        now = datetime.now(UTC)
        return [s["_id"] for s in self.docs if s["userId"] == user_id and s["expiresAt"] > now]


class FakePushTokens:
    def __init__(self, user_ids: list[str] | None = None) -> None:
        self.user_ids = user_ids or []
        self.deleted_sessions: list[str] = []

    async def delete_by_session(self, session_id: str) -> None:
        self.deleted_sessions.append(session_id)

    async def delete_all_for_user(self, user_id: str) -> int:
        removed = self.user_ids.count(user_id)
        self.user_ids = [u for u in self.user_ids if u != user_id]
        return removed

    async def distinct_user_ids(self) -> list[str]:
        return self.user_ids


class FakeEmail:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[tuple[str, str, str]] = []

    async def send_otp(self, to: str, code: str, purpose: str) -> None:
        if self.fail:
            raise EmailDeliveryError("Email provider error: boom")
        self.sent.append((to, code, purpose))


# ---- reminders -----------------------------------------------------------------------------


class FakeRemindersSent:
    def __init__(self) -> None:
        self.claimed: set[tuple[str, str, str, str]] = set()

    async def claim(self, user_id: str, date: str, name: str, time: str) -> bool:
        key = (str(user_id), date, name, time)
        if key in self.claimed:
            return False
        self.claimed.add(key)
        return True

    async def delete_all_for_user(self, user_id: str) -> int:
        mine = {c for c in self.claimed if c[0] == str(user_id)}
        self.claimed -= mine
        return len(mine)

    async def release(self, user_id: str, date: str, time: str, names: Any) -> None:
        for name in names:
            self.claimed.discard((str(user_id), date, name, time))


class FakePush:
    def __init__(self, result: PushSendResult | None = None) -> None:
        self.result = result or PushSendResult(sent=1, failed=0)
        self.calls: list[tuple[str, Any]] = []

    async def send_to_user(self, user_id: str, payload: Any) -> PushSendResult:
        self.calls.append((str(user_id), payload))
        return self.result
