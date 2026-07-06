import re
from typing import List

def detect_auto_reply(turns: List[dict]) -> int:
    """
    Detects if the merchant is stuck in an auto-reply loop.
    Returns the count of consecutive identical messages from the merchant.
    """
    merchant_msgs = [turn["msg"] for turn in turns if turn["from"] == "merchant"]
    if not merchant_msgs:
        return 0
        
    last_msg = merchant_msgs[-1]
    count = 1
    for msg in reversed(merchant_msgs[:-1]):
        if msg == last_msg:
            count += 1
        else:
            break
    return count

def detect_intent(message: str) -> bool:
    """
    Detects explicit commitment language indicating the merchant wants to proceed.
    Transitions to action mode.
    """
    intent_keywords = [
        r"let'?s do it",
        r"\bgo ahead\b",
        r"\bok proceed\b",
        r"\bdo it\b",
        r"i want to join",
        r"update (my|the) profile",
        r"please check & update",
        r"sure, go ahead"
    ]
    
    msg_lower = message.lower()
    for keyword in intent_keywords:
        if re.search(keyword, msg_lower):
            return True
    return False

def detect_hostility(message: str) -> bool:
    """
    Detects hostility or off-topic abuse from the merchant.
    """
    hostile_keywords = [
        r"\bstop\b",
        r"\bunsubscribe\b",
        r"\bspam\b",
        r"leave me alone",
        r"don'?t contact",
        r"not interested",
        r"fuck",
        r"shut up",
        r"bakwas",
        r"pareshan"
    ]
    
    msg_lower = message.lower()
    for keyword in hostile_keywords:
        if re.search(keyword, msg_lower):
            return True
    return False
