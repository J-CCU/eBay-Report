"""
CCU eBay listing report + buyer-block audit  (READ-ONLY: never edits eBay or Shopify)

Run (from anywhere):
    python ccu_ebay_report.py                      # asks which account when config.yaml has more than one
    python ccu_ebay_report.py --account <name>     # a specific account (CCU or a seller_accounts entry)
    python ccu_ebay_report.py --limit 20           # quick test on the first 20 listings
    python ccu_ebay_report.py --refresh-shopify    # ignore the cached Shopify pull

Reads config.yaml from the same folder as this script (or --config PATH).
Writes to ./ccu_report_output/:
    requested_fields_<account>_<stamp>.csv  only the requested fields (plus item number/title), one row per listing/variation
    ebay_report_<account>_<stamp>.csv   requested fields plus working columns
    audit_<account>_<stamp>.csv         one row per problem that can stop a buyer checking out
    changes_<account>_<stamp>.csv       every field that changed since the previous run
    snapshot_<account>_<stamp>.json     raw values used for the next change comparison
    errors_<account>_<stamp>.log        API errors, if any
Only Python's standard library is used.
"""
import argparse, base64, collections, csv, datetime as dt, glob, json, os, re, ssl, subprocess, sys, time
import urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

MAC = sys.platform == "darwin"


def app_folder():
    """Where config.yaml and ccu_report_output live: next to the .py, the .exe, or the Mac program."""
    if not getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(__file__))
    here = os.path.dirname(os.path.realpath(sys.executable))
    p = here
    while os.path.dirname(p) != p:      # .../X.app/Contents/MacOS/X -> the folder holding X.app
        if p.endswith(".app"):
            here = os.path.dirname(p)
            break
        p = os.path.dirname(p)
    return here if os.access(here, os.W_OK) else os.path.join(os.path.expanduser("~"), "Downloads")


