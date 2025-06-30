def update_activity(client, existing, act):
    name = format_entertainment(act.get('activityName','Unnamed'))
    type_main, subtype = format_activity_type(act.get('activityType', {}).get('typeKey',''), name)
    icon = ACTIVITY_ICONS.get(subtype if subtype != type_main else type_main)

    # Format and clean values
    training_effect_label = format_training_effect(act.get('trainingEffectLabel', '')).strip()
    aerobic_msg = format_training_message(act.get('aerobicTrainingEffectMessage', '')).strip()
    anaerobic_msg = format_training_message(act.get('anaerobicTrainingEffectMessage', '')).strip()

    props = {
        "Activity Type": {"select": {"name": type_main}},
        "Subactivity Type": {"select": {"name": subtype}},
        "Distance (km)": {"number": round(act.get('distance', 0) / 1000, 2)},
        "Duration (min)": {"number": round(act.get('duration', 0) / 60, 2)},
        "Calories": {"number": round(act.get('calories', 0))},
        "Avg Pace": {
            "rich_text": [{
                "text": {"content": format_pace(act.get('averageSpeed', 0))}
            }]
        },
        "Avg Power": {"number": round(act.get('avgPower', 0), 1)},
        "Max Power": {"number": round(act.get('maxPower', 0), 1)},
        "Aerobic": {"number": round(act.get('aerobicTrainingEffect', 0), 1)},
        "Anaerobic": {"number": round(act.get('anaerobicTrainingEffect', 0), 1)},
        "PR": {"checkbox": act.get('pr', False)},
        "Fav": {"checkbox": act.get('favorite', False)},
    }

    # Conditionally add select fields if they have valid values
    if training_effect_label:
        props["Training Effect"] = {"select": {"name": training_effect_label}}
    if aerobic_msg:
        props["Aerobic Effect"] = {"select": {"name": aerobic_msg}}
    if anaerobic_msg:
        props["Anaerobic Effect"] = {"select": {"name": anaerobic_msg}}

    update = {
        "page_id": existing['id'],
        "properties": props
    }

    if icon:
        update["icon"] = {"type": "external", "external": {"url": icon}}

    # Send to Notion
    client.pages.update(**update)
