from datetime import timedelta
from typing import Literal

OtpPurpose = Literal["signup", "signin"]

OTP_LENGTH = 6
OTP_TTL = timedelta(minutes=10)
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_COOLDOWN = timedelta(seconds=60)

# Refresh tokens rotate on every use. Presenting the previous one again within this window is
# treated as two tabs racing (rejected, harmless); later it is treated as theft (session revoked).
REFRESH_REUSE_GRACE = timedelta(seconds=10)
# The refresh cookie is only sent to the auth endpoints.
REFRESH_COOKIE_PATH = "/api/v1/auth"

# Wellness counters live in the same collection as dose logs, under this sentinel name.
WELLNESS_LOG_KEY = "__wellness__"

HEATMAP_DAYS = 133
MEDICATION_HISTORY_DAYS = 14
STATS_DAYS = 120
WELLNESS_YEAR_DAYS = 365
WELLNESS_CALENDAR_DAYS = 119
WELLNESS_WEEKLY_AVG_WINDOW = 84
WELLNESS_HISTORY_LIMIT = 30

# Reminder runs still count a dose as "due" this many minutes after its scheduled minute.
REMINDER_LOOKBACK_MINUTES = 5

# Family sharing: a father shares a one-time code, his son connects with it to follow along.
INVITE_CODE_LENGTH = 8
INVITE_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I, easy to read aloud
INVITE_CODE_TTL = timedelta(hours=24)
CAREGIVER_REMIND_COOLDOWN = timedelta(minutes=5)
ACTIVITY_LIMIT = 20

# Reports
REPORT_SEND_COOLDOWN = timedelta(seconds=60)
WEEKDAY_SHORT = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")  # 0 = Sunday