def mac_certificates():
    """python.org Python on macOS has no certificate store of its own; use certifi's (bundled in the Mac build)."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except (ImportError, OSError, ssl.SSLError):
        return None


HERE = app_folder()
OUT = os.path.join(HERE, "ccu_report_output")
SSL_CTX = mac_certificates() if MAC else None
HOME = os.path.expanduser("~")
CONFIG_DIRS = [HERE, os.path.join(HOME, "Downloads"), os.path.join(HOME, "Documents"),
               os.path.join(HOME, "Documents", "Commerce Intel")]
SHOPIFY_API = "2026-07"
TRADING_URL = "https://api.ebay.com/ws/api.dll"
COMPAT = "1349"
NS = {"e": "urn:ebay:apis:eBLBaseComponents"}
CONSIGNMENT_MARKUP = 0.05          # % increase rule for consignment
PRICE_TOL = 0.006                  # ratio tolerance when matching a price rule
CARD_CATEGORIES = {"183454", "261328", "183050"}   # CCG Individual Cards, Sports / Non-Sport Trading Card Singles
GRADED_ID, UNGRADED_ID = "2750", "4000"
DEFAULT_ACCOUNT = "cashcardsunlimited"   # the only account allowed to use the top-level ebay tokens

# ---- Condition descriptor IDs (eBay trading cards). Unknown IDs are written as "id:<n>". ----
DESC_NAMES = {"27501": "Professional Grader", "27502": "Grade", "27503": "Certification Number", "40001": "Card Condition"}
GRADER = {"275010": "Professional Sports Authenticator (PSA)", "275011": "Beckett Collectors Club Grading (BCCG)",
          "275012": "Beckett Vintage Grading (BVG)", "275013": "Beckett Grading Services (BGS)",
          "275014": "Certified Sports Guaranty (CSG)", "275015": "Certified Guaranty Company (CGC)",
          "275016": "Sportscard Guaranty Corporation (SGC)", "275017": "K Sportscard Authentication (KSA)",
          "275018": "Gem Mint Authentication (GMA)", "275019": "Hybrid Grading Approach (HGA)",
          "2750110": "International Sports Authentication (ISA)", "2750111": "Professional Card Authenticator (PCA)",
          "2750112": "Gold Standard Grading (GSG)", "2750113": "Platin Grading Service (PGS)",
          "2750114": "MNT Grading (MNT)", "2750115": "Technical Authentication & Grading (TAG)",
          "2750116": "Rare Edition (Rare)", "2750117": "Revolution Card Grading (RCG)",
          "2750118": "Premier Card Grading (PCG)", "2750119": "Ace Grading (Ace)",
          "2750120": "Card Grading Australia (CGA)", "2750121": "Trading Card Grading (TCG)",
          "2750122": "ARK Grading (ARK)", "2750123": "Other"}
GRADE = {"275020": "10", "275021": "9.5", "275022": "9", "275023": "8.5", "275024": "8", "275025": "7.5",
         "275026": "7", "275027": "6.5", "275028": "6", "275029": "5.5", "2750210": "5", "2750211": "4.5",
         "2750212": "4", "2750213": "3.5", "2750214": "3", "2750215": "2.5", "2750216": "2", "2750217": "1.5",
         "2750218": "1", "2750219": "Authentic", "2750220": "Authentic Altered", "2750221": "Authentic - Trimmed",
         "2750222": "Authentic - Coloured"}
CARD_COND = {"400010": "Near mint or better", "400011": "Excellent", "400012": "Very good", "400013": "Poor",
             "400015": "Lightly played (Excellent)", "400016": "Moderately played (Very good)",
             "400017": "Heavily played (Poor)"}
VALUE_MAPS = {"27501": GRADER, "27502": GRADE, "40001": CARD_COND}

# ---- requested fields, in the requested order ----
SHIPPING = ["Shipping Cost type", "Service", "Package Weight (oz)", "Package Size (in)"]
PRICE = ["Operator", "Input", "Rounding", "Result"]
SPECIFICS = ["Brand", "Franchise", "Game", "Grade", "Graded", "Language", "Manufacturer", "Set", "Sport"]
RECOMMENDED = ["Autographed", "Card Name", "Card Number", "Card Type", "Character", "Features", "League",
               "Player/Athlete", "Signed By", "Team", "Finish", "Rarity"]
OPTIONAL = ["Card Condition", "HP", "Professional Grader", "Stage", "Year Manufactured"]
CONDITION = ["eBay Condition", "Condition: Card Condition", "Condition: Professional Grader", "Condition: Grade",
             "Certification Number"]
LEAD = ["Item Number", "Title", "SKU", "Variation", "Category", "Available Qty", "eBay Price"]
PRICE_EXTRA = ["Price Rule Basis", "Shopify Price", "Shopify Vendor", "Shopify Qty", "Shopify Match"]
TAIL = ["Issues", "Changed Since Last Run"]
SPEC_COLS = SPECIFICS + RECOMMENDED + OPTIONAL
_is = lambda c: f"IS: {c}" if c in ("Grade", "Card Condition", "Professional Grader") else c
COLUMNS = (LEAD + SHIPPING + PRICE + [_is(c) for c in SPEC_COLS] + CONDITION
           + ["Category ID"] + PRICE_EXTRA + TAIL)
# Excel group headings (row 1) by requested category
GROUPS = [("Listing", LEAD), ("Shipping Fields", SHIPPING), ("Price", PRICE),
          ("Item Specifics", [_is(c) for c in SPECIFICS]), ("Recommended", RECOMMENDED),
          ("Optional", [_is(c) for c in OPTIONAL]), ("Condition", CONDITION),
          ("Reference (extra columns)", ["Category ID"] + PRICE_EXTRA + TAIL)]


# ------------------------------------------------------------------ Excel (.xlsx) writer, standard library only
def _col(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26); s = chr(65 + r) + s
    return s


def _esc(v):
    v = "" if v is None else str(v)
    v = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", v)[:32000]
    return v.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _sheet_xml(rows, header_rows, widths):
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
           f'<sheetViews><sheetView workbookViewId="0"><pane xSplit="2" ySplit="{header_rows}" '
           f'topLeftCell="C{header_rows + 1}" activePane="bottomRight" state="frozen"/></sheetView></sheetViews><cols>']
    for i, w in enumerate(widths, 1):
        out.append(f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>')
    out.append("</cols><sheetData>")
    for ri, row in enumerate(rows, 1):
        style = 1 if ri <= header_rows else 0
        cells = []
        for ci, v in enumerate(row, 1):
            ref = f"{_col(ci)}{ri}"
            if isinstance(v, (int, float)) and not isinstance(v, bool) and ri > header_rows:
                cells.append(f'<c r="{ref}" s="{style}"><v>{v}</v></c>')
            elif v not in ("", None):
                cells.append(f'<c r="{ref}" s="{style}" t="inlineStr"><is><t xml:space="preserve">{_esc(v)}</t></is></c>')
        out.append(f'<row r="{ri}">{"".join(cells)}</row>')
    last = f"{_col(len(widths))}{max(len(rows), header_rows)}"
    out.append(f'</sheetData><autoFilter ref="A{header_rows}:{last}"/></worksheet>')
    return "".join(out)


def write_xlsx(path, sheets):
    """sheets: list of (name, rows, header_rows, widths)"""
    import zipfile
    names = [s[0] for s in sheets]
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
          '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
          + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                    for i in range(1, len(sheets) + 1)) + "</Types>")
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    wb = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
          + "".join(f'<sheet name="{_esc(n)}" sheetId="{i}" r:id="rId{i}"/>' for i, n in enumerate(names, 1))
          + "</sheets></workbook>")
    wbrels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
              + "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
                        for i in range(1, len(sheets) + 1))
              + f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
              '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
              '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
              '<fill><patternFill patternType="solid"><fgColor rgb="FFD9E1F2"/></patternFill></fill></fills>'
              '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
              '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
              '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/></cellXfs>'
              '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct); z.writestr("_rels/.rels", rels)
        z.writestr("xl/workbook.xml", wb); z.writestr("xl/_rels/workbook.xml.rels", wbrels)
        z.writestr("xl/styles.xml", styles)
        for i, (n, rows, hr, w) in enumerate(sheets, 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", _sheet_xml(rows, hr, w))


def display_all(c):
    return c.replace("SellingStatus > ", "").replace("PrimaryCategory > ", "Category ")


def display(c):
    return c.replace("IS: ", "").replace("Condition: ", "")


# ------------------------------------------------------------------ config
def has_ebay_section(path):
    try:
        return any(re.match(r"ebay:\s*(#.*)?$", line) for line in open(path, encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return False


def find_config(given=None, required=True):
    """--config if given, else the first config.yaml with an ebay section: next to the program, Downloads, Documents."""
    if given:
        return given
    for d in CONFIG_DIRS:
        for n in ("config.yaml", "config.yml"):
            if has_ebay_section(os.path.join(d, n)):
                return os.path.join(d, n)
    if not required:
        return None
    sys.exit("No config.yaml with an 'ebay:' section found. Put config.yaml next to this program "
             "(or in Downloads / Documents).\nLooked in:\n  " + "\n  ".join(CONFIG_DIRS))


def read_config(path):
    """Tiny YAML reader for this config's shape (nested keys, "quoted" values). No PyYAML needed."""
    if not os.path.exists(path):
        sys.exit(f"config.yaml not found: {path}\nPut config.yaml next to this program (or in Downloads / Documents).")
    root, stack = {}, [(-1, None)]
    stack[0] = (-1, root)
    for raw in open(path, encoding="utf-8"):
        q = re.match(r"""(\s*[^:#]+:\s*(?:"[^"]*"|'[^']*'))(.*)$""", raw)   # a quoted value may contain " #"
        line = "" if raw.strip().startswith("#") else (q.group(1) + q.group(2).split(" #")[0] if q else raw.split(" #")[0]).rstrip()
        if not line.strip():
            continue
        ind = len(line) - len(line.lstrip())
        m = re.match(r'\s*([^:]+):\s*(.*)$', line)
        if not m:
            continue
        key, val = m.group(1).strip(), m.group(2).strip()
        while stack and stack[-1][0] >= ind:
            stack.pop()
        parent = stack[-1][1]
        if val == "":
            parent[key] = {}
            stack.append((ind, parent[key]))
        else:
            parent[key] = val[1:-1] if val.startswith('"') and val.endswith('"') else val
    return root


