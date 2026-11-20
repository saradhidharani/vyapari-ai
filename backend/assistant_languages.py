import re
import unicodedata


SALES_LANGUAGES = {
    "hi": {
        "all_time": "कुल शुद्ध बिक्री",
        "net_sales": "शुद्ध बिक्री",
        "payments": "प्राप्त भुगतान",
        "refunds": "रिफंड",
        "all_aliases": ("कुल", "शुद्ध", "कुल शुद्ध"),
        "pattern": re.compile(
            r"(?:(?P<period>.+?) (?:की |के )?)?"
            r"(?:कुल |शुद्ध )?बिक्री(?: का सारांश| कितनी हुई| कितनी है| कैसी रही)?(?: बताएं| बताइए)?"
        ),
        "periods": {
            "today": ("आज",),
            "yesterday": ("बीते कल",),
            "this week": ("इस हफ्ते", "इस सप्ताह"),
            "last week": ("पिछले हफ्ते", "पिछले सप्ताह"),
            "last 7 days": ("पिछले 7 दिन", "पिछले 7 दिनों", "पिछले सात दिन", "पिछले सात दिनों"),
            "this month": ("इस महीने", "इस माह"),
            "last month": ("पिछले महीने", "पिछले माह"),
        },
    },
    "te": {
        "all_time": "మొత్తం నికర అమ్మకాలు",
        "net_sales": "నికర అమ్మకాలు",
        "payments": "అందిన చెల్లింపులు",
        "refunds": "తిరిగి చెల్లించిన మొత్తం",
        "all_aliases": ("మొత్తం", "నికర", "మొత్తం నికర"),
        "pattern": re.compile(
            r"(?:(?P<period>.+?) )?(?:మొత్తం |నికర )?"
            r"అమ్మకాలు(?: ఎంత| ఎంత ఉన్నాయి| ఎలా ఉన్నాయి| ఎలా జరిగాయి| చెప్పండి)?"
        ),
        "periods": {
            "today": ("ఈరోజు", "ఈ రోజు", "నేడు"),
            "yesterday": ("నిన్న",),
            "this week": ("ఈ వారం",),
            "last week": ("గత వారం", "పోయిన వారం"),
            "last 7 days": ("గత 7 రోజులు", "గత 7 రోజుల", "గత ఏడు రోజుల"),
            "this month": ("ఈ నెల",),
            "last month": ("గత నెల", "పోయిన నెల"),
        },
    },
}


