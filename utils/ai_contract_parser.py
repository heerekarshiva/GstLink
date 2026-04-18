import os
import json
import re

def parse_contract_with_ai(contract_text: str) -> dict:
    """
    Parse contract text using Groq (primary) with regex fallback.
    Groq is fast, free, and supports llama3 models.
    """
    groq_key = os.environ.get('GROQ_API_KEY', '')

    if groq_key:
        return _parse_with_groq(contract_text, groq_key)
    else:
        return _parse_with_regex(contract_text)


def _parse_with_groq(contract_text: str, api_key: str) -> dict:
    """Use Groq (llama-3.3-70b-versatile) to extract invoice fields — fast & free"""
    try:
        from groq import Groq

        client = Groq(api_key=api_key)

        prompt = f"""You are an expert Indian GST invoice assistant.

Extract the following fields from this contract/agreement text.
Return ONLY a valid JSON object with these exact keys (no explanation, no markdown):

{{
  "client_name": "Full name or company name of the client",
  "client_gstin": "15-char Indian GSTIN or null if not found",
  "amount": 50000,
  "description": "Short 1-2 line service description",
  "hsn_sac": "HSN/SAC code (use 998312 for software, 998521 for design, 998523 for writing, 998591 for digital marketing, 998315 for consulting)",
  "payment_terms": "e.g. Net 30 days",
  "state": "Client state in India or null",
  "due_days": 30
}}

Contract text:
---
{contract_text[:3000]}
---

Respond with ONLY the JSON object."""

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=500
        )

        raw = response.choices[0].message.content.strip()
        # Strip markdown fences if model adds them
        raw = re.sub(r'^```json?\s*', '', raw, flags=re.MULTILINE)
        raw = re.sub(r'\s*```$', '', raw, flags=re.MULTILINE)
        raw = raw.strip()

        result = json.loads(raw)
        result['source'] = 'groq'
        return result

    except json.JSONDecodeError:
        # Groq responded but JSON was malformed — try regex
        return {**_parse_with_regex(contract_text), 'source': 'regex_fallback'}
    except Exception:
        # Never expose internal exception details (paths, versions, config) to callers
        return {**_parse_with_regex(contract_text), 'source': 'regex_fallback'}


def _parse_with_regex(contract_text: str) -> dict:
    """Fallback: basic regex-based extraction when no API key is set"""
    result = {
        'client_name': None,
        'client_gstin': None,
        'amount': None,
        'description': None,
        'hsn_sac': '998312',
        'payment_terms': 'Net 30 days',
        'state': None,
        'due_days': 30,
        'source': 'regex'
    }

    # GSTIN pattern (15-char Indian format)
    gstin_match = re.search(
        r'\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}\b',
        contract_text, re.IGNORECASE
    )
    if gstin_match:
        result['client_gstin'] = gstin_match.group().upper()

    # Amount patterns (Indian format with ₹, Rs, INR)
    amount_patterns = [
        r'(?:Rs\.?|INR|₹)\s*([0-9,]+(?:\.[0-9]{2})?)',
        r'([0-9,]+(?:\.[0-9]{2})?)\s*(?:rupees|INR)',
        r'(?:amount|total|fee|value)[:\s]+(?:Rs\.?|INR|₹)?\s*([0-9,]+(?:\.[0-9]{2})?)',
    ]
    for pattern in amount_patterns:
        match = re.search(pattern, contract_text, re.IGNORECASE)
        if match:
            try:
                result['amount'] = float(match.group(1).replace(',', ''))
                break
            except ValueError:
                pass

    # HSN/SAC code if explicitly mentioned
    hsn_match = re.search(r'(?:HSN|SAC)[:\s#]+([0-9]{4,8})', contract_text, re.IGNORECASE)
    if hsn_match:
        result['hsn_sac'] = hsn_match.group(1)
    else:
        # Guess from keywords
        text_lower = contract_text.lower()
        if any(k in text_lower for k in ['software', 'development', 'coding', 'app', 'website']):
            result['hsn_sac'] = '998312'
            result['description'] = 'Software Development Services'
        elif any(k in text_lower for k in ['design', 'ui', 'ux', 'graphic', 'logo']):
            result['hsn_sac'] = '998521'
            result['description'] = 'Design Services'
        elif any(k in text_lower for k in ['content', 'writing', 'copywriting', 'blog', 'article']):
            result['hsn_sac'] = '998523'
            result['description'] = 'Content Writing Services'
        elif any(k in text_lower for k in ['marketing', 'seo', 'digital', 'ads', 'social media']):
            result['hsn_sac'] = '998591'
            result['description'] = 'Digital Marketing Services'
        elif any(k in text_lower for k in ['consult', 'advisory', 'strategy', 'management']):
            result['hsn_sac'] = '998315'
            result['description'] = 'Consulting Services'
        else:
            result['description'] = 'Professional Services'

    # Indian states detection
    indian_states = [
        'Maharashtra', 'Delhi', 'Karnataka', 'Tamil Nadu', 'Gujarat',
        'Rajasthan', 'Uttar Pradesh', 'West Bengal', 'Telangana', 'Kerala',
        'Andhra Pradesh', 'Haryana', 'Madhya Pradesh', 'Punjab', 'Bihar',
        'Goa', 'Odisha', 'Assam', 'Jharkhand', 'Chhattisgarh'
    ]
    for state in indian_states:
        if state.lower() in contract_text.lower():
            result['state'] = state
            break

    # Payment due days
    due_match = re.search(r'(\d+)\s*days?', contract_text, re.IGNORECASE)
    if due_match:
        days = int(due_match.group(1))
        if 7 <= days <= 90:
            result['due_days'] = days

    return result