def account_names(ecfg):
    """Accounts in config.yaml: every seller_accounts entry, plus CCU when it uses the top-level tokens."""
    names = list((ecfg.get("seller_accounts") or {}).keys())
    if (ecfg.get("refresh_token") or ecfg.get("user_token")) and DEFAULT_ACCOUNT not in names:
        names.insert(0, DEFAULT_ACCOUNT)
    return names


def choose_account(ecfg, given=None):
    """--account if given; otherwise the only account, or a numbered menu."""
    if given:
        return given
    names = account_names(ecfg)
    if not names:
        sys.exit("No eBay accounts in this config.yaml. Choose a config.yaml that has the eBay tokens, "
                 "or connect an account with 'Connect eBay Account.bat'.")
    if len(names) == 1:
        print(f"eBay account: {names[0]}")
        return names[0]
    print("Which eBay account?")
    for i, n in enumerate(names, 1):
        print(f"  {i}. {n}")
    while True:
        try:
            a = input(f"Type a number (1-{len(names)}) and press Enter: ").strip()
        except EOFError:
            sys.exit("No account chosen.")
        if a.isdigit() and 1 <= int(a) <= len(names):
            return names[int(a) - 1]
        if a in names:
            return a
        print("  That is not one of the choices, try again.")


# ------------------------------------------------------------------ http helpers
def http(url, data=None, headers=None, timeout=60, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers=headers or {})
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            body = e.read()[:600]
            if e.code in (429, 500, 502, 503) and i < tries - 1:
                time.sleep(3 * (i + 1)); continue
            raise RuntimeError(f"HTTP {e.code} from {url}: {body!r}")
        except urllib.error.URLError as e:
            if i < tries - 1:
                time.sleep(3); continue
            raise RuntimeError(f"Network error for {url}: {e}")


# ------------------------------------------------------------------ eBay
class Ebay:
    def __init__(self, cfg, account):
        self.app, self.dev, self.cert = cfg.get("app_id", ""), cfg.get("dev_id", ""), cfg.get("cert_id", "")
        sellers = cfg.get("seller_accounts") or {}
        if account not in sellers and account != DEFAULT_ACCOUNT:
            sys.exit(f"eBay: no account '{account}' in config.yaml. Accounts: {', '.join(account_names(cfg)) or 'none'}")
        acct = sellers.get(account) or {}
        own = account == DEFAULT_ACCOUNT          # other accounts never fall back to CCU's tokens
        self.oauth = None
        self.ana = acct.get("user_token") or (cfg.get("user_token", "") if own else "")
        rt = acct.get("refresh_token") or (cfg.get("refresh_token") if own else "")
        if rt:
            try:
                basic = base64.b64encode(f"{self.app}:{self.cert}".encode()).decode()
                body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": rt}).encode()
                j = json.loads(http("https://api.ebay.com/identity/v1/oauth2/token", body,
                                    {"Content-Type": "application/x-www-form-urlencoded",
                                     "Authorization": f"Basic {basic}"}))
                self.oauth = j["access_token"]
                print("eBay: OAuth token OK")
            except Exception as e:
                print(f"eBay: OAuth refresh failed ({e}); falling back to user_token")
        if not self.oauth and not self.ana:
            sys.exit(f"eBay: no usable token for '{account}'. Connect it with 'Connect eBay Account.bat', signed in as {account}.")
        if not self.oauth:
            print("eBay: using Auth'n'Auth user_token")
        # make sure the token really belongs to the chosen account before pulling anything
        expected = acct.get("ebay_user_id") or account
        root, _ = self.call("GetUser", "")
        uid = t(root, "e:User/e:UserID")
        if uid.lower() != expected.lower():
            sys.exit(f"eBay: the token for '{account}' signs in as '{uid}', not '{expected}'. Stopping so data isn't mixed up.")
        print(f"eBay: signed in as {uid}")

    def call(self, name, inner):
        creds = "" if self.oauth else f"<RequesterCredentials><eBayAuthToken>{self.ana}</eBayAuthToken></RequesterCredentials>"
        xml = (f'<?xml version="1.0" encoding="utf-8"?><{name}Request xmlns="urn:ebay:apis:eBLBaseComponents">'
               f"{creds}<ErrorLanguage>en_US</ErrorLanguage><WarningLevel>High</WarningLevel>{inner}</{name}Request>")
        h = {"X-EBAY-API-SITEID": "0", "X-EBAY-API-COMPATIBILITY-LEVEL": COMPAT, "X-EBAY-API-CALL-NAME": name,
             "Content-Type": "text/xml", "X-EBAY-API-APP-NAME": self.app, "X-EBAY-API-DEV-NAME": self.dev,
             "X-EBAY-API-CERT-NAME": self.cert}
        if self.oauth:
            h["X-EBAY-API-IAF-TOKEN"] = self.oauth
        root = ET.fromstring(http(TRADING_URL, xml.encode(), h))
        ack = t(root, "e:Ack")
        errs = [(t(x, "e:SeverityCode"), t(x, "e:ErrorCode"), t(x, "e:LongMessage")) for x in root.findall("e:Errors", NS)]
        if ack == "Failure":
            raise RuntimeError(f"{name} failed: {errs}")
        return root, errs

    def active_item_ids(self):
        ids, page, pages = [], 1, 1
        while page <= pages:
            root, _ = self.call("GetMyeBaySelling",
                f"<ActiveList><Include>true</Include><Pagination><EntriesPerPage>200</EntriesPerPage>"
                f"<PageNumber>{page}</PageNumber></Pagination></ActiveList>")
            al = root.find("e:ActiveList", NS)
            if al is None:
                break
            pages = int(t(al, "e:PaginationResult/e:TotalNumberOfPages") or 1)
            ids += [t(i, "e:ItemID") for i in al.findall("e:ItemArray/e:Item", NS)]
            page += 1
        return ids

    def get_item(self, item_id):
        root, errs = self.call("GetItem", f"<ItemID>{item_id}</ItemID><DetailLevel>ReturnAll</DetailLevel>"
                                          f"<IncludeItemSpecifics>true</IncludeItemSpecifics>")
        return root.find("e:Item", NS), errs


