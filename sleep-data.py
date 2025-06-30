from datetime import datetime, timedelta
from garminconnect import Garmin
from notion_client import Client
from dotenv import load_dotenv
import pytz
import os

local_tz = pytz.timezone("Asia/Kuala_Lumpur")

def get_sleep_data_range(garmin, days_back=7):
    today = datetime.today().date()
    sleep_data_list = []
    for i in range(days_back):
        day = today - timedelta(days=i)
        data = garmin.get_sleep_data(day.isoformat())
        if data:
            sleep_data_list.append(data)
    return sleep_data_list

def is_nap(session):
    start_local = datetime.fromtimestamp(session["startGMT"] / 1000, local_tz)
    end_local = datetime.fromtimestamp(session["endGMT"] / 1000, local_tz)
    duration = (end_local - start_local).total_seconds()
    
    # Nap duration less than 2 hours
    if duration > 0 and duration <= 2 * 3600:
        # Nap between 9am and 6pm?
        if 9 <= start_local.hour < 18:
            return True
    return False

def format_duration(seconds):
    minutes = (seconds or 0) // 60
    return f"{minutes // 60}h {minutes % 60}m"

def format_time(timestamp):
    return (
        datetime.utcfromtimestamp(timestamp / 1000).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        if timestamp else None
    )

def format_time_readable(timestamp):
    return (
        datetime.fromtimestamp(timestamp / 1000, local_tz).strftime("%H:%M")
        if timestamp else "Unknown"
    )

def sleep_data_exists(client, database_id, sleep_date, session_type):
    # session_type: "Main Sleep" or "Nap"
    query = client.databases.query(
        database_id=database_id,
        filter={
            "and": [
                {"property": "Long Date", "date": {"equals": sleep_date}},
                {"property": "Session Type", "select": {"equals": session_type}}
            ]
        }
    )
    results = query.get('results', [])
    return results[0] if results else None

def create_sleep_data(client, database_id, session, session_type, resting_hr=None):
    start_ts = session.get('startGMT')
    end_ts = session.get('endGMT')
    if not start_ts or not end_ts:
        return
    
    start_local = datetime.fromtimestamp(start_ts / 1000, local_tz)
    end_local = datetime.fromtimestamp(end_ts / 1000, local_tz)
    sleep_date = start_local.date().isoformat()
    duration_seconds = (end_local - start_local).total_seconds()

    properties = {
        "Date": {"title": [{"text": {"content": start_local.strftime("%d.%m.%Y")}}]},
        "Times": {"rich_text": [{"text": {"content": f"{format_time_readable(start_ts)} → {format_time_readable(end_ts)}"}}]},
        "Long Date": {"date": {"start": sleep_date}},
        "Full Date/Time": {"date": {"start": format_time(start_ts), "end": format_time(end_ts)}},
        "Total Sleep (h)": {"number": round(duration_seconds / 3600, 2)},
        "Total Sleep": {"rich_text": [{"text": {"content": format_duration(duration_seconds)}}]},
        "Session Type": {"select": {"name": session_type}},
    }
    if resting_hr is not None:
        properties["Resting HR"] = {"number": resting_hr}

    client.pages.create(parent={"database_id": database_id}, properties=properties, icon={"emoji": "😴"})
    print(f"Created {session_type} entry for: {sleep_date} from {format_time_readable(start_ts)} to {format_time_readable(end_ts)}")

def main():
    load_dotenv()

    garmin = Garmin(os.getenv("GARMIN_EMAIL"), os.getenv("GARMIN_PASSWORD"))
    garmin.login()
    client = Client(auth=os.getenv("NOTION_TOKEN"))
    database_id = os.getenv("NOTION_SLEEP_DB_ID")

    sleep_data_list = get_sleep_data_range(garmin, days_back=7)

    for day_data in sleep_data_list:
        resting_hr = day_data.get('restingHeartRate')

        # Create main sleep session from dailySleepDTO
        main_sleep = day_data.get('dailySleepDTO')
        if main_sleep:
            sleep_date = main_sleep.get('calendarDate')
            if sleep_date and not sleep_data_exists(client, database_id, sleep_date, "Main Sleep"):
                create_sleep_data(client, database_id, main_sleep, "Main Sleep", resting_hr)

        # Now parse naps from detailed sleepLevelsMap (if exists)
        detailed_sleep = day_data.get("sleepLevelsMap")
        if detailed_sleep:
            sessions = detailed_sleep.get("sleep", [])
            for session in sessions:
                if is_nap(session):
                    start_local = datetime.fromtimestamp(session["startGMT"] / 1000, local_tz)
                    nap_date = start_local.date().isoformat()
                    if not sleep_data_exists(client, database_id, nap_date, "Nap"):
                        create_sleep_data(client, database_id, session, "Nap")

if __name__ == "__main__":
    main()
