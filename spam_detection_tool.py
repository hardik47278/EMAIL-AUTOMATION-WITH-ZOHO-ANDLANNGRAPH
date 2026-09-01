import tldextract
import whois
import dns.resolver
import requests
import os
from datetime import datetime
from langchain_core.tools import tool

@tool
def extract_domain(email: str) -> str:
    """Extract clean domain from email address"""
    domain_raw = email.split("@")[-1].strip().lower()
    ext = tldextract.extract(domain_raw)
    return f"{ext.domain}.{ext.suffix}" if ext.suffix else ext.domain

@tool
def get_whois_info(domain: str) -> dict:
    """Get WHOIS info (registrar, country, age)"""
    try:
        w = whois.whois(domain)

        creation_date = w.creation_date
        if isinstance(creation_date, list):
            creation_date = creation_date[0]

        age_days = None
        if creation_date:
            age_days = (datetime.now() - creation_date).days

        return {
            "registrar": str(w.registrar),
            "country": str(w.country),
            "creation_date": str(creation_date),
            "age_days": age_days
        }

    except Exception as e:
        return {"error": str(e)}


@tool
def dns_checks(domain: str) -> dict:
    """Check DNS records (MX, A, TXT)"""
    result = {}

    try:
        mx = dns.resolver.resolve(domain, "MX")
        result["mx_records"] = [str(r.exchange).rstrip(".") for r in mx]
    except:
        result["mx_records"] = []

    try:
        a = dns.resolver.resolve(domain, "A")
        result["a_records"] = [str(r) for r in a]
    except:
        result["a_records"] = []

    try:
        txt = dns.resolver.resolve(domain, "TXT")
        result["txt_records"] = [str(r) for r in txt]
    except:
        result["txt_records"] = []

    return result


VT_API_KEY = os.getenv("VT_API_KEY")


@tool
def virustotal_check(domain: str) -> dict:
    """Check domain reputation using VirusTotal"""
    try:
        url = f"https://www.virustotal.com/api/v3/domains/{domain}"
        headers = {"x-apikey": VT_API_KEY}

        res = requests.get(url, headers=headers)
        data = res.json()

        stats = data["data"]["attributes"]["last_analysis_stats"]

        return {
            "malicious": stats.get("malicious", 0),
            "suspicious": stats.get("suspicious", 0),
            "harmless": stats.get("harmless", 0),
            "undetected": stats.get("undetected", 0)
        }

    except Exception as e:
        return {"error": str(e)}