def t(node, path):
    if node is None:
        return ""
    x = node.find(path, NS)
    return (x.text or "").strip() if x is not None and x.text else ""


def name_values(node, path):
    out = {}
    for nv in (node.findall(path, NS) if node is not None else []):
        n = t(nv, "e:Name")
        vals = [v.text.strip() for v in nv.findall("e:Value", NS) if v.text]
        if n:
            out[n] = "; ".join(vals)
    return out


def parse_item(it):
    """Flatten a GetItem <Item> into the fields the report needs."""
    d = {"item_id": t(it, "e:ItemID"), "title": t(it, "e:Title"), "sku": t(it, "e:SKU"),
         "category": t(it, "e:PrimaryCategory/e:CategoryName"), "category_id": t(it, "e:PrimaryCategory/e:CategoryID"),
         "condition_id": t(it, "e:ConditionID"), "condition": t(it, "e:ConditionDisplayName"),
         "status": t(it, "e:SellingStatus/e:ListingStatus"), "format": t(it, "e:ListingType"),
         "price": t(it, "e:SellingStatus/e:CurrentPrice") or t(it, "e:StartPrice"),
         "qty": int(t(it, "e:Quantity") or 0) - int(t(it, "e:SellingStatus/e:QuantitySold") or 0),
         "ship_type": t(it, "e:ShippingDetails/e:ShippingType"),
         "ship_policy": t(it, "e:SellerProfiles/e:SellerShippingProfile/e:ShippingProfileName"),
         "specifics": name_values(it, "e:ItemSpecifics/e:NameValueList"), "descriptors": {}, "variations": []}
    svc = []
    for o in it.findall("e:ShippingDetails/e:ShippingServiceOptions", NS) if it is not None else []:
        s, c = t(o, "e:ShippingService"), t(o, "e:ShippingServiceCost")
        cost = "free" if t(o, "e:FreeShipping") == "true" else c or (
            "calculated" if "Calculated" in t(it, "e:ShippingDetails/e:ShippingType") else "?")
        svc.append(f"{s} ({cost})")
    d["services"] = "; ".join(svc)
    pk = it.find("e:ShippingPackageDetails", NS) if it is not None else None
    def num(path):
        try:
            return float(t(pk, path) or 0)
        except ValueError:
            return 0.0
    unit = t(pk, "e:MeasurementUnit") or "English"
    major, minor = num("e:WeightMajor"), num("e:WeightMinor")
    oz = major * 16 + minor if unit == "English" else (major * 1000 + minor) / 28.3495   # metric: kg + g
    dims = [num("e:PackageLength"), num("e:PackageWidth"), num("e:PackageDepth")]
    if unit != "English":
        dims = [x / 2.54 for x in dims]
    d["weight_oz"] = round(oz, 2)
    d["dims_in"] = dims
    d["package_type"] = t(pk, "e:ShippingPackage")
    for cd in it.findall("e:ConditionDescriptors/e:ConditionDescriptor", NS) if it is not None else []:
        n = t(cd, "e:Name")
        vals = [v.text.strip() for v in cd.findall("e:Value", NS) if v.text]
        info = t(cd, "e:AdditionalInfo")
        m = VALUE_MAPS.get(n, {})
        shown = "; ".join(m.get(v, f"id:{v}") if m else v for v in vals) or info
        d["descriptors"][DESC_NAMES.get(n, f"id:{n}")] = shown
    for v in it.findall("e:Variations/e:Variation", NS) if it is not None else []:
        d["variations"].append({
            "sku": t(v, "e:SKU"), "price": t(v, "e:StartPrice"),
            "qty": int(t(v, "e:Quantity") or 0) - int(t(v, "e:SellingStatus/e:QuantitySold") or 0),
            "specifics": name_values(v, "e:VariationSpecifics/e:NameValueList")})
    return d


# ------------------------------------------------------------------ every field eBay returns, one row per listing
SKIP_TREES = {"Seller", "ItemSpecifics", "ConditionDescriptors", "Variations", "Description", "PictureDetails",
              "BusinessSellerDetails", "ApplicationData"}
FIRST_FIELDS = ["ItemID", "Title", "SubTitle", "SKU", "ListingType", "SellingStatus > ListingStatus",
                "SellingStatus > CurrentPrice", "StartPrice", "BuyItNowPrice", "Quantity", "SellingStatus > QuantitySold",
                "PrimaryCategory > CategoryName", "PrimaryCategory > CategoryID", "Storefront > StoreCategoryID",
                "ConditionID", "ConditionDisplayName", "ConditionDescription"]


def _local(tag):
    return tag.split("}", 1)[-1]


