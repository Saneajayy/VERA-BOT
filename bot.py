import os
import time
from datetime import datetime
from typing import Any, List, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from composer import select_triggers, generate_message, lint_response, generate_reply
from conversation_handlers import detect_auto_reply, detect_intent, detect_hostility

app = FastAPI()
START = time.time()

# In-memory stores (per the challenge brief, this is acceptable for the test)
contexts: dict[tuple[str, str], dict] = {}    # (scope, context_id) -> {"version": int, "payload": dict}
conversations: dict[str, dict] = {}           # conversation_id -> {"turns": list, "last_bodies": list}
suppressed_keys: set = set()                  # set of used suppression_keys

@app.get("/v1/healthz")
async def healthz():
    counts = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
    for (scope, _), _ in contexts.items():
        counts[scope] = counts.get(scope, 0) + 1
    return {"status": "ok", "uptime_seconds": int(time.time() - START), "contexts_loaded": counts}

@app.get("/v1/metadata")
async def metadata():
    return {
        "team_name": "Antigravity",
        "team_members": ["Antigravity"],
        "model": "Gemini 3.5 Flash",
        "approach": "Deterministic trigger selection with grounded LLM templating and safety linting",
        "contact_email": "antigravity@example.com",
        "version": "1.0.0",
        "submitted_at": datetime.utcnow().isoformat() + "Z"
    }

class CtxBody(BaseModel):
    scope: str
    context_id: str
    version: int
    payload: dict[str, Any]
    delivered_at: str

@app.post("/v1/context")
async def push_context(body: CtxBody):
    key = (body.scope, body.context_id)
    cur = contexts.get(key)
    
    if body.scope not in ["category", "merchant", "customer", "trigger"]:
        return {"accepted": False, "reason": "invalid_scope", "details": f"Unknown scope {body.scope}"}
        
    if cur:
        if cur["version"] == body.version:
            return {
                "accepted": True,
                "ack_id": f"ack_{body.context_id}_v{body.version}",
                "stored_at": datetime.utcnow().isoformat() + "Z"
            }
        elif cur["version"] > body.version:
            return {"accepted": False, "reason": "stale_version", "current_version": cur["version"]}
        
    contexts[key] = {"version": body.version, "payload": body.payload}
    return {
        "accepted": True,
        "ack_id": f"ack_{body.context_id}_v{body.version}",
        "stored_at": datetime.utcnow().isoformat() + "Z"
    }

class TickBody(BaseModel):
    now: str
    available_triggers: List[str] = []

@app.post("/v1/tick")
async def tick(body: TickBody):
    actions = []
    
    # 1. Select triggers (deterministically score and filter)
    selected_triggers = select_triggers(body.available_triggers, contexts)
    
    # Process up to 20 actions max to stay within the limit and budget
    valid_triggers = []
    for trg_id in selected_triggers:
        trg = contexts.get(("trigger", trg_id), {}).get("payload")
        if not trg:
            continue
        key = trg.get("suppression_key", f"{trg_id}_suppress")
        if key in suppressed_keys:
            continue
        valid_triggers.append(trg_id)
    
    for trg_id in valid_triggers[:20]:
        trg = contexts.get(("trigger", trg_id), {}).get("payload")
        if not trg: continue
            
        merchant_id = trg.get("merchant_id")
        customer_id = trg.get("customer_id")
        
        merchant = contexts.get(("merchant", merchant_id), {}).get("payload")
        category = contexts.get(("category", merchant.get("category_slug")), {}).get("payload") if merchant else None
        customer = contexts.get(("customer", customer_id), {}).get("payload") if customer_id else None
        
        if not (merchant and category): continue
            
        # Determine send_as
        send_as = "merchant_on_behalf" if customer_id else "vera"
        
        # 2. Generate grounded message
        conversation_id = f"conv_{merchant_id}_{trg_id}"
        
        # Check if conversation already has too many repeats (defensive)
        conv = conversations.get(conversation_id, {"turns": [], "last_bodies": []})
        
        body_text, cta, rationale = generate_message(
            category=category,
            merchant=merchant,
            trigger=trg,
            customer=customer,
            contexts=contexts
        )
        
        # 3. Lint the response (safety gate)
        lint_result = lint_response(body_text, category, conv.get("last_bodies", []))
        if not lint_result["valid"]:
            from composer import get_fallback_message
            body_text, cta, rationale = get_fallback_message(category, merchant, trg, customer)
        else:
            body_text = lint_result["body"] # might be cleaned
        
        action = {
            "conversation_id": conversation_id,
            "merchant_id": merchant_id,
            "customer_id": customer_id,
            "send_as": send_as,
            "trigger_id": trg_id,
            "template_name": "vera_generic_v1",
            "template_params": [],
            "body": body_text,
            "cta": cta,
            "suppression_key": trg.get("suppression_key", f"{trg_id}_suppress"),
            "rationale": rationale
        }
        
        # Update conversation state
        if conversation_id not in conversations:
            conversations[conversation_id] = {"turns": [], "last_bodies": []}
        conversations[conversation_id]["last_bodies"].append(body_text)
        
        suppressed_keys.add(action["suppression_key"])
        actions.append(action)
        
    return {"actions": actions}

class ReplyBody(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: str
    message: str
    received_at: str
    turn_number: int

@app.post("/v1/reply")
async def reply(body: ReplyBody):
    conv = conversations.setdefault(body.conversation_id, {"turns": [], "last_bodies": []})
    conv["turns"].append({"from": body.from_role, "msg": body.message})
    
    if detect_hostility(body.message):
        return {
            "action": "end",
            "rationale": "Merchant is hostile or off-topic. Gracefully exiting."
        }

    # 1. Detect auto-reply
    auto_reply_count = detect_auto_reply(conv["turns"])
    if auto_reply_count >= 3:
        return {
            "action": "end",
            "rationale": "Auto-reply 3x in a row, no real reply. Conversation has zero engagement signal; closing."
        }
    elif auto_reply_count == 2:
        return {
            "action": "wait",
            "wait_seconds": 86400,
            "rationale": "Same auto-reply twice in a row. Wait 24h before retry."
        }
    intent = "normal_reply"
    if auto_reply_count == 1:
        if "automated assistant" in body.message.lower() or "auto-reply" in body.message.lower() or "team will respond" in body.message.lower():
            intent = "auto_reply"
        
    if detect_intent(body.message):
        intent = "intent_transition"
        
    merchant = contexts.get(("merchant", body.merchant_id), {}).get("payload") if body.merchant_id else {}
    category = contexts.get(("category", merchant.get("category_slug")), {}).get("payload") if merchant else {}
    customer = contexts.get(("customer", body.customer_id), {}).get("payload") if body.customer_id else None
    
    body_text, cta, rationale = generate_reply(category, merchant, customer, body.message, intent, conv["turns"])
    
    # Lint reply
    lint_res = lint_response(body_text, category, conv["last_bodies"])
    if not lint_res["valid"]:
        from composer import get_fallback_reply
        body_text, cta, rationale = get_fallback_reply(category, merchant, customer, body.message, intent)
    
    return {
        "action": "send",
        "body": body_text,
        "cta": cta,
        "rationale": rationale
    }

@app.post("/v1/teardown")
async def teardown():
    contexts.clear()
    conversations.clear()
    suppressed_keys.clear()
    return {"status": "cleared"}
