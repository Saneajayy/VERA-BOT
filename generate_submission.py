import json
import os
import requests

BOT_URL = "http://localhost:8080"

# 1. Load the dataset
expanded_dir = "dataset/expanded"
with open(f"{expanded_dir}/test_pairs.json", "r") as f:
    test_pairs = json.load(f)["pairs"]

# 2. Push contexts needed for the test pairs
categories = {}
for file in os.listdir(f"{expanded_dir}/categories"):
    with open(f"{expanded_dir}/categories/{file}", "r") as f:
        data = json.load(f)
        categories[data["slug"]] = data
        requests.post(f"{BOT_URL}/v1/context", json={
            "scope": "category",
            "context_id": data["slug"],
            "version": 1,
            "payload": data,
            "delivered_at": "2026-04-26T10:00:00Z"
        })

for pair in test_pairs:
    merchant_id = pair["merchant_id"]
    with open(f"{expanded_dir}/merchants/{merchant_id}.json", "r") as f:
        merchant_data = json.load(f)
        requests.post(f"{BOT_URL}/v1/context", json={
            "scope": "merchant",
            "context_id": merchant_id,
            "version": 1,
            "payload": merchant_data,
            "delivered_at": "2026-04-26T10:00:00Z"
        })

    trigger_id = pair["trigger_id"]
    with open(f"{expanded_dir}/triggers/{trigger_id}.json", "r") as f:
        trigger_data = json.load(f)
        requests.post(f"{BOT_URL}/v1/context", json={
            "scope": "trigger",
            "context_id": trigger_id,
            "version": 1,
            "payload": trigger_data,
            "delivered_at": "2026-04-26T10:00:00Z"
        })
        
    customer_id = trigger_data.get("customer_id")
    if customer_id:
        with open(f"{expanded_dir}/customers/{customer_id}.json", "r") as f:
            customer_data = json.load(f)
            requests.post(f"{BOT_URL}/v1/context", json={
                "scope": "customer",
                "context_id": customer_id,
                "version": 1,
                "payload": customer_data,
                "delivered_at": "2026-04-26T10:00:00Z"
            })

# 3. Request ticks for each pair and write to submission.jsonl
with open("submission.jsonl", "w") as out_f:
    for pair in test_pairs:
        test_id = pair["test_id"]
        trigger_id = pair["trigger_id"]
        
        # We simulate the tick with just this trigger
        resp = requests.post(f"{BOT_URL}/v1/tick", json={
            "now": "2026-04-26T10:05:00Z",
            "available_triggers": [trigger_id]
        })
        
        actions = resp.json().get("actions", [])
        if actions:
            action = actions[0]
            out = {
                "test_id": test_id,
                "body": action["body"],
                "cta": action["cta"],
                "send_as": action["send_as"],
                "suppression_key": action["suppression_key"],
                "rationale": action["rationale"]
            }
            out_f.write(json.dumps(out) + "\n")
        else:
            print(f"No action for {test_id}")
            
print("Generated submission.jsonl")