def _flatten(el, prefix, out):
    for ch in el:
        name = _local(ch.tag)
        if not prefix and name in SKIP_TREES:
            continue
        key = f"{prefix} > {name}" if prefix else name
        if len(ch):
            _flatten(ch, key, out)
        else:
            val = (ch.text or "").strip()
            unit = ch.attrib.get("currencyID") or ch.attrib.get("unit") or ""
            if unit and val:
                val = f"{val} {unit}"
            if val:
                out[key] = f"{out[key]}; {val}" if key in out and val not in out[key].split("; ") else val


def all_fields(it):
    """Every field in the GetItem response for one listing, as {column: value}."""
    out = {}
    _flatten(it, "", out)
    for n, v in name_values(it, "e:ItemSpecifics/e:NameValueList").items():
        out[f"Item Specific: {n}"] = v
    d = parse_item(it)
    for n, v in d["descriptors"].items():
        out[f"Condition Detail: {n}"] = v
    pics = [p.text for p in it.findall("e:PictureDetails/e:PictureURL", NS) if p.text]
    out["Photos: Count"] = len(pics)
    out["Photos: URLs"] = " ".join(pics)
    if d["variations"]:
        out["Variations: Count"] = len(d["variations"])
        out["Variations: Detail"] = " || ".join(
            f"{v['sku'] or '(no SKU)'}: {', '.join(f'{k}={x}' for k, x in v['specifics'].items())} "
            f"@ {v['price']} qty {v['qty']}" for v in d["variations"])
    desc = t(it, "e:Description")
    if desc:
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", desc)).strip()
        out["Description (text)"] = text[:30000]
    out["Listing URL"] = t(it, "e:ListingDetails/e:ViewItemURL") or f"https://www.ebay.com/itm/{t(it, 'e:ItemID')}"
    return out


def order_all_columns(rows):
    seen = collections.Counter(k for r in rows for k in r)
    first = [c for c in FIRST_FIELDS if c in seen]
    spec = sorted((c for c in seen if c.startswith("Item Specific: ")), key=lambda c: (-seen[c], c))
    cond = sorted(c for c in seen if c.startswith("Condition Detail: "))
    extra = [c for c in ("Photos: Count", "Variations: Count", "Variations: Detail", "Listing URL") if c in seen]
    tail = [c for c in ("Photos: URLs", "Description (text)") if c in seen]
    used = set(first + spec + cond + extra + tail)
    rest = sorted(c for c in seen if c not in used)
    return first + spec + cond + extra + rest + tail


# ------------------------------------------------------------------ Shopify
def shopify_products(cfg, refresh):
    cache = os.path.join(OUT, "shopify_cache.json")
    shop, token = cfg["store_url"], cfg.get("admin_api_token", "")
    if not refresh and os.path.exists(cache) and time.time() - os.path.getmtime(cache) < 12 * 3600:
        try:
            cached = json.load(open(cache, encoding="utf-8"))
        except ValueError:
            cached = None
        if isinstance(cached, dict) and cached.get("store") == shop:    # only reuse this store's products
            print("Shopify: using cache from the last 12 hours (use --refresh-shopify to re-pull)")
            return cached["rows"]
    if not token:
        body = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": cfg["client_id"],
                                       "client_secret": cfg["client_secret"]}).encode()
        token = json.loads(http(f"https://{shop}/admin/oauth/access_token", body,
                                {"Content-Type": "application/x-www-form-urlencoded"}))["access_token"]
    q = """query($after:String){ products(first:250, after:$after){ pageInfo{hasNextPage endCursor}
      nodes{ id title vendor tags status variants(first:100){ nodes{ sku price inventoryQuantity } } } } }"""
    rows, after = [], None
    while True:
        d = json.loads(http(f"https://{shop}/admin/api/{SHOPIFY_API}/graphql.json",
                            json.dumps({"query": q, "variables": {"after": after}}).encode(),
                            {"Content-Type": "application/json", "X-Shopify-Access-Token": token}))
        if "errors" in d:
            sys.exit(f"Shopify query error: {d['errors']}")
        p = d["data"]["products"]
        for n in p["nodes"]:
            for v in n["variants"]["nodes"]:
                rows.append({"product_id": n["id"], "title": n["title"], "vendor": n["vendor"], "tags": n["tags"], "status": n["status"],
                             "sku": (v["sku"] or "").strip(), "price": float(v["price"] or 0),
                             "qty": v.get("inventoryQuantity")})
        print(f"  Shopify: {len(rows)} variants...", end="\r")
        if not p["pageInfo"]["hasNextPage"]:
            break
        after = p["pageInfo"]["endCursor"]
    print()
    json.dump({"store": shop, "rows": rows}, open(cache, "w", encoding="utf-8"))
    return rows


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


class ShopifyIndex:
    def __init__(self, rows):
        self.by_sku, self.by_title = {}, {}
        for r in rows:
            if r["sku"]:
                self.by_sku.setdefault(r["sku"], []).append(r)
            self.by_title.setdefault(norm(r["title"]), []).append(r)

    def match(self, sku, title, ebay_price):
        if sku and sku in self.by_sku:
            return self.by_sku[sku][0], "SKU"
        cands = self.by_title.get(norm(title), []) if len(norm(title)) >= 15 else []
        active = [c for c in cands if c["status"] == "ACTIVE"] or cands
        if not active:
            return None, "not found"
        products = {c.get("product_id") or (c["title"], c["vendor"], tuple(c["tags"]), c["status"]) for c in active}
        if len(products) > 1:                       # different products share the title: don't guess by price
            return None, f"title (ambiguous: {len(products)} products)"
        if ebay_price:
            def score(c):
                if not c["price"]:
                    return 9
                r = ebay_price / c["price"]
                return min(abs(r - 1), abs(r - 1 - CONSIGNMENT_MARKUP))
            active = sorted(active, key=score)
        return active[0], "title"


