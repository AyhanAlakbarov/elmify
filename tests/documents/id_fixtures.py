# tests/documents/id_fixtures.py
"""Azure prebuilt-idDocument answers with a strip whose check digits are real."""

from apps.documents.azure_layout import AzureIdResult
from apps.documents.mrz import check_digit


def td3(*, surname="ALIYEVA", given="NARMIN", number="C01X00T47", nationality="AZE",
        birth="980314", sex="F", expiry="310519", personal="", issuing="AZE") -> str:
    names = f"{surname}<<{given.replace(' ', '<')}"
    first = f"P<{issuing}{names}".ljust(44, "<")[:44]
    number_field = number.ljust(9, "<")
    personal_field = personal.ljust(14, "<")
    second = (
        f"{number_field}{check_digit(number_field)}{nationality}{birth}{check_digit(birth)}"
        f"{sex}{expiry}{check_digit(expiry)}{personal_field}{check_digit(personal_field)}"
    )
    composite = second[0:10] + second[13:20] + second[21:43]
    return f"{first}\n{second}{check_digit(composite)}"


def td1(*, surname="ALIYEVA", given="NARMIN", number="AZE123456", nationality="AZE",
        birth="980314", sex="F", expiry="310519", issuing="AZE") -> str:
    """A three-line ID-card strip with real check digits."""
    one = f"I<{issuing}{number.ljust(9, '<')}{check_digit(number.ljust(9, '<'))}".ljust(30, "<")
    two = (f"{birth}{check_digit(birth)}{sex}{expiry}{check_digit(expiry)}{nationality}"
           + "<" * 11)
    composite = one[5:30] + two[0:7] + two[8:15] + two[18:29]
    two += check_digit(composite)
    three = f"{surname}<<{given.replace(' ', '<')}".ljust(30, "<")[:30]
    return f"{one}\n{two}\n{three}"


def field(value, *, kind="string", confidence=0.99, offset=0):
    key = {"string": "valueString", "date": "valueDate",
           "countryRegion": "valueCountryRegion"}[kind]
    return {"type": kind, key: value, "content": value, "confidence": confidence,
            "spans": [{"offset": offset, "length": len(value)}]}


def result(fields: dict, *, doc_type="idDocument.passport", word_confidence=0.99,
           strip: str | None = None) -> AzureIdResult:
    """`fields` maps Azure field names to field() dicts; words are generated so
    every field's span is covered at `word_confidence`."""
    words, text, offset = [], [], 0
    built = {}
    for name, spec in fields.items():
        content = spec["content"]
        spec = {**spec, "spans": [{"offset": offset, "length": len(content)}]}
        words.append({"content": content, "confidence": word_confidence,
                      "span": {"offset": offset, "length": len(content)}})
        text.append(content)
        offset += len(content) + 1
        built[name] = spec
    if strip is not None:
        built["MachineReadableZone"] = {"type": "object", "content": strip, "confidence": 0.99}
    return AzureIdResult.model_validate({
        "content": " ".join(text),
        "pages": [{"pageNumber": 1, "width": 1, "height": 1, "unit": "inch", "words": words}],
        "documents": [{"docType": doc_type, "confidence": 0.99, "fields": built}],
    })


def passport(**overrides):
    """A clean passport whose printed page agrees with its strip."""
    printed = {
        "LastName": field("ƏLIYEVA"), "FirstName": field("NƏRMIN"),
        "DocumentNumber": field("C01X00T47"), "DateOfBirth": field("1998-03-14", kind="date"),
        "DateOfExpiration": field("2031-05-19", kind="date"),
        "DateOfIssue": field("2021-05-20", kind="date"), "Sex": field("F"),
        "Nationality": field("AZE", kind="countryRegion"),
        "CountryRegion": field("AZE", kind="countryRegion"),
        "PlaceOfBirth": field("BAKU"), "IssuingAuthority": field("MIA"),
    }
    strip_args = overrides.pop("strip_args", {})
    printed.update(overrides.pop("fields", {}))
    return result(printed, strip=td3(**strip_args), **overrides)
