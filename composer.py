import os
import re
import json
import google.generativeai as genai
from typing import List, Tuple, Dict, Any
from datetime import datetime

# Initialize Gemini if key exists
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    
def select_triggers(available_triggers: List[str], contexts: dict) -> List[str]:
    """
    Deterministically scores and selects the top triggers to act upon.
    Returns max 20 triggers.
    """
    scored = []
    for t_id in available_triggers:
        trg_wrapper = contexts.get(("trigger", t_id))
        if not trg_wrapper: continue
        trg = trg_wrapper.get("payload", {})
        
        # Base urgency
        urgency = trg.get("urgency", 1)
        
        # If it expires soon, bump urgency
        expires_at = trg.get("expires_at")
        if expires_at:
            try:
                # ISO8601 parsing
                exp = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                if (exp - datetime.utcnow()).total_seconds() < 86400: # 1 day
                    urgency += 2
            except:
                pass
                
        scored.append((urgency, t_id))
        
    # Sort by urgency descending
    scored.sort(key=lambda x: x[0], reverse=True)
    return [t_id for _, t_id in scored[:20]]

def get_fallback_message(category: dict, merchant: dict, trigger: dict, customer: dict = None) -> Tuple[str, str, str]:
    """
    Provides a deterministic fallback message if the LLM fails or is unavailable.
    """
    trigger_kind = trigger.get("kind", "")
    merchant_name = merchant.get("identity", {}).get("name", "there")
    
    if customer:
        cust_name = customer.get("identity", {}).get("name", "there")
        if trigger_kind == "recall_due":
            body = f"Hi {cust_name}, {merchant_name} here. It's time for your scheduled visit. Are you available this week?"
            cta = "open_ended"
            rationale = "Fallback recall message."
            return body, cta, rationale
            
    # Merchant facing fallback
    if trigger_kind == "research_digest":
        body = f"Hi {merchant_name}, we noticed some new research in your field. Would you like a quick summary?"
        cta = "binary_yes_no"
        rationale = "Fallback research digest."
        return body, cta, rationale
        
    body = f"Hi {merchant_name}, we noticed some recent activity on your profile. Reply YES if you'd like to review it."
    cta = "binary_yes_no"
    rationale = "Fallback generic trigger."
    return body, cta, rationale

def generate_message(category: dict, merchant: dict, trigger: dict, customer: dict, contexts: dict) -> Tuple[str, str, str]:
    """
    Calls the LLM (Gemini) to generate the message based on rules, or uses a fallback.
    Returns: (body, cta, rationale)
    """
    if not GEMINI_API_KEY:
        return get_fallback_message(category, merchant, trigger, customer)
        
    model = genai.GenerativeModel('gemini-3.5-flash')
    
    # Extract taboos
    taboos = category.get("voice", {}).get("taboos", [])
    if "vocab_taboo" in category.get("voice", {}):
        taboos = category.get("voice", {}).get("vocab_taboo", [])
        
    taboos_str = ", ".join(taboos)
    
    # Language preference
    target_audience = customer if customer else merchant
    langs = target_audience.get("identity", {}).get("languages", ["en"])
    lang_pref = target_audience.get("identity", {}).get("language_pref", "English")
    
    if "hi" in langs or "hindi" in lang_pref.lower() or "hi-en" in lang_pref.lower():
        language_instruction = "Use Hindi-English code-mix (Hinglish). This is VERY important for Indian merchants."
    else:
        language_instruction = "Use English."

    # CTA Instruction
    cta_instruction = "Include EXACTLY ONE Call-To-Action (CTA) at the very end. Make it either a binary choice (Reply YES) or an open-ended question."
        
    prompt = f"""
    You are 'Vera', an AI assistant helping a merchant on WhatsApp. 
    You must compose a short, highly-engaging WhatsApp message to the target based on the context provided.
    
    Context:
    - Target: {'Customer (' + customer.get('identity', {}).get('name', '') + ')' if customer else 'Merchant (' + merchant.get('identity', {}).get('name', '') + ')'}
    - Category Voice: {json.dumps(category.get('voice', {}))}
    - Trigger (Why now?): {json.dumps(trigger)}
    - Merchant Snapshot: {json.dumps(merchant.get('performance', {}))}
    - Merchant Offers: {json.dumps(merchant.get('offers', []))}
    
    CRITICAL RULES:
    1. DO NOT use any of these taboo words: {taboos_str}
    2. NEVER include a URL in the message. (Hard rule)
    3. Use specific numbers/facts from the context, do not hallucinate them.
    4. {language_instruction}
    5. {cta_instruction}
    6. Use one compulsion lever: specificity, loss aversion, social proof, curiosity, reciprocity, or effort externalization.
    
    Return the response as a JSON object with exactly these 3 keys:
    {{
        "body": "The WhatsApp message text.",
        "cta": "open_ended" or "binary_yes_no" or "none",
        "rationale": "Why you chose this framing."
    }}
    """
    
    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                candidate_count=1,
                max_output_tokens=300,
                temperature=0.0, # Deterministic
                response_mime_type="application/json",
            ),
        )
        data = json.loads(response.text)
        return data["body"], data.get("cta", "open_ended"), data.get("rationale", "Generated by LLM")
    except Exception as e:
        print(f"LLM Generation Error: {e}")
        return get_fallback_message(category, merchant, trigger, customer)

