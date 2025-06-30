from datetime import datetime, timezone, timedelta
import pytz
import os
from garminconnect import Garmin
from notion_client import Client
from dotenv import load_dotenv

# Set your local timezone here
local_tz = pytz.timezone('Asia/Kuala_Lumpur')

ACTIVITY_ICONS = {
    "Barre": "https://img.icons8.com/?size=100&id=66924&format=png&color=000000",
    # ... same as before
}

def get_all_activities(garmin, limit=1000):
    return garmin.get_activities(0, limit)

def format_activity_type(activity_type, activity_name=""):
    formatted = activity_type.replace('_', ' ').title() if activity_type else "Unknown"
    activity_type = activity_subtype = formatted

    mapping = {
        "Barre": "Strength", "Indoor Cardio": "Cardio",
        "Indoor Cycling": "Cycling", "Indoor Rowing": "Rowing",
        "Speed Walking": "Walking", "Strength Training": "Strength",
        "Treadmill Running": "Running"
    }

    if formatted in mapping:
        activity_type = mapping[formatted]
    if formatted == "Rowing V2":
        activity_type = "Rowing"
    if formatted in ["Yoga", "Pilates"]:
        activity_type = "Yoga/Pilates"

    # Name-based overrides
    lower = activity_name.lower()
    if "meditation" in lower:
        return "Meditation", "Meditation"
    if "barre" in lower:
        return "Strength", "Barre"
    if "stretch" in lower:
        return "Stretching", "Stretching"

    return activity_type, formatted

def format_entertainment(name):
    return name.replace('ENTERTAINMENT', 'Netflix')

def format_training_message(msg):
    messages = {
        'NO_': 'No Benefit', 'MINOR_': 'Some Benefit',
        'RECOVERY_': 'Recovery', 'MAINTAINING_': 'Maintaining',
        'IMPROVING_': 'Impacting', 'IMPACTING_': 'Impacting',
        'HIGHLY_': 'Highly Impacting', 'OVERREACHING_': 'Overreaching'
    }
    for k, v in messages.items():
        if msg.startswith(k):
            return v
    return msg

def format_training_effect(label):
    return label.replace('_', ' ').title()

def format_pace(avg_speed):
    if avg_speed > 0:
        pace = 1000 / (avg_speed * 60)
        mins = int(pace)
        secs = int((pace - mins) * 60)
        return f"{mins}:{secs:02d} min/km"
    return ""

def convert_to_local_time(gmt_time_str):
    try:
        gmt = datetime.strptime(gmt_time_str, '%Y-%m-%dT%H:%M:%S.%fZ')
    except ValueError:
        gmt = datetime.strptime(gmt_time_str, '%Y-%m-%d %H:%M:%S')
    gmt = gmt.replace(tzinfo=timezone.utc).astimezone(local_tz)
    return gmt

def get_activity_end_time(start_str, duration_sec):
    start = convert_to_local_time(start_str)
    end = start + timedelta(seconds=duration_sec)
    return start, end

def activity_exists(client, db_id, date_str, activity_type, activity_name):
    main_type = activity_type if isinstance(activity_type, str) else activity_type[0]
    lookup_type = "Stretching" if "stretch" in activity_name.lower() else main_type

    try:
        resp = client.databases.query(
            database_id=db_id,
            filter={
                "and": [
                    {"property": "Date", "date": {"equals": date_str.split('T')[0]}},
                    {"property": "Activity Type", "select": {"equals": lookup_type}},
                    {"property": "Activity Name", "title": {"equals": activity_name}}
                ]
            }
        )
        return resp.get('results', [None])[0]
    except Exception:
        return None

def activity_needs_update(existing, new):
    props = existing.get('properties', {})
    act_name = new.get('activityName', '')
    type_main, subtype = format_activity_type(new.get('activityType', {}).get('typeKey', ''), act_name)

    def num(prop): return props.get(prop, {}).get('number', None)
    def sel_name(prop): return props.get(prop, {}).get('select', {}).get('name', None)
    def rich_text(prop): 
        rt = props.get(prop, {}).get('rich_text', [])
        return rt[0]['text']['content'] if rt else None
    def chk(prop): return props.get(prop, {}).get('checkbox', None)

    checks = {
        'Distance (km)': round(new.get('distance',0)/1000,2),
        'Duration (min)': round(new.get('duration',0)/60,2),
        'Calories': round(new.get('calories',0)),
        'Avg Pace': format_pace(new.get('averageSpeed',0)),
        'Avg Power': round(new.get('avgPower',0),1),
        'Max Power': round(new.get('maxPower',0),1),
        'Training Effect': format_training_effect(new.get('trainingEffectLabel','')),
        'Aerobic': round(new.get('aerobicTrainingEffect',0),1),
        'Anaerobic': round(new.get('anaerobicTrainingEffect',0),1),
        'Aerobic Effect': format_training_message(new.get('aerobicTrainingEffectMessage','')),
        'Anaerobic Effect': format_training_message(new.get('anaerobicTrainingEffectMessage','')),
        'PR': new.get('pr',False),
        'Fav': new.get('favorite',False),
        'Activity Type': type_main,
    }

    for prop, val in checks.items():
        if prop in ['PR','Fav']:
            if chk(prop) != val:
                return True
        elif prop in ['Activity Type']:
            if sel_name(prop) != val:
                return True
        elif prop in ['Training Effect','Aerobic Effect','Anaerobic Effect']:
            if sel_name(prop) != val:
                return True
        elif prop in ['Avg Pace']:
            if rich_text(prop) != val:
                return True
        else:
            if num(prop) != val:
                return True

    # Check subtype if exists
    subtype_name = sel_name('Subactivity Type')
    if subtype_name is None or subtype_name != subtype:
        return True

    return False

