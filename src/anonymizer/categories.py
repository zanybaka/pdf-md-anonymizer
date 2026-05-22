"""Detection category identifiers."""
from __future__ import annotations

from enum import StrEnum


class Category(StrEnum):
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    INN = "INN"
    SNILS = "SNILS"
    OGRN = "OGRN"
    OGRNIP = "OGRNIP"
    KPP = "KPP"
    BIK = "BIK"
    ACCOUNT = "ACCOUNT"
    CARD = "CARD"
    DOB = "DOB"
    POSTAL_CODE = "POSTAL_CODE"
    ADDRESS = "ADDRESS"
    PASSPORT = "PASSPORT"
    IP = "IP"
    URL = "URL"
    SECRET = "SECRET"
    ORG = "ORG"
    PERSON = "PERSON"
    LOC = "LOC"
    NICKNAME = "NICKNAME"