def lint_response(body: str, category: dict, history_bodies: List[str]) -> Dict[str, Any]:
    """
    Post-generation safety gate. Returns {"valid": bool, "body": str}.
    """
    # 1. URL Check (Hard -3 penalty)
    if "http://" in body or "https://" in body or "www." in body:
        # Try to strip URL
        body = re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '', body)
        if "http" in body: # if still there
            return {"valid": False, "body": body}

    # 2. Taboo Check
    taboos = category.get("voice", {}).get("taboos", [])
    if "vocab_taboo" in category.get("voice", {}):
        taboos = category.get("voice", {}).get("vocab_taboo", [])
        
    body_lower = body.lower()
    for taboo in taboos:
        if re.search(r'\b' + re.escape(taboo.lower()) + r'\b', body_lower):
            # Replace taboo or fail
            return {"valid": False, "body": body}

    # 3. Repetition Check
    if body in history_bodies:
        return {"valid": False, "body": body}
        
    # 4. Multiple CTA Check (heuristic: more than one 'reply' or '?')
    # If it asks too many questions, it might be penalized, but hard to regex perfectly.
    
    return {"valid": True, "body": body.strip()}

def get_fallback_reply(category: dict, merchant: dict, customer: dict, message: str, intent: str) -> Tuple[str, str, str]:
    merchant_name = merchant.get("identity", {}).get("name", "there") if merchant else "there"
    if intent == "intent_transition":
        return f"Great {merchant_name}, let's do it! I've initiated the setup process for you. You'll receive a confirmation shortly.", "none", "Merchant showed explicit intent to proceed."
    elif intent == "auto_reply":
        return f"Looks like an auto-reply 😊 When the owner sees this, just reply 'Yes'.", "binary_yes_no", "Detected auto-reply; one explicit prompt to flag it for the owner."
    return f"Got it {merchant_name}. Let me know if you need anything else or have questions!", "none", "Generic fallback reply."

def generate_reply(category: dict, merchant: dict, customer: dict, message: str, intent: str, history: List[dict]) -> Tuple[str, str, str]:
    if not GEMINI_API_KEY:
        return get_fallback_reply(category, merchant, customer, message, intent)
        
    model = genai.GenerativeModel('gemini-3.5-flash')
    taboos = category.get("voice", {}).get("taboos", [])
    if "vocab_taboo" in category.get("voice", {}):
        taboos = category.get("voice", {}).get("vocab_taboo", [])
    
    target = customer if customer else merchant
    if not target:
        return get_fallback_reply(category, merchant, customer, message, intent)
        
    langs = target.get("identity", {}).get("languages", ["en"])
    lang_pref = target.get("identity", {}).get("language_pref", "English")
    
    if "hi" in langs or "hindi" in lang_pref.lower() or "hi-en" in lang_pref.lower():
        lang_inst = "Use Hindi-English code-mix (Hinglish)."
    else:
        lang_inst = "Use English."

    hist_str = json.dumps(history[-3:])
    
    if intent == "intent_transition":
        system_goal = "The user just explicitly agreed to proceed. Switch to action mode immediately. Acknowledge and state the next step using specific facts from their profile."
        cta = "none"
    elif intent == "auto_reply":
        system_goal = "This seems to be an automated assistant replying. Ask a simple question to get the real owner's attention."
        cta = "binary_yes_no"
    else:
        system_goal = "Respond politely to the latest message. Do not ask qualifying questions if they are engaged."
        cta = "none"

    prompt = f"""
    You are 'Vera', an AI assistant on WhatsApp. 
    Target: {json.dumps(target.get('identity', {}))}
    Category Voice: {json.dumps(category.get('voice', {}))}
    Offers: {json.dumps(merchant.get('offers', []) if merchant else [])}
    Recent History: {hist_str}
    User's latest message: "{message}"
    
    Goal: {system_goal}
    
    CRITICAL RULES:
    1. DO NOT use these taboo words: {", ".join(taboos)}
    2. NEVER include a URL.
    3. {lang_inst}
    4. Use specific numbers/facts from context.
    
    Return exactly:
    {{
        "body": "Your text",
        "cta": "{cta}",
        "rationale": "Why you said this"
    }}
    """
    
    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                candidate_count=1,
                max_output_tokens=200,
                temperature=0.0,
                response_mime_type="application/json",
            ),
        )
        data = json.loads(response.text)
        return data["body"], data.get("cta", cta), data.get("rationale", system_goal)
    except Exception as e:
        print(f"LLM Reply Error: {e}")
        return get_fallback_reply(category, merchant, customer, message, intent)