def price_rule(ebay_price, shop):
    """Returns Operator, Input, Rounding, Result, Basis."""
    if not shop or not shop["price"] or not ebay_price:
        return "", "", "", "", "unknown (no Shopify match)"
    sp, r = shop["price"], ebay_price / shop["price"]
    tags = [x.lower() for x in shop["tags"]]
    if "consignment" in tags:
        if abs(r - 1 - CONSIGNMENT_MARKUP) < PRICE_TOL:
            return "% increase", "5", "None", f"{sp * (1 + CONSIGNMENT_MARKUP):.2f}", "consignment tag"
        return "% increase", "5", "None", f"{sp * (1 + CONSIGNMENT_MARKUP):.2f}", \
            f"MISMATCH: eBay {ebay_price:.2f} vs Shopify {sp:.2f} (x{r:.3f}); consignment tag expects +5%"
    if abs(r - 1) < PRICE_TOL:
        return "Web price", "", "None", f"{sp:.2f}", "inferred: eBay = Shopify"
    if abs(r - 1 - CONSIGNMENT_MARKUP) < PRICE_TOL:
        return "% increase", "5", "None", f"{sp * (1 + CONSIGNMENT_MARKUP):.2f}", "inferred: eBay = Shopify +5%"
    return "?", "", "", "", f"MISMATCH: eBay {ebay_price:.2f} vs Shopify {sp:.2f} (x{r:.3f})"


# ------------------------------------------------------------------ audit
CARD_TITLE = re.compile(r"\b(PSA|BGS|CGC|SGC|Beckett|Pokemon|Pokémon|Topps|Panini|Bowman|Prizm|MTG|Magic)\b", re.I)
SLAB_TITLE = re.compile(r"\b(PSA|BGS|CGC|SGC|TAG)\s*(\d|10|Authentic)", re.I)


def audit(d, rows):
    """Problems that can stop a buyer checking out (or make the listing change on the next sync)."""
    issues, iid, card = [], d["item_id"], d["category_id"] in CARD_CATEGORIES
    add = lambda sev, issue, fix: issues.append({"Item Number": iid, "Title": d["title"], "Severity": sev,
                                                 "Issue": issue, "Suggested fix": fix})
    if d["variations"]:
        names = {n for v in d["variations"] for n in v["specifics"]}
        if card and names & {"Condition", "Card Condition"}:
            add("High", f"Variations use {', '.join(sorted(names))} in a card category",
                "List each condition separately, or change the sync app's variation option")
        live = [v for v in d["variations"] if v["qty"] > 0]
        if not live:
            add("High", "Every variation has 0 available", "Fix stock in Shopify or end the listing")
        elif len(live) < len(d["variations"]):
            add("Medium", f"{len(d['variations']) - len(live)} of {len(d['variations'])} variations have 0 available",
                "Remove empty variations so buyers can't pick them")
    elif d["qty"] <= 0:
        add("High", "Available quantity is 0", "Fix stock in Shopify")
    if "Calculated" in (d["ship_type"] or ""):
        if not d["weight_oz"]:
            add("High", "Calculated shipping but no package weight",
                "Add package weight (in Shopify product weight or the listing) so eBay can price shipping")
        elif d["weight_oz"] > 240:
            add("Low", f"Calculated shipping with package weight {d['weight_oz']:g} oz (over 15 lb)",
                "Check the weight; a wrong weight can make shipping too expensive or unavailable")
        if not all(d["dims_in"]):
            add("Low", "Calculated shipping but package dimensions missing",
                "Add package length/width/depth so carriers can quote")
    if not d["sku"] and not any(v["sku"] for v in d["variations"]):
        add("High", "No SKU on the listing or its variations", "Give the Shopify variant a unique SKU and relink in the sync app")
    for r in rows:
        if r["Shopify Match"] == "not found":
            add("Medium", f"No matching Shopify product (SKU '{r['SKU']}')", "Link the listing to its Shopify product")
        if r["Shopify Match"].startswith("title (ambiguous"):
            add("Medium", f"Shopify match is {r['Shopify Match']}; price/qty not checked (SKU '{r['SKU']}')",
                "Review: give the listing the Shopify variant's SKU so it matches exactly")
        if r["Price Rule Basis"].startswith("MISMATCH"):
            add("Medium", f"Price follows neither rule: {r['Price Rule Basis']}", "Correct the price rule in the sync app")
        sq = r["Shopify Qty"]
        if isinstance(sq, int) and r["Available Qty"] != "" and sq != r["Available Qty"] and r["Shopify Match"] == "SKU":
            add("Medium", f"eBay qty {r['Available Qty']} vs Shopify qty {sq} ({r['SKU']})", "Check the sync app's inventory sync")
    if card:
        if d["condition_id"] not in (GRADED_ID, UNGRADED_ID):
            add("High", f"Condition '{d['condition']}' (ID {d['condition_id']}) in a card category; only Graded/Ungraded are valid",
                "Map Shopify condition to Graded or Ungraded")
        ds = d["descriptors"]
        if d["condition_id"] == GRADED_ID:
            for k in ("Professional Grader", "Grade"):
                if not ds.get(k):
                    add("High", f"Graded but missing {k}", f"Add {k} in Shopify so it syncs")
            if not ds.get("Certification Number"):
                add("Low", "Graded but missing Certification Number", "Add the cert number in Shopify")
            sp = {k.lower(): v for k, v in d["specifics"].items()}
            if sp.get("card condition"):
                add("Medium", f"Graded slab also carries item specific Card Condition='{sp['card condition']}'",
                    "Remove Card Condition from graded products in Shopify / the sync mapping")
            if sp.get("graded", "").lower() == "no":
                add("Medium", "Condition is Graded but item specific Graded=No", "Set Graded=Yes in Shopify")
            if sp.get("grade") and ds.get("Grade") and sp["grade"].strip() != ds["Grade"].strip():
                add("Medium", f"Item specific Grade '{sp['grade']}' differs from condition Grade '{ds['Grade']}'",
                    "Make the grade the same in both places")
            g = sp.get("professional grader", "")
            abbr = re.search(r"\(([^)]+)\)", ds.get("Professional Grader", ""))
            if g and abbr and abbr.group(1).lower() not in g.lower() \
                    and g.lower() not in ds.get("Professional Grader", "").lower():
                add("Low", f"Item specific Professional Grader '{g}' vs condition '{ds['Professional Grader']}'",
                    "Use one spelling of the grader name")
        if d["condition_id"] == UNGRADED_ID:
            if not ds.get("Card Condition"):
                add("High", "Ungraded but missing Card Condition", "Set Card Condition")
            if SLAB_TITLE.search(d["title"]):
                add("Medium", "Title looks like a graded slab but condition is Ungraded", "Set condition to Graded with grader/grade")
    elif CARD_TITLE.search(d["title"]) and d["category_id"] not in CARD_CATEGORIES and "Helmet" not in d["category"] \
            and "Jersey" not in d["category"]:
        add("Medium", f"Looks like a card but listed in '{d['category']}'", "Fix the category mapping in the sync app")
    return issues


