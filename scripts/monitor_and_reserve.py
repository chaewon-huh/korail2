"""Poll Korail for seats and reserve when available."""

import argparse
import logging
import sys
import time
from datetime import datetime
from typing import Optional

from korail2 import (
    Korail,
    NeedToLoginError,
    NoResultsError,
    ReserveOption,
    SoldOutError,
)

logger = logging.getLogger("monitor_and_reserve")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def normalize_id(raw_id: str) -> str:
    """Normalize phone-like IDs to ###-####-#### for Korail."""
    digits = "".join(ch for ch in raw_id if ch.isdigit())
    if len(digits) == 11:
        return f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
    return raw_id


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Poll Korail and auto-reserve general seats."
    )
    parser.add_argument(
        "--id",
        dest="korail_id",
        required=True,
        help="Korail ID (membership/email/phone)",
    )
    parser.add_argument("--pw", dest="korail_pw", required=True, help="Korail password")
    parser.add_argument(
        "--dep", default="동대구", help="Departure station (default: 동대구)"
    )
    parser.add_argument("--arr", default="광명", help="Arrival station (default: 광명)")
    parser.add_argument(
        "--date",
        default=datetime.now().strftime("%Y%m%d"),
        help="Date YYYYMMDD (default: today)",
    )
    parser.add_argument(
        "--time",
        dest="dep_time",
        default=datetime.now().strftime("%H%M%S"),
        help="Start time HHMMSS search cursor (default: now)",
    )
    parser.add_argument(
        "--end-time",
        dest="end_time",
        help="Latest departure time HHMMSS (optional, filters out trains after this time)",
    )
    parser.add_argument(
        "--exact",
        action="store_true",
        help="Only monitor the exact departure time train (uses --time, ignores --end-time/--limit)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=3,
        help="Max trains (earliest first) to attempt per poll cycle after filtering by general seats",
    )
    parser.add_argument(
        "--interval", type=int, default=3, help="Polling interval seconds"
    )
    return parser.parse_args()


def _validate_time(dep_time: str) -> str:
    return datetime.strptime(dep_time, "%H%M%S").strftime("%H%M%S")


def _validate_date(dep_date: str) -> str:
    return datetime.strptime(dep_date, "%Y%m%d").strftime("%Y%m%d")


def poll_and_reserve(
    korail: Korail,
    dep: str,
    arr: str,
    date: str,
    dep_time: str,
    limit: int,
    interval: int,
    end_time: Optional[str] = None,
):
    dep = dep.strip()
    arr = arr.strip()
    date = _validate_date(date.strip())
    dep_time = _validate_time(dep_time.strip())
    end_time = _validate_time(end_time.strip()) if end_time else None
    interval = max(3, min(interval, 300))

    attempt = 0
    relogin_attempts = 0
    while True:
        attempt += 1
        logger.info(
            "[%s] Searching %s->%s on %s from %s (limit %s)...",
            attempt,
            dep,
            arr,
            date,
            dep_time,
            limit,
        )
        try:
            trains = korail.search_train(dep, arr, date, dep_time)
            if end_time:
                trains = [t for t in trains if t.dep_time <= end_time]
            # Keep earliest trains that have general seats.
            trains = [t for t in trains if t.has_general_seat()]
            trains.sort(key=lambda t: (t.dep_date, t.dep_time))
            trains = trains[:limit]
            if not trains:
                raise NoResultsError()
            for train in trains:
                logger.info("Trying %s", train)
                try:
                    reservation = korail.reserve(
                        train, option=ReserveOption.GENERAL_ONLY
                    )
                    logger.info(
                        "Reserved! ID=%s, train=%s",
                        getattr(reservation, "rsv_id", None),
                        reservation,
                    )
                    return reservation
                except SoldOutError:
                    logger.info("Sold out while reserving candidate, moving on...")
                    continue
        except NoResultsError:
            logger.info("No seats found.")
        except NeedToLoginError:
            relogin_attempts += 1
            if relogin_attempts > 3:
                logger.error("Re-login failed too many times, aborting.")
                sys.exit(1)
            logger.info(
                "Session expired, re-authenticating (attempt %s)...", relogin_attempts
            )
            if not korail.login():
                logger.error("Re-login failed, aborting.")
                sys.exit(1)
        except Exception as exc:  # pragma: no cover - safety net for unexpected issues
            logger.exception("Unexpected error: %s", exc)

        time.sleep(interval)


def poll_and_reserve_exact_train(
    korail: Korail,
    dep: str,
    arr: str,
    date: str,
    exact_dep_time: str,
    interval: int,
):
    dep = dep.strip()
    arr = arr.strip()
    date = _validate_date(date.strip())
    exact_dep_time = _validate_time(exact_dep_time.strip())
    interval = max(3, min(interval, 300))

    attempt = 0
    relogin_attempts = 0
    while True:
        attempt += 1
        logger.info(
            "[%s] Searching exact train %s->%s on %s at %s ...",
            attempt,
            dep,
            arr,
            date,
            exact_dep_time,
        )
        try:
            trains = korail.search_train(
                dep, arr, date, exact_dep_time, include_no_seats=True
            )
            candidates = [
                t
                for t in trains
                if t.dep_date == date
                and t.dep_time == exact_dep_time
                and t.dep_name == dep
                and t.arr_name == arr
            ]
            if not candidates:
                raise NoResultsError()

            train = candidates[0]
            logger.info("Found %s", train)
            if not train.has_general_seat():
                logger.info("No general seats yet, retrying...")
            else:
                reservation = korail.reserve(train, option=ReserveOption.GENERAL_ONLY)
                logger.info(
                    "Reserved! ID=%s, train=%s",
                    getattr(reservation, "rsv_id", None),
                    reservation,
                )
                return reservation
        except NoResultsError:
            logger.info("Exact train not found (or no schedule returned yet).")
        except NeedToLoginError:
            relogin_attempts += 1
            if relogin_attempts > 3:
                logger.error("Re-login failed too many times, aborting.")
                sys.exit(1)
            logger.info(
                "Session expired, re-authenticating (attempt %s)...", relogin_attempts
            )
            if not korail.login():
                logger.error("Re-login failed, aborting.")
                sys.exit(1)
        except SoldOutError:
            logger.info("Sold out while reserving, retrying...")
        except Exception as exc:  # pragma: no cover - safety net for unexpected issues
            logger.exception("Unexpected error: %s", exc)

        time.sleep(interval)


def main() -> None:
    args = parse_args()
    korail_id = normalize_id(args.korail_id)
    korail = Korail(korail_id, args.korail_pw, auto_login=True)
    if not korail.logined:
        print("Login failed. Check credentials.")
        sys.exit(1)
    if args.exact:
        poll_and_reserve_exact_train(
            korail=korail,
            dep=args.dep,
            arr=args.arr,
            date=args.date,
            exact_dep_time=args.dep_time,
            interval=args.interval,
        )
    else:
        poll_and_reserve(
            korail,
            args.dep,
            args.arr,
            args.date,
            args.dep_time,
            args.limit,
            args.interval,
            args.end_time,
        )


if __name__ == "__main__":
    main()
