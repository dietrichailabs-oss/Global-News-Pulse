"""Read-only projection of retained GDELT codes, separate from verified news.

Country names use GDELT's published FIPS lookup, never ISO-code guessing or
provider centroids. Source: https://data.gdeltproject.org/blog/mapping-global-refugee-flows/COUNTRY-GEO-LOOKUP.TXT
Reviewed 2026-11-11. Conflicting GV/LO entries and unsupported map territories
are deliberately not resolved. No country severity or crisis is inferred.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import re
import sqlite3
import time
from .crisis_overlay import normalize_country
from .security import safe_url

# Labels transcribed from the provider's lookup; centroids intentionally omitted.
# Historical/ambiguous entries are not silently replaced with ISO equivalents.
_FIPS = '''AF|Afghanistan
AL|Albania
AG|Algeria
AO|Angola
AR|Argentina
AM|Armenia
AS|Australia
AU|Austria
AJ|Azerbaijan
BF|The Bahamas
BA|Bahrain
BG|Bangladesh
BB|Barbados
BO|Belarus
BE|Belgium
BH|Belize
BN|Benin
BT|Bhutan
BL|Bolivia
BK|Bosnia-Herzegovina
BC|Botswana
BR|Brazil
BX|Brunei
BU|Bulgaria
UV|Burkina Faso
BY|Burundi
CB|Cambodia
CM|Cameroon
CA|Canada
CV|Cape Verde
CT|Central African Republic
CD|Chad
CI|Chile
CH|China
CO|Colombia
CN|Comoros
CF|Congo
CS|Costa Rica
IV|Cote d'Ivoire
HR|Croatia
CU|Cuba
CY|Cyprus
EZ|Czech Republic
DA|Denmark
DJ|Djibouti
DR|Dominican Republic
TT|East Timor
EC|Ecuador
EG|Egypt
ES|El Salvador
ER|Eritrea
EN|Estonia
ET|Ethiopia
FJ|Fiji
FI|Finland
FR|France
GB|Gabon
GA|Gambia
GG|Georgia
GM|Germany
GH|Ghana
GR|Greece
GT|Guatemala
PU|Guinea-Bissau
GY|Guyana
HA|Haiti
HO|Honduras
HU|Hungary
IC|Iceland
IN|India
ID|Indonesia
IR|Iran
IZ|Iraq
EI|Ireland
IS|Israel
IT|Italy
JM|Jamaica
JA|Japan
JO|Jordan
KZ|Kazakhstan
KE|Kenya
KN|North Korea
KS|South Korea
KU|Kuwait
KG|Kyrgyzstan
LA|Laos
LG|Latvia
LE|Lebanon
LT|Lesotho
LI|Liberia
LY|Libya
LH|Lithuania
LU|Luxembourg
MK|Macedonia
MA|Madagascar
MI|Malawi
MY|Malaysia
MV|Maldives
ML|Mali
MT|Malta
MR|Mauritania
MP|Mauritius
MX|Mexico
MD|Moldova
MG|Mongolia
MO|Morocco
MZ|Mozambique
BM|Myanmar
WA|Namibia
NP|Nepal
NL|Netherlands
NZ|New Zealand
NU|Nicaragua
NG|Niger
NI|Nigeria
NO|Norway
MU|Oman
PK|Pakistan
PM|Panama
PP|Papua New Guinea
PA|Paraguay
PE|Peru
RP|Philippines
PL|Poland
PO|Portugal
QA|Qatar
RO|Romania
RS|Russia
RW|Rwanda
SA|Saudi Arabia
SG|Senegal
RI|Serbia
SL|Sierra Leone
SN|Singapore
SI|Slovenia
BP|Solomon Islands
SO|Somalia
SF|South Africa
SP|Spain
CE|Sri Lanka
SU|Sudan
NS|Suriname
WZ|Swaziland
SW|Sweden
SZ|Switzerland
SY|Syria
TW|Taiwan
TI|Tajikistan
TZ|Tanzania
TH|Thailand
TO|Togo
TD|Trinidad and Tobago
TS|Tunisia
TU|Turkey
TX|Turkmenistan
UG|Uganda
UP|Ukraine
AE|United Arab Emirates
UK|United Kingdom
US|United States
UY|Uruguay
UZ|Uzbekistan
VE|Venezuela
VM|Vietnam
YM|Yemen
CG|Democratic Republic of the Congo
ZA|Zambia
ZI|Zimbabwe
MJ|Montenegro
NH|Vanuatu
OD|South Sudan
KV|Kosovo
EK|Equatorial Guinea
WI|Western Sahara
NC|New Caledonia
GL|Greenland'''
FIPS_NAMES = dict(line.split('|', 1) for line in _FIPS.splitlines())
NAME_ALIASES = {'thebahamas':'bahamas', 'bosniaherzegovina':'bosniaandherz',
                'centralafricanrepublic':'centralafricanrep', 'easttimor':'timorleste',
                'macedonia':'northmacedonia', 'swaziland':'eswatini'}
MAX_ROWS = 20000


def _moment(value):
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value).replace('Z','+00:00'))
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def empty(state='empty', message='No retained GDELT observations in this date window.'):
    return dict(state=state,message=message,countries={},records=[],examined=0,
                unmapped=0,invalid=0,truncated=False,latest_batch='',legacy_batches=0)


def project(connection, country_names, *, since=None, now=None, limit=MAX_ROWS):
    """Read only existing tables; no schema creation, writes, HTTP or alerts.

    The row cap is a visible sample limit, NOT a claim of complete coverage.
    SQLite work is interrupted on a finite instruction/time allowance. No
    progress handler is installed on the caller's shared connection: callers
    should supply the dedicated read-only connection used by read_archive.
    """
    moment = _moment(now) if now is not None else datetime.now(timezone.utc)
    start = _moment(since) if since else moment-timedelta(days=7)
    if type(limit) is not int or not 1 <= limit <= MAX_ROWS:
        raise ValueError('Invalid GDELT display limit')
    if start > moment:
        return empty()
    names = {normalize_country(name): name for name in country_names}
    tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {'gdelt_event_rows','gdelt_batches'} <= tables:
        return empty('missing','No GDELT batches stored. Enable batch collection separately in Settings.')
    columns={r[1] for r in connection.execute('PRAGMA table_info(gdelt_batches)')}
    # Baseline/no-version and explicit version1 use the correct52/53 fields.
    # Prototype version2 was an erroneous off-by-one implementation. Preserve
    # its rows without rendering them or claiming they have been repaired.
    version_clause=''
    legacy=0
    if 'parser_version' in columns:
        version_clause=' AND COALESCE(b.parser_version,1)=1'
        legacy=connection.execute("SELECT COUNT(*) FROM gdelt_batches WHERE status='complete' AND kind='export' AND COALESCE(parser_version,1)!=1").fetchone()[0]
    upper = moment.strftime('%Y%m%d%H%M%S')
    lower = start.strftime('%Y%m%d%H%M%S')
    rows = connection.execute(f'''SELECT r.global_event_id,r.batch_timestamp,r.event_day,r.date_added,
        r.event_code,r.quad_class,r.action_country_code,r.action_location,r.source_article_url,b.imported_at
        FROM gdelt_event_rows r JOIN gdelt_batches b ON b.filename=r.filename
        WHERE b.status='complete' AND b.kind='export' {version_clause} AND r.batch_timestamp=b.batch_timestamp
        AND r.batch_timestamp>=? AND r.batch_timestamp<=? AND r.date_added<=?
        AND r.event_day>=? AND r.event_day<=?
        ORDER BY r.batch_timestamp DESC,r.global_event_id LIMIT ?''',
        (lower,upper,upper,start.strftime('%Y%m%d'),moment.strftime('%Y%m%d'),limit+1)).fetchall()
    result = empty()
    result['legacy_batches']=legacy
    result['truncated'] = len(rows)>limit
    for row in rows[:limit]:
        result['examined'] += 1
        identity,batch,day,added,code,quad,fips,location,url,imported = row
        try:
            if not re.fullmatch(r'[0-9]{1,20}',identity) or not re.fullmatch(r'[0-9]{1,4}',code):
                raise ValueError('Invalid identity')
            if quad not in ('1','2','3','4') or not re.fullmatch(r'[A-Z]{2}',fips):
                raise ValueError('Invalid coded value')
            for value,fmt,length in ((day,'%Y%m%d',8),(added,'%Y%m%d%H%M%S',14),(batch,'%Y%m%d%H%M%S',14)):
                if not re.fullmatch('[0-9]{'+str(length)+'}',value):raise ValueError('Invalid date')
                datetime.strptime(value,fmt)
            if _moment(imported)>moment:raise ValueError('Future import')
            if not isinstance(location,str) or len(location)>256 or any(ord(c)<32 for c in location):
                raise ValueError('Invalid label')
            url = safe_url(url)
        except (ValueError,TypeError,OverflowError):
            result['invalid'] += 1
            continue
        source_name=FIPS_NAMES.get(fips,'')
        key=normalize_country(source_name)
        key=NAME_ALIASES.get(key,key)
        country=names.get(normalize_country(source_name),'') or names.get(key,'')
        if not country:
            result['unmapped'] += 1
        record=dict(id=identity,batch=batch,event_day=day,date_added=added,event_code=code,
                    quad_class=quad,fips=fips,country=country,location=location,url=url)
        result['records'].append(record)
        result['latest_batch']=max(result['latest_batch'],batch)
        if country:
            group=result['countries'].setdefault(
                normalize_country(country),
                dict(name=country,count=0,material_conflict=0,protest=0),
            )
            group['count']+=1
            # CAMEO QuadClass 4 is material conflict. Root code 14 is protest.
            # These remain automated coded observations, never verified crises.
            if quad=='4':
                group['material_conflict']+=1
            if code.startswith('14'):
                group['protest']+=1
    result['state']='ready' if result['records'] else 'empty'
    result['message']=(f"{len(result['records'])} retained coded observations · {len(result['countries'])} countries · "
        f"{result['unmapped']} unlocated · {result['invalid']} invalid excluded. Not verified crises.")
    if result['truncated']:result['message']+=' Display sample capped; more retained rows may match.'
    if legacy:result['message']+=f' {legacy} prototype/unsupported parser batch(es) preserved but excluded.'
    return result


def read_archive(database, country_names, *, since=None, now=None):
    """Dedicated read-only bounded connection; never create or mutate the archive."""
    from pathlib import Path
    connection=None
    try:
        path=Path(database).absolute()
        if not path.is_file():return empty('missing','No local GDELT archive is available.')
        connection=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=.1)
        connection.execute('PRAGMA query_only=ON')
        deadline=time.monotonic()+.25
        steps=0
        def budget():
            nonlocal steps
            steps+=1
            return int(steps>1000 or time.monotonic()>deadline)
        connection.set_progress_handler(budget,10000)
        return project(connection,country_names,since=since,now=now)
    except (sqlite3.Error,OSError,ValueError,TypeError):
        return empty('unavailable','GDELT display unavailable or read budget reached; no old layer is shown.')
    finally:
        if connection is not None:connection.close()
