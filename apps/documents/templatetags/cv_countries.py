"""ISO 3166-1 alpha-2 to English country name, for CV rendering.

The schema stores and validates two-letter codes; a human-read CV must not
say "Berlin, DE". Same pattern as cv_dates.py's month table: the mapping is
carried here, fixed, so the same content renders the same bytes on any
server regardless of locale. Common names over official ones ("Russia", not
"Russian Federation") -- this text faces an admissions reader, not a treaty.
An unknown code falls back to itself rather than guessing.
"""

from __future__ import annotations

from django import template

register = template.Library()

_PAIRS = """
AD:Andorra;AE:United Arab Emirates;AF:Afghanistan;AG:Antigua and Barbuda;AI:Anguilla
AL:Albania;AM:Armenia;AO:Angola;AQ:Antarctica;AR:Argentina;AS:American Samoa;AT:Austria
AU:Australia;AW:Aruba;AX:Aland Islands;AZ:Azerbaijan;BA:Bosnia and Herzegovina;BB:Barbados
BD:Bangladesh;BE:Belgium;BF:Burkina Faso;BG:Bulgaria;BH:Bahrain;BI:Burundi;BJ:Benin
BL:Saint Barthelemy;BM:Bermuda;BN:Brunei;BO:Bolivia;BQ:Bonaire;BR:Brazil;BS:Bahamas
BT:Bhutan;BV:Bouvet Island;BW:Botswana;BY:Belarus;BZ:Belize;CA:Canada;CC:Cocos Islands
CD:DR Congo;CF:Central African Republic;CG:Congo;CH:Switzerland;CI:Ivory Coast
CK:Cook Islands;CL:Chile;CM:Cameroon;CN:China;CO:Colombia;CR:Costa Rica;CU:Cuba
CV:Cabo Verde;CW:Curacao;CX:Christmas Island;CY:Cyprus;CZ:Czechia;DE:Germany
DJ:Djibouti;DK:Denmark;DM:Dominica;DO:Dominican Republic;DZ:Algeria;EC:Ecuador
EE:Estonia;EG:Egypt;EH:Western Sahara;ER:Eritrea;ES:Spain;ET:Ethiopia;FI:Finland
FJ:Fiji;FK:Falkland Islands;FM:Micronesia;FO:Faroe Islands;FR:France;GA:Gabon
GB:United Kingdom;GD:Grenada;GE:Georgia;GF:French Guiana;GG:Guernsey;GH:Ghana
GI:Gibraltar;GL:Greenland;GM:Gambia;GN:Guinea;GP:Guadeloupe;GQ:Equatorial Guinea
GR:Greece;GS:South Georgia;GT:Guatemala;GU:Guam;GW:Guinea-Bissau;GY:Guyana
HK:Hong Kong;HM:Heard Island;HN:Honduras;HR:Croatia;HT:Haiti;HU:Hungary
ID:Indonesia;IE:Ireland;IL:Israel;IM:Isle of Man;IN:India;IO:British Indian Ocean Territory
IQ:Iraq;IR:Iran;IS:Iceland;IT:Italy;JE:Jersey;JM:Jamaica;JO:Jordan;JP:Japan
KE:Kenya;KG:Kyrgyzstan;KH:Cambodia;KI:Kiribati;KM:Comoros;KN:Saint Kitts and Nevis
KP:North Korea;KR:South Korea;KW:Kuwait;KY:Cayman Islands;KZ:Kazakhstan;LA:Laos
LB:Lebanon;LC:Saint Lucia;LI:Liechtenstein;LK:Sri Lanka;LR:Liberia;LS:Lesotho
LT:Lithuania;LU:Luxembourg;LV:Latvia;LY:Libya;MA:Morocco;MC:Monaco;MD:Moldova
ME:Montenegro;MF:Saint Martin;MG:Madagascar;MH:Marshall Islands;MK:North Macedonia
ML:Mali;MM:Myanmar;MN:Mongolia;MO:Macao;MP:Northern Mariana Islands;MQ:Martinique
MR:Mauritania;MS:Montserrat;MT:Malta;MU:Mauritius;MV:Maldives;MW:Malawi;MX:Mexico
MY:Malaysia;MZ:Mozambique;NA:Namibia;NC:New Caledonia;NE:Niger;NF:Norfolk Island
NG:Nigeria;NI:Nicaragua;NL:Netherlands;NO:Norway;NP:Nepal;NR:Nauru;NU:Niue
NZ:New Zealand;OM:Oman;PA:Panama;PE:Peru;PF:French Polynesia;PG:Papua New Guinea
PH:Philippines;PK:Pakistan;PL:Poland;PM:Saint Pierre and Miquelon;PN:Pitcairn
PR:Puerto Rico;PS:Palestine;PT:Portugal;PW:Palau;PY:Paraguay;QA:Qatar;RE:Reunion
RO:Romania;RS:Serbia;RU:Russia;RW:Rwanda;SA:Saudi Arabia;SB:Solomon Islands
SC:Seychelles;SD:Sudan;SE:Sweden;SG:Singapore;SH:Saint Helena;SI:Slovenia
SJ:Svalbard;SK:Slovakia;SL:Sierra Leone;SM:San Marino;SN:Senegal;SO:Somalia
SR:Suriname;SS:South Sudan;ST:Sao Tome and Principe;SV:El Salvador;SX:Sint Maarten
SY:Syria;SZ:Eswatini;TC:Turks and Caicos Islands;TD:Chad;TF:French Southern Territories
TG:Togo;TH:Thailand;TJ:Tajikistan;TK:Tokelau;TL:Timor-Leste;TM:Turkmenistan
TN:Tunisia;TO:Tonga;TR:Turkey;TT:Trinidad and Tobago;TV:Tuvalu;TW:Taiwan
TZ:Tanzania;UA:Ukraine;UG:Uganda;UM:US Minor Outlying Islands;US:United States
UY:Uruguay;UZ:Uzbekistan;VA:Vatican City;VC:Saint Vincent and the Grenadines
VE:Venezuela;VG:British Virgin Islands;VI:US Virgin Islands;VN:Vietnam;VU:Vanuatu
WF:Wallis and Futuna;WS:Samoa;YE:Yemen;YT:Mayotte;ZA:South Africa;ZM:Zambia;ZW:Zimbabwe
"""

_NAMES: dict[str, str] = dict(
    pair.split(":", 1) for line in _PAIRS.strip().splitlines() for pair in line.split(";")
)


@register.filter
def country_name(code: str | None) -> str:
    """None renders as nothing: ResearchEntry.country is optional, and a
    template that printed the literal "None" would be worse than silent."""
    return _NAMES.get(code or "", code or "")
