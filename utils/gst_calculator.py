# GST Calculator Utility

# Indian states with GST codes
INDIAN_STATES = {
    "Andhra Pradesh": "37", "Arunachal Pradesh": "12", "Assam": "18",
    "Bihar": "10", "Chhattisgarh": "22", "Goa": "30", "Gujarat": "24",
    "Haryana": "06", "Himachal Pradesh": "02", "Jharkhand": "20",
    "Karnataka": "29", "Kerala": "32", "Madhya Pradesh": "23",
    "Maharashtra": "27", "Manipur": "14", "Meghalaya": "17",
    "Mizoram": "15", "Nagaland": "13", "Odisha": "21", "Punjab": "03",
    "Rajasthan": "08", "Sikkim": "11", "Tamil Nadu": "33",
    "Telangana": "36", "Tripura": "16", "Uttar Pradesh": "09",
    "Uttarakhand": "05", "West Bengal": "19", "Delhi": "07",
    "Jammu and Kashmir": "01", "Ladakh": "38", "Chandigarh": "04",
    "Dadra and Nagar Haveli": "26", "Daman and Diu": "25",
    "Lakshadweep": "31", "Puducherry": "34", "Andaman and Nicobar": "35"
}

# Common HSN/SAC codes for freelancers
COMMON_HSN_SAC = {
    "998311": "IT Design & Development",
    "998312": "IT Software Development",
    "998313": "IT Maintenance & Support",
    "998314": "IT Infrastructure Services",
    "998315": "IT Consulting",
    "998316": "IT Testing & QA",
    "998371": "Accounting & Bookkeeping",
    "998372": "Tax & Audit Services",
    "998381": "Management Consulting",
    "998382": "Business Process Consulting",
    "9983":   "Other Professional Services",
    "9984":   "Telecommunications",
    "9985":   "Support Services",
    "998521": "Graphic Design",
    "998523": "Content Writing & Copywriting",
    "998591": "Digital Marketing",
    "998592": "SEO & SEM Services",
    "8523":   "Digital Products / Software",
}

# GST rate slabs
GST_RATES = [0, 5, 12, 18, 28]


def calculate_gst(base_amount: float, gst_rate: float, supplier_state: str, client_state: str):
    """
    Calculate GST based on supply type.
    Intra-state → CGST + SGST
    Inter-state → IGST
    """
    gst_amount = base_amount * gst_rate / 100

    if supplier_state and client_state and supplier_state.strip() == client_state.strip():
        # Intra-state supply
        cgst = round(gst_amount / 2, 2)
        sgst = round(gst_amount - cgst, 2)  # use remainder to avoid ₹0.01 paise drift
        igst = 0.0
        gst_type = "CGST_SGST"
    else:
        # Inter-state supply
        cgst = 0.0
        sgst = 0.0
        igst = round(gst_amount, 2)
        gst_type = "IGST"

    total = round(base_amount + gst_amount, 2)

    return {
        "base_amount": round(base_amount, 2),
        "gst_rate": gst_rate,
        "gst_type": gst_type,
        "cgst": cgst,
        "sgst": sgst,
        "igst": igst,
        "gst_amount": round(gst_amount, 2),
        "total": total
    }


def validate_gstin(gstin: str) -> bool:
    """Basic GSTIN format validation: 15 chars, alphanumeric"""
    if not gstin:
        return True  # Optional field
    gstin = gstin.strip().upper()
    if len(gstin) != 15:
        return False
    import re
    pattern = r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$'
    return bool(re.match(pattern, gstin))


def get_state_from_gstin(gstin: str) -> str:
    """Extract state from GSTIN first 2 digits"""
    if not gstin or len(gstin) < 2:
        return ""
    code = gstin[:2]
    for state, sc in INDIAN_STATES.items():
        if sc == code:
            return state
    return ""


def number_to_words(amount: float) -> str:
    """Convert amount to Indian number words (for invoice)"""
    ones = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine',
            'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen',
            'Seventeen', 'Eighteen', 'Nineteen']
    tens = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']

    def _below_1000(n):
        if n < 20:
            return ones[n]
        elif n < 100:
            return tens[n // 10] + (' ' + ones[n % 10] if n % 10 else '')
        else:
            return ones[n // 100] + ' Hundred' + (' and ' + _below_1000(n % 100) if n % 100 else '')

    def _convert(n):
        """Recursive conversion supporting full Indian number system."""
        if n == 0:
            return ''
        elif n < 1000:
            return _below_1000(n)
        elif n < 100000:
            return _below_1000(n // 1000) + ' Thousand' + (' ' + _below_1000(n % 1000) if n % 1000 else '')
        elif n < 10000000:
            # Use _convert for the lakh remainder so sub-lakh thousands are handled correctly
            return _convert(n // 100000) + ' Lakh' + (' ' + _convert(n % 100000) if n % 100000 else '')
        else:
            return _convert(n // 10000000) + ' Crore' + (' ' + _convert(n % 10000000) if n % 10000000 else '')

    n = int(amount)
    paise = round((amount - n) * 100)

    result = 'Rupees ' + (_convert(n) if n > 0 else 'Zero')
    if paise:
        result += f' and {paise} Paise'
    result += ' Only'
    return result