def create_activity(client, db_id, act):
    name = format_entertainment(act.get('activityName','Unnamed'))
    type_main, subtype = format_activity_type(act.get('activityType', {}).get('typeKey',''), name)
    start, end = get_activity_end_time(act.get('startTimeGMT',''), act.get('duration',0))
    icon = ACTIVITY_ICONS.get(subtype if subtype != type_main else type_main)

    props = {
        "Date": {"date": {"start": start.isoformat(), "end": end.isoformat()}},
        "Activity Type": {"select": {"name": type_main}},
        "Subactivity Type": {"select": {"name": subtype}},
        "Activity Name": {"title": [{"text": {"content": name}}]},
        "Distance (km)": {"number": round(act.get('distance',0)/1000,2)},
        "Duration (min)": {"number": round(act.get('duration',0)/60,2)},
        "Calories": {"number": round(act.get('calories',0))},
        "Avg Pace": {"rich_text":[{"text":{"content":format_pace(act.get('averageSpeed',0))}}]},
        "Avg Power": {"number": round(act.get('avgPower',0),1)},
        "Max Power": {"number": round(act.get('maxPower',0),1)},
        "Training Effect": {"select":{"name":format_training_effect(act.get('trainingEffectLabel',''))}},
        "Aerobic": {"number": round(act.get('aerobicTrainingEffect',0),1)},
        "Aerobic Effect": {"select":{"name":format_training_message(act.get('aerobicTrainingEffectMessage',''))}},
        "Anaerobic": {"number": round(act.get('anaerobicTrainingEffect',0),1)},
        "Anaerobic Effect": {"select":{"name":format_training_message(act.get('anaerobicTrainingEffectMessage',''))}},
        "PR": {"checkbox": act.get('pr',False)},
        "Fav": {"checkbox": act.get('favorite',False)},
    }
    page = {"parent": {"database_id": db_id}, "properties": props}
    if icon:
        page["icon"] = {"type": "external", "external": {"url": icon}}
    client.pages.create(**page)

def update_activity(client, existing, act):
    name = format_entertainment(act.get('activityName','Unnamed'))
    type_main, subtype = format_activity_type(act.get('activityType', {}).get('typeKey',''), name)
    icon = ACTIVITY_ICONS.get(subtype if subtype != type_main else type_main)

    props = {
        "Activity Type": {"select": {"name": type_main}},
        "Subactivity Type": {"select": {"name": subtype}},
        "Distance (km)": {"number": round(act.get('distance',0)/1000,2)},
        "Duration (min)": {"number": round(act.get('duration',0)/60,2)},
        "Calories": {"number": round(act.get('calories',0))},
        "Avg Pace": {"rich_text":[{"text":{"content":format_pace(act.get('averageSpeed',0))}}]},
        "Avg Power": {"number": round(act.get('avgPower',0),1)},
        "Max Power": {"number": round(act.get('maxPower',0),1)},
        "Training Effect": {"select":{"name":format_training_effect(act.get('trainingEffectLabel',''))}},
        "Aerobic": {"number": round(act.get('aerobicTrainingEffect',0),1)},
        "Aerobic Effect": {"select":{"name":format_training_message(act.get('aerobicTrainingEffectMessage',''))}},
        "Anaerobic": {"number": round(act.get('anaerobicTrainingEffect',0),1)},
        "Anaerobic Effect": {"select":{"name":format_training_message(act.get('anaerobicTrainingEffectMessage',''))}},
        "PR": {"checkbox": act.get('pr',False)},
        "Fav": {"checkbox": act.get('favorite',False)},
    }
    update = {"page_id": existing['id'], "properties": props}
    if icon:
        update["icon"] = {"type": "external", "external": {"url": icon}}
    client.pages.update(**update)

def main():
    load_dotenv()
    garmin_email = os.getenv("GARMIN_EMAIL")
    garmin_password = os.getenv("GARMIN_PASSWORD")
    notion_token = os.getenv("NOTION_TOKEN")
    database_id = os.getenv("NOTION_DB_ID")

    if not all([garmin_email, garmin_password, notion_token, database_id]):
        raise ValueError("Missing required environment values.")

    garmin = Garmin(garmin_email, garmin_password)
    garmin.login()
    client = Client(auth=notion_token)

    activities = get_all_activities(garmin)
    for act in activities:
        activity_name = format_entertainment(act.get('activityName','Unnamed'))
        activity_type = format_activity_type(act.get('activityType', {}).get('typeKey',''), activity_name)
        existing = activity_exists(client, database_id, act.get('startTimeGMT',''), activity_type, activity_name)

        if existing and activity_needs_update(existing, act):
            update_activity(client, existing, act)
            print("Updated:", activity_name)
        elif not existing:
            create_activity(client, database_id, act)
            print("Created:", activity_name)

if __name__ == '__main__':
    main()