# ------------------------------------------------------------------ report rows
def build_rows(d, idx):
    sp = {k.lower(): v for k, v in d["specifics"].items()}
    base = {"Item Number": d["item_id"], "Title": d["title"], "Category": d["category"], "Category ID": d["category_id"],
            "Shipping Cost type": d["ship_type"] + (f" (policy: {d['ship_policy']})" if d["ship_policy"] else ""),
            "Service": d["services"], "eBay Condition": d["condition"],
            "Package Weight (oz)": d["weight_oz"] or "",
            "Package Size (in)": " x ".join(f"{x:g}" for x in d["dims_in"]) if any(d["dims_in"]) else "",
            "Condition: Card Condition": d["descriptors"].get("Card Condition", ""),
            "Condition: Professional Grader": d["descriptors"].get("Professional Grader", ""),
            "Condition: Grade": d["descriptors"].get("Grade", ""),
            "Certification Number": d["descriptors"].get("Certification Number", "")}
    for c in SPEC_COLS:
        base[f"IS: {c}" if c in ("Grade", "Card Condition", "Professional Grader") else c] = sp.get(c.lower(), "")
    units = d["variations"] or [{"sku": d["sku"], "price": d["price"], "qty": d["qty"], "specifics": {}}]
    rows = []
    for v in units:
        price = float(v["price"] or d["price"] or 0)
        shop, how = idx.match(v["sku"] or d["sku"], d["title"], price) if idx else (None, "skipped")
        op, inp, rnd, res, basis = price_rule(price, shop)
        r = dict(base)
        r.update({"SKU": v["sku"] or d["sku"], "Variation": " | ".join(f"{k}={x}" for k, x in v["specifics"].items()),
                  "Available Qty": v["qty"], "eBay Price": f"{price:.2f}", "Operator": op, "Input": inp,
                  "Rounding": rnd, "Result": res, "Price Rule Basis": basis,
                  "Shopify Price": f"{shop['price']:.2f}" if shop else "", "Shopify Vendor": shop["vendor"] if shop else "",
                  "Shopify Qty": shop["qty"] if shop else "", "Shopify Match": how})
        rows.append(r)
    return rows


def cmp_val(field, v):
    """Value used for change comparison: eBay returns the shipping policy name only sometimes, so ignore it."""
    return re.sub(r" \(policy: .*\)$", "", v) if field == "Shipping Cost type" else v


def row_key(r):
    return f"{r['Item Number']}|{r['SKU']}|{r['Variation']}"