BUSINESS_LANGUAGES = {
    "hi": {
        "prompts": {
            "स्टॉक का सारांश": "inventory summary",
            "कुल स्टॉक": "inventory summary",
            "कम स्टॉक वाले उत्पाद": "low stock",
            "हाल के ऑर्डर": "recent orders",
            "ग्राहकों की संख्या": "customer count",
            "मेरे कितने ग्राहक हैं": "customer count",
        },
        "stock_pattern": r"(.+) का स्टॉक(?: कितना है)?",
        "order_pattern": r"ऑर्डर #?(?:ord-)?(\d{1,19})(?: की स्थिति)?",
        "inventory": "{count} उत्पाद · स्टॉक में {units} इकाइयाँ · तय स्टॉक सीमा से नीचे {low} उत्पाद।",
        "no_low": "कोई उत्पाद अपनी तय स्टॉक सीमा से नीचे नहीं है।",
        "low": "तय स्टॉक सीमा से नीचे वाले उत्पाद",
        "low_limited": "तय स्टॉक सीमा से नीचे वाले पहले 10 उत्पाद",
        "stock_line": "{name} · स्टॉक में {stock}",
        "product_missing": "आपकी सूची में इस नाम का कोई उत्पाद नहीं मिला।",
        "product_multiple": "इस नाम के कई उत्पाद हैं। अलग-अलग स्टॉक देखने के लिए Products खोलें।",
        "product_stock": "{name} के स्टॉक में {stock} इकाइयाँ हैं।",
        "customer_count": "आपके व्यवसाय में {count} ग्राहक संपर्क दर्ज हैं।",
        "recent_orders": "सबसे हाल के ऑर्डर:",
        "no_orders": "आपके व्यवसाय में कोई ऑर्डर दर्ज नहीं है।",
        "order_missing": "आपके व्यवसाय में यह ऑर्डर नहीं मिला।",
        "order_label": "ऑर्डर ",
        "help": "इनमें से कोई सवाल पूछें: आज की बिक्री, कुल स्टॉक, कम स्टॉक वाले उत्पाद, हाल के ऑर्डर या ग्राहकों की संख्या।",
        "statuses": {"Pending": "भुगतान बाकी", "Paid": "भुगतान हुआ", "Cancelled": "रद्द", "Refunded": "रिफंड हुआ"},
    },
    "te": {
        "prompts": {
            "స్టాక్ వివరాలు": "inventory summary",
            "మొత్తం స్టాక్": "inventory summary",
            "తక్కువ స్టాక్ ఉన్న ఉత్పత్తులు": "low stock",
            "ఇటీవలి ఆర్డర్లు": "recent orders",
            "కస్టమర్ల సంఖ్య": "customer count",
            "నా కస్టమర్లు ఎంతమంది": "customer count",
        },
        "stock_pattern": r"(.+) స్టాక్(?: ఎంత(?: ఉంది)?)?",
        "order_pattern": r"ఆర్డర్ #?(?:ord-)?(\d{1,19})(?: స్థితి)?",
        "inventory": "{count} ఉత్పత్తులు · స్టాక్‌లో {units} యూనిట్లు · నిర్ణయించిన స్టాక్ పరిమితి కంటే తక్కువగా ఉన్న ఉత్పత్తులు {low}.",
        "no_low": "ఏ ఉత్పత్తి స్టాక్ కూడా దాని నిర్ణీత పరిమితి కంటే తక్కువగా లేదు.",
        "low": "నిర్ణీత స్టాక్ పరిమితి కంటే తక్కువగా ఉన్న ఉత్పత్తులు",
        "low_limited": "నిర్ణీత స్టాక్ పరిమితి కంటే తక్కువగా ఉన్న మొదటి 10 ఉత్పత్తులు",
        "stock_line": "{name} · స్టాక్‌లో {stock}",
        "product_missing": "మీ ఉత్పత్తుల జాబితాలో ఈ పేరుతో ఏ ఉత్పత్తీ కనిపించలేదు.",
        "product_multiple": "ఈ పేరుతో ఒకటి కంటే ఎక్కువ ఉత్పత్తులు ఉన్నాయి. వాటి స్టాక్ చూడటానికి Products తెరవండి.",
        "product_stock": "{name} స్టాక్‌లో {stock} యూనిట్లు ఉన్నాయి.",
        "customer_count": "మీ వ్యాపారంలో {count} కస్టమర్ సంప్రదింపు వివరాలు నమోదై ఉన్నాయి.",
        "recent_orders": "ఇటీవలి ఆర్డర్లు:",
        "no_orders": "మీ వ్యాపారంలో ఆర్డర్లు ఏవీ నమోదు కాలేదు.",
        "order_missing": "ఈ ఆర్డర్ మీ వ్యాపారంలో కనిపించలేదు.",
        "order_label": "ఆర్డర్ ",
        "help": "ఇలా అడగండి: ఈరోజు అమ్మకాలు, మొత్తం స్టాక్, తక్కువ స్టాక్ ఉన్న ఉత్పత్తులు, ఇటీవలి ఆర్డర్లు లేదా కస్టమర్ల సంఖ్య.",
        "statuses": {"Pending": "చెల్లింపు పెండింగ్", "Paid": "చెల్లించారు", "Cancelled": "రద్దు చేశారు", "Refunded": "నగదు తిరిగి చెల్లించారు"},
    },
}


def localized_business_query(query: str, language: str):
    pack = BUSINESS_LANGUAGES[language]
    if query in pack["prompts"]:
        return pack["prompts"][query]
    stock = re.fullmatch(pack["stock_pattern"], query)
    if stock:
        return f"stock for {stock.group(1)}"
    order = re.fullmatch(pack["order_pattern"], query)
    if order:
        return f"order {int(order.group(1))}"
    return None


def question_language(question: str):
    if re.search(r"[\u0c00-\u0c7f]", question):
        return "te"
    if re.search(r"[\u0900-\u097f]", question):
        return "hi"
    return None


def localized_sales_period(query: str, language: str):
    normalized = unicodedata.normalize("NFC", query)
    normalized = "".join(
        str(unicodedata.decimal(character)) if character.isdecimal() else character
        for character in normalized
    )
    pack = SALES_LANGUAGES[language]
    match = pack["pattern"].fullmatch(normalized)
    if not match:
        return None
    alias = match.group("period")
    if alias is None or alias in pack["all_aliases"]:
        return "all"
    if language == "hi" and alias == "कल" and normalized.endswith(("कितनी हुई", "कैसी रही")):
        return "yesterday"
    return next((period for period, aliases in pack["periods"].items() if alias in aliases), None)
