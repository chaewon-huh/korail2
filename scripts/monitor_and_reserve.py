"""Poll Korail for seats and reserve when available."""
import argparse
import sys
import time
from datetime import datetime

from korail2 import Korail, ReserveOption, NoResultsError, NeedToLoginError, SoldOutError


def normalize_id(raw_id: str) -> str:
    """Normalize phone-like IDs to ###-####-#### for Korail."""
    digits = "".join(ch for ch in raw_id if ch.isdigit())
    if len(digits) == 11:
        return f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
    return raw_id


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Poll Korail and auto-reserve general seats.")
    parser.add_argument("--id", dest="korail_id", required=True, help="Korail ID (membership/email/phone)")
    parser.add_argument("--pw", dest="korail_pw", required=True, help="Korail password")
    parser.add_argument("--dep", default="동대구", help="Departure station (default: 동대구)")
    parser.add_argument("--arr", default="광명", help="Arrival station (default: 광명)")
    parser.add_argument("--date", default=datetime.now().strftime("%Y%m%d"), help="Date YYYYMMDD (default: today)")
    parser.add_argument(
        "--time",
        dest="dep_time",
        default=datetime.now().strftime("%H%M%S"),
        help="Start time HHMMSS search cursor (default: now)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=3,
        help="Max trains (earliest first) to attempt per poll cycle after filtering by general seats",
    )
    parser.add_argument("--interval", type=int, default=5, help="Polling interval seconds")
    return parser.parse_args()


def poll_and_reserve(korail: Korail, dep: str, arr: str, date: str, dep_time: str, limit: int, interval: int) -> None:
    attempt = 0
    while True:
        attempt += 1
        print(f"[{attempt}] Searching {dep}->{arr} on {date} from {dep_time} (limit {limit})...")
        try:
            trains = korail.search_train(dep, arr, date, dep_time)
            # Keep earliest trains that have general seats.
            trains = [t for t in trains if t.has_general_seat()]
            trains.sort(key=lambda t: (t.dep_date, t.dep_time))
            trains = trains[:limit]
            if not trains:
                raise NoResultsError()
            for train in trains:
                print(f"Trying {train}")
                try:
                    reservation = korail.reserve(train, option=ReserveOption.GENERAL_ONLY)
                    print(f"Reserved! ID={reservation.rsv_id}, train={reservation}")
                    return
                except SoldOutError:
                    # Try next candidate in this poll cycle.
                    print("Sold out while reserving candidate, moving on...")
                    continue
        except NoResultsError:
            print("No seats found.")
        except NeedToLoginError:
            print("Session expired, re-authenticating...")
            if not korail.login():
                print("Re-login failed, aborting.")
                sys.exit(1)
        except Exception as exc:  # pragma: no cover - safety net for unexpected issues
            print(f"Unexpected error: {exc}")

        time.sleep(interval)


def main() -> None:
    args = parse_args()
    korail_id = normalize_id(args.korail_id)
    korail = Korail(korail_id, args.korail_pw, auto_login=True)
    if not korail.logined:
        print("Login failed. Check credentials.")
        sys.exit(1)
    poll_and_reserve(korail, args.dep, args.arr, args.date, args.dep_time, args.limit, args.interval)


if __name__ == "__main__":
    main()
