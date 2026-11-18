from datetime import timedelta
from typing import Literal

OtpPurpose = Literal["signup", "signin"]

OTP_LENGTH = 6
OTP_TTL = timedelta(minutes=10)
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_COOLDOWN = timedelta(seconds=60)

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