# ------------------------------------------------------------------ main
def open_file(path):
    """Open a finished report in Excel / Numbers / the default app."""
    try:
        if MAC:
            subprocess.run(["open", path], check=False)
        elif sys.platform == "win32":
            os.startfile(path)
        else:
            subprocess.run(["xdg-open", path], check=False)
    except OSError:
        pass


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", help="skip the menu and use this account")
    ap.add_argument("--config", help="path to config.yaml (default: next to this program, then Downloads / Documents)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--refresh-shopify", action="store_true")
    ap.add_argument("--no-shopify", action="store_true")
    a = ap.parse_args(argv)
    os.makedirs(OUT, exist_ok=True)
    a.config = find_config(a.config)
    print(f"Config: {a.config}")
    cfg = read_config(a.config)
    a.account = choose_account(cfg["ebay"], a.account)
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    tag = f"{a.account}_{stamp}"

    idx = None
    if not a.no_shopify:
        idx = ShopifyIndex(shopify_products(cfg["shopify"], a.refresh_shopify))

    eb = Ebay(cfg["ebay"], a.account)
    ids = eb.active_item_ids()
    print(f"eBay: {len(ids)} active listings")
    if a.limit:
        ids = ids[:a.limit]

    report, audits, errors, snap, everything = [], [], [], {}, []
    for n, iid in enumerate(ids, 1):
        print(f"  GetItem {n}/{len(ids)}  {iid}", end="\r")
        try:
            it, errs = eb.get_item(iid)
            for sev, code, msg in errs:
                errors.append(f"{iid}\t{sev}\t{code}\t{msg}")
            d = parse_item(it)
            everything.append(all_fields(it))
        except Exception as e:
            errors.append(f"{iid}\tFailure\t\t{e}")
            continue
        rows = build_rows(d, idx)
        issues = audit(d, rows)
        for r in rows:
            r["Issues"] = len(issues)
        report += rows
        audits += issues
        for r in rows:
            snap[row_key(r)] = {c: str(r.get(c, "")) for c in COLUMNS if c not in TAIL}
    print()

    # ---- change comparison with the previous run of this account
    prev = sorted(p for p in glob.glob(os.path.join(OUT, "snapshot_*.json"))     # this account only, not
                  if re.fullmatch(re.escape(f"snapshot_{a.account}_") + r"\d{4}-\d{2}-\d{2}_\d{4}(\d{2})?\.json",
                                  os.path.basename(p)))                         # accounts sharing a prefix
    changes = []
    if prev:
        old = json.load(open(prev[-1], encoding="utf-8"))
        for k, cur in snap.items():
            if k not in old:
                changes.append({"Key": k, "Field": "(listing)", "Old": "", "New": "new since last run"}); continue
            for f, v in cur.items():
                if cmp_val(f, old[k].get(f, "")) != cmp_val(f, v):
                    changes.append({"Key": k, "Field": f, "Old": old[k].get(f, ""), "New": v})
        for k in old:
            if k not in snap and not a.limit:
                changes.append({"Key": k, "Field": "(listing)", "Old": "present", "New": "gone since last run"})
    changed = {c["Key"] for c in changes}
    for r in report:
        r["Changed Since Last Run"] = ("yes" if row_key(r) in changed else "no") if prev else "first run"

    def write(name, rows, cols):
        p = os.path.join(OUT, f"{name}_{tag}.csv")
        with open(p, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
        return p

    # requested fields only, clean headers (duplicates labelled by section)
    req_groups = [("Shipping", SHIPPING[:2]), ("Price", PRICE[:3] + ["Result"] if "Result" not in PRICE[:3] else PRICE),
                  ("Item Specifics", [_is(c) for c in SPECIFICS]), ("Recommended", RECOMMENDED),
                  ("Optional", [_is(c) for c in OPTIONAL]), ("Condition", CONDITION)]
    req_cols, req_heads = ["Item Number", "Title", "Variation"], ["Item Number", "Title", "Variation"]
    dupes = {"Grade", "Card Condition", "Professional Grader"}
    for g, cols in req_groups:
        for c in cols:
            if c == "Rounding":
                continue
            name = display(c)
            req_cols.append(c)
            req_heads.append(f"{name} ({g})" if name in dupes else name)
    preq = os.path.join(OUT, f"requested_fields_{tag}.csv")
    with open(preq, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(req_heads)
        for r in report:
            w.writerow([r.get(c, "") for c in req_cols])
    print(f"REQUESTED FIELDS CSV: {preq}")
    p1 = write("ebay_report", report, COLUMNS)
    sev = {"High": 0, "Medium": 1, "Low": 2}
    p2 = write("audit", sorted(audits, key=lambda x: sev[x["Severity"]]), ["Severity", "Item Number", "Title", "Issue", "Suggested fix"])
    p3 = write("changes", changes, ["Key", "Field", "Old", "New"])
    if not a.limit:
        json.dump(snap, open(os.path.join(OUT, f"snapshot_{tag}.json"), "w", encoding="utf-8"))
    if errors:
        open(os.path.join(OUT, f"errors_{tag}.log"), "w", encoding="utf-8").write("\n".join(errors))

    # ---- Excel workbook: All Fields, Requested Fields (grouped), Problems, Changes
    group_row = []
    for g, cols in GROUPS:
        group_row += [g] + [""] * (len(cols) - 1)
    wide = {"Title": 50, "Variation": 30, "Category": 28, "Service": 30, "Shipping Cost type": 28,
            "Price Rule Basis": 28, "Condition: Professional Grader": 30}
    NUMERIC = {"Available Qty", "eBay Price", "Result", "Shopify Price", "Shopify Qty", "Issues"}

    def cell(r, c):
        v = r.get(c, "")
        if c in NUMERIC and v not in ("", None):
            try:
                return float(v) if "." in str(v) else int(v)
            except ValueError:
                return v
        return v
    listing_rows = [group_row, [display(c) for c in COLUMNS]] + [[cell(r, c) for c in COLUMNS] for r in report]
    acols = ["Severity", "Item Number", "Title", "Issue", "Suggested fix"]
    ccols = ["Key", "Field", "Old", "New"]
    xlsx = os.path.join(OUT, f"eBay_Listings_Report_{tag}.xlsx")
    all_cols = order_all_columns(everything)
    all_rows = [[display_all(c) for c in all_cols]] + [[r.get(c, "") for c in all_cols] for r in everything]
    write_xlsx(xlsx, [
        ("All Fields", all_rows, 1, [50 if c in ("Title", "Variations: Detail") else 16 for c in all_cols]),
        ("Requested Fields", listing_rows, 2, [wide.get(c, 14) for c in COLUMNS]),
        ("Problems", [acols] + [[x[c] for c in acols] for x in sorted(audits, key=lambda x: sev[x["Severity"]])], 1,
         [10, 14, 50, 60, 55]),
        ("Changes", [ccols] + [[x[c] for c in ccols] for x in changes], 1, [45, 28, 30, 30]),
    ])
    print(f"\nEXCEL REPORT: {xlsx}")

    cnt = {}
    for x in audits:
        cnt[x["Severity"]] = cnt.get(x["Severity"], 0) + 1
    print(f"\nReport rows: {len(report)}  ->  {p1}")
    print(f"Audit issues: {len(audits)} {cnt}  ->  {p2}")
    print(f"Changes since last run: {len(changes) if prev else 'first run'}  ->  {p3}")
    if errors:
        print(f"API errors/warnings: {len(errors)} (see errors_{tag}.log)")
    top = {}
    for x in audits:
        k = re.sub(r"\d+", "#", x["Issue"].split(":")[0])
        top[k] = top.get(k, 0) + 1
    print("\nTop issues:")
    for k, v in sorted(top.items(), key=lambda kv: -kv[1])[:10]:
        print(f"  {v:5}  {k}")
    return xlsx


if __name__ == "__main__":
    main()
