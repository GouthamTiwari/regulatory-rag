"""Spell out common regulatory abbreviations before routing and searching.

Why: a short question like "What is RCM?" gives keyword search nothing to match (the
circulars mostly write "reverse charge" in full), gives the embedding very little meaning,
and gives the router no corpus hint. "What is RCM (reverse charge mechanism)?" fixes all
three. Only abbreviations that appear in the corpus and have a single meaning there are
listed; ambiguous ones (AD, PoS, SEZ) are left out on purpose.
"""

import re

GLOSSARY: dict[str, str] = {
    # GST
    "RCM": "reverse charge mechanism",
    "ITC": "input tax credit",
    "TCS": "tax collected at source",
    "ISD": "input service distributor",
    "LUT": "letter of undertaking",
    "OIDAR": "online information database access and retrieval services",
    "CBIC": "Central Board of Indirect Taxes and Customs",
    # RBI
    "PSL": "priority sector lending",
    "ANBC": "adjusted net bank credit",
    "CEOBE": "credit equivalent of off-balance sheet exposure",
    "KYC": "know your customer",
    "OVD": "officially valid document",
    "CKYCR": "Central KYC Records Registry",
    "NBFC": "non-banking financial company",
    "PPI": "prepaid payment instrument",
    "LRS": "liberalised remittance scheme",
    "FEMA": "Foreign Exchange Management Act",
    "MSME": "micro, small and medium enterprises",
    "UPI": "unified payments interface",
    "NEFT": "national electronic funds transfer",
    "RTGS": "real time gross settlement",
    "BBPS": "Bharat Bill Payment System",
    "KFS": "key facts statement",
    "APR": "annual percentage rate",
    "EMI": "equated monthly instalment",
    "NPA": "non-performing asset",
}

# Upper-case whole words only, with an optional plural "s" (NBFCs, PPIs). Matching is
# case-sensitive so ordinary words ("emi", "apr") in lower case are never touched.
_PATTERN = re.compile(r"\b(" + "|".join(sorted(GLOSSARY, key=len, reverse=True)) + r")(s?)\b")


def expand_abbreviations(question: str) -> str:
    """Add the full form after the first use of each known abbreviation.

    Skipped when the question already contains the full form, so a question that is
    already clear is returned unchanged.
    """
    seen: set[str] = set()

    def add_full_form(match: re.Match) -> str:
        abbr, plural = match.group(1), match.group(2)
        full = GLOSSARY[abbr]
        if abbr in seen or full.lower() in question.lower():
            return match.group(0)
        seen.add(abbr)
        return f"{abbr}{plural} ({full})"

    return _PATTERN.sub(add_full_form, question)
