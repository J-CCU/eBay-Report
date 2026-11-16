# CCU eBay Reports

Read-only reporting tools for an eBay seller account. They pull every active listing through the eBay
Trading API, match each one to the Shopify store's products, and write CSV / Excel reports of listing
fields, price rules and problems that can stop a buyer checking out. They are meant for staff who manage
eBay listings that are synced from a Shopify store.

Nothing is ever changed on eBay or Shopify: the tools only read.

## Quick start

A prebuilt program isn't included right now; build one from source (see [Building the app](#building-the-app))
or run the script with Python.

1. Create `config.yaml` with your eBay and Shopify credentials (see [Configuration](#configuration-configyaml))
   and put it next to the program or in `~/Downloads`.
2. Run `python3 ccu_ebay_app.py`, or the program you built (`CCU eBay Reports.exe` on Windows,
   `CCU eBay Reports` on Mac; see [Building the app](#building-the-app)).
3. Press Enter to accept the `config.yaml` it found, then pick the eBay account if asked.
4. The requested-fields CSV opens when done. It is saved in `ccu_report_output/`.

For the full report, audit and Excel workbook, run `python3 ccu_ebay_report.py` instead.

## What is in this repo

| File | Purpose |
| --- | --- |
| `ccu_ebay_app.py` | Entry point for the packaged program. Picks `config.yaml`, runs the requested-fields report and opens the CSV. |
| `requested_fields_report.py` | Builds the requested-fields CSV (only the requested columns, in the requested order). |
| `ccu_ebay_report.py` | Full listing report and buyer-block audit (CSVs, Excel workbook, change tracking). Also the shared eBay/Shopify connection code used by the other two scripts. |
| `Build Mac eBay App.command` | Builds the Mac program from the three `.py` files. |
| `CCU eBay Reports - Mac build kit.zip` | The same three scripts plus the build script, zipped for copying to a Mac. |

## Features

- **Requested-fields CSV** (`ccu_ebay_app.py` / `requested_fields_report.py`): one row per listing
  (one per variation for multi-variation listings) with listing title, shipping, price rule, item
  specifics and condition fields.
- **Full report and audit** (`ccu_ebay_report.py`):
  - every active listing, with Shopify price, vendor, quantity and how it was matched (exact SKU first; otherwise
    the full normalized title, at least 15 characters, preferring active Shopify products; if several different
    Shopify products share that title the match is shown as `title (ambiguous: N products)` and flagged in the
    audit for review instead of being guessed)
  - price-rule detection: "Web price" (eBay = Shopify), "% increase 5" (eBay = Shopify + 5%), otherwise flagged
    as a mismatch; a product tagged `consignment` must be priced at Shopify + 5% or it is flagged as a mismatch
  - audit of problems that can block checkout: zero stock, empty variations, condition used as a variation
    in a card category, calculated shipping with no weight or dimensions (or over 15 lb), missing SKU, no
    Shopify match, price or quantity mismatch, wrong condition for a trading-card category, graded cards
    missing grader / grade / cert number, ungraded cards missing Card Condition, slab-like titles listed as
    Ungraded, conflicting item specifics, card-like titles in non-card categories
  - change comparison against the previous run for the same account (the shipping policy name shown after
    "Shipping Cost type" is ignored, because eBay only returns it some of the time)
  - Excel workbook with All Fields, Requested Fields, Problems and Changes sheets (written with the
    standard library, no Excel needed to create it)
- Multiple eBay seller accounts in one `config.yaml`, with a numbered menu to choose one.
- Safety check: before pulling data, it confirms the eBay token signs in as the expected eBay user and
  stops if it does not, so data from different accounts is never mixed.
- Shopify product data is cached for 12 hours.

## Requirements

- Built program: nothing to install to run it. Build it yourself (see [Building the app](#building-the-app)).
  The Mac program only runs on Macs with the same chip type (Apple silicon or Intel) as the Mac that
  built it.
- Windows or macOS. On Linux the scripts run from source; the finished CSV is opened with `xdg-open`.
- From source: Python 3.10 or newer. Only the standard library is used (`tkinter`, for the file picker in
  `ccu_ebay_app.py`, is optional; without it you type the path). On a Mac with Python from
  python.org, install `certifi` (`python3 -m pip install certifi`) or run Python's
  "Install Certificates.command"; otherwise HTTPS connections may fail certificate checks.
- Internet access to `api.ebay.com` and the Shopify store's `*.myshopify.com` domain.
- A `config.yaml` with eBay and Shopify credentials (see [Configuration](#configuration-configyaml)).

## How to run

### Built program

1. Build the program (see [Building the app](#building-the-app)), then put `config.yaml` next to it (or in your Downloads or Documents folder).
2. Double-click `CCU eBay Reports.exe` (Windows) or `CCU eBay Reports` (Mac, opens in Terminal).
   On a Mac that did not build it, the first time: right-click it > Open > Open (it is not signed).
3. It shows which `config.yaml` it will use. Press Enter to use it, or type `C` and Enter to choose a
   different one in a file picker (or type/drag the path if no picker is available).
4. If `config.yaml` has more than one eBay account, type the number of the account.
5. When finished, the CSV opens automatically. Press Enter to close the window.

### From source

Requested-fields CSV (same as the built program):

```
py ccu_ebay_app.py                 # Windows
python3 ccu_ebay_app.py            # Mac
```

Or run the report script directly:

```
py requested_fields_report.py [--account NAME] [--config PATH] [--with-id] [--refresh-shopify]
python3 requested_fields_report.py [--account NAME] [--config PATH] [--with-id] [--refresh-shopify]
```

Full report and audit:

```
py ccu_ebay_report.py [--account NAME] [--config PATH] [--limit N] [--refresh-shopify] [--no-shopify]
python3 ccu_ebay_report.py [--account NAME] [--config PATH] [--limit N] [--refresh-shopify] [--no-shopify]
```

| Option | Scripts | Meaning |
| --- | --- | --- |
| `--account NAME` | all | Use this account and skip the menu. |
| `--config PATH` | all | Use this `config.yaml` instead of searching for one. |
| `--with-id` | requested_fields_report | Add `Item Number` as the first column. |
| `--refresh-shopify` | all | Ignore the cached Shopify pull and download products again. |
| `--limit N` | ccu_ebay_report | Only process the first N listings (quick test). No snapshot is saved and removed listings are not reported. |
| `--no-shopify` | ccu_ebay_report | Skip Shopify entirely (price-rule and Shopify columns are left blank / "skipped"). |

`ccu_ebay_app.py` passes any extra arguments through to `requested_fields_report.py`.

## Configuration: config.yaml

The tools read a `config.yaml` that has an `ebay:` section and a `shopify:` section. A small built-in
YAML reader is used (no PyYAML needed), so keep to this format:

- `ebay:` and `shopify:` start at the beginning of the line; nested keys are indented (two spaces).
- Wrap values in double quotes. Single quotes are not removed and become part of the value.
- A ` #` (space, then `#`) after a value starts a comment. A value that itself contains ` #` must be
  wrapped in quotes.

### Where config.yaml is looked for

If `--config` is not given, the first `config.yaml` or `config.yml` containing an `ebay:` line is used,
searched in this order:

1. The program folder (next to the `.py` files, the `.exe`, or the folder holding the Mac program).
2. `~/Downloads`
3. `~/Documents`
4. `~/Documents/Commerce Intel`

The packaged program (`ccu_ebay_app.py`) remembers the file you chose in `ccu_ebay_settings.json` next to
the program. That file stores only the path to `config.yaml`, never its contents. `config.yaml` is never
built into the program.

### Layout

Use placeholders like these; never commit a real `config.yaml`.

```yaml
ebay:
  app_id: "YOUR_EBAY_APP_ID"
  dev_id: "YOUR_EBAY_DEV_ID"
  cert_id: "YOUR_EBAY_CERT_ID"
  refresh_token: "YOUR_REFRESH_TOKEN"     # optional: default account only (see below)
  user_token: "YOUR_AUTHNAUTH_TOKEN"      # optional: default account only (see below)
  seller_accounts:
    example-seller:
      refresh_token: "SELLER_REFRESH_TOKEN"
      user_token: "SELLER_AUTHNAUTH_TOKEN"
      ebay_user_id: "example-seller"      # optional, defaults to the account name

shopify:
  store_url: "your-store.myshopify.com"
  admin_api_token: "YOUR_ADMIN_API_TOKEN"
  # or, instead of admin_api_token:
  client_id: "YOUR_CLIENT_ID"
  client_secret: "YOUR_CLIENT_SECRET"
```

### eBay keys

| Key | Purpose |
| --- | --- |
| `app_id`, `dev_id`, `cert_id` | eBay developer keyset (from the eBay Developers Program, Production keys). Sent as Trading API headers; `app_id` + `cert_id` are also used to exchange a refresh token for an OAuth access token. |
| `refresh_token` | OAuth refresh token for a seller account. Preferred: exchanged for an access token on each run. |
| `user_token` | Auth'n'Auth token. Used if there is no refresh token or the OAuth refresh fails. |
| `seller_accounts.<name>` | One block per seller account. `<name>` is what appears in the account menu and in output file names. Each needs `refresh_token` and/or `user_token`. |
| `seller_accounts.<name>.ebay_user_id` | The eBay user ID the token must sign in as. Defaults to `<name>`. If the token signs in as someone else, the run stops. |

Top-level `refresh_token` / `user_token` are only used by one built-in default account name defined as
`DEFAULT_ACCOUNT` in `ccu_ebay_report.py`; that account appears in the menu only when top-level tokens are
present. Every other account must be listed under `seller_accounts` and never falls back to the
top-level tokens.

The tokens need read access to the seller's listings (Trading API `GetUser`, `GetMyeBaySelling`,
`GetItem`).

### Shopify keys

| Key | Purpose |
| --- | --- |
| `store_url` | The store's `*.myshopify.com` domain. |
| `admin_api_token` | Admin API access token with permission to read products (variant `inventoryQuantity` may also need inventory read access). Used directly if present. |
| `client_id`, `client_secret` | Used if there is no `admin_api_token`: exchanged for an access token via the client-credentials grant. |

The `shopify:` section is required, except for `ccu_ebay_report.py --no-shopify`.

### Other settings (in code)

These are constants near the top of `ccu_ebay_report.py`, not config keys:

| Constant | Default | Purpose |
| --- | --- | --- |
| `SHOPIFY_API` | `2026-07` | Shopify Admin GraphQL API version. |
| `COMPAT` | `1349` | eBay Trading API compatibility level. |
| `CONSIGNMENT_MARKUP` | `0.05` | Markup for the "% increase" price rule. |
| `PRICE_TOL` | `0.006` | Ratio tolerance when matching a price rule. |
| `CARD_CATEGORIES` | `183454, 261328, 183050` | eBay category IDs treated as trading-card singles in the audit. |

No environment variables are used.

## Outputs

All files go to a `ccu_report_output` folder in the program folder. For the packaged program, if its
folder cannot be written to, `~/Downloads` is used instead. `<account>` is the account name, `<stamp>` is
`YYYY-MM-DD_HHMMSS` (older runs used `YYYY-MM-DD_HHMM`; their snapshots are still read). CSVs are UTF-8 with BOM so Excel opens them correctly.

### requested_fields_report.py / the packaged program

`requested_fields_<account>_<stamp>.csv`, one row per listing (per variation), columns in this order
(some names repeat on purpose; the first set is from item specifics, the second from eBay condition
descriptors):

`Listing Name`, `Shipping Cost type`, `Service`, `Operator`, `Input`, `Result`, `Brand`, `Franchise`,
`Game`, `Grade`, `Graded`, `Language`, `Manufacturer`, `Set`, `Sport`, `Autographed`, `Card Name`,
`Card Number`, `Card Type`, `Character`, `Features`, `League`, `Player/Athlete`, `Signed By`, `Team`,
`Finish`, `Rarity`, `Card Condition`, `HP`, `Professional Grader`, `Stage`, `Year Manufactured`,
`eBay Condition`, `Card Condition`, `Professional Grader`, `Grade`, `Certification Number`.

With `--with-id`, `Item Number` is added first.

### ccu_ebay_report.py

| File | Contents |
| --- | --- |
| `requested_fields_<account>_<stamp>.csv` | Item Number, Title, Variation, then the requested fields; repeated names are labelled with their section, e.g. `Grade (Item Specifics)`, `Grade (Condition)`. |
| `ebay_report_<account>_<stamp>.csv` | Requested fields plus working columns: SKU, Category, Available Qty, eBay Price, Package Weight (oz), Package Size (in), Rounding, Category ID, Price Rule Basis, Shopify Price / Vendor / Qty / Match, Issues (number of audit problems for the listing), Changed Since Last Run. Repeated field names carry a prefix here: `IS: Grade` (item specific) and `Condition: Grade` (condition descriptor). |
| `audit_<account>_<stamp>.csv` | One row per problem: Severity (High / Medium / Low), Item Number, Title, Issue, Suggested fix. Sorted by severity. |
| `changes_<account>_<stamp>.csv` | Key (item / SKU / variation), Field, Old, New, compared with the latest previous snapshot for that account. |
| `snapshot_<account>_<stamp>.json` | Values used for the next change comparison (not written with `--limit`). |
| `errors_<account>_<stamp>.log` | eBay API errors and warnings, if any. |
| `eBay_Listings_Report_<account>_<stamp>.xlsx` | Sheets: All Fields (every field eBay returns per listing, including item specifics, photos, variations, description text, listing URL), Requested Fields (grouped headings), Problems, Changes. |
| `shopify_cache.json` | Cached Shopify products (reused for 12 hours). Shared by all accounts; it remembers which store it came from and is downloaded again when the config points at a different store. |

The console also prints counts and the top 10 issue types.

## Building the app

### Mac

1. Put `Build Mac eBay App.command` in the same folder as `ccu_ebay_app.py`, `ccu_ebay_report.py` and
   `requested_fields_report.py` (or unzip `CCU eBay Reports - Mac build kit.zip`).
2. Double-click `Build Mac eBay App.command`, or run `bash "Build Mac eBay App.command"`.

The script:

- finds Python 3.10+ (python.org framework install, Homebrew, `/usr/local/bin`, or `python3` on PATH)
- creates a throwaway virtual environment and installs PyInstaller and certifi from PyPI
- runs PyInstaller (`--onefile --console`, certifi as a hidden import) on `ccu_ebay_app.py`
- puts the single-file program `CCU eBay Reports` next to the scripts and reveals it in Finder

It takes 1 to 2 minutes. `config.yaml` is not included in the build.

### Windows

The Windows build script referenced in the source (`Build Windows eBay App.bat`) is not in this repo. An equivalent manual build:

```
py -m pip install pyinstaller
py -m PyInstaller --noconfirm --onefile --console --name "CCU eBay Reports" ccu_ebay_app.py
```

The program appears in `dist\`.

## Troubleshooting

| Message / symptom | Fix |
| --- | --- |
| `No config.yaml with an 'ebay:' section found` | Put `config.yaml` next to the program or in Downloads / Documents, or pass `--config PATH`. The file must contain a line starting `ebay:`. |
| `No eBay accounts in this config.yaml` | Add tokens under `ebay:` (default account) or under `seller_accounts`. |
| `eBay: no account '<name>' in config.yaml` | `--account` value is not one of the configured accounts. |
| `eBay: OAuth refresh failed ...; falling back to user_token` | The refresh token or app/cert IDs are wrong or expired. It continues with `user_token` if present. |
| `eBay: no usable token for '<name>'` | Neither token works for that account. Get a new token for that eBay user and put it in `config.yaml`. (The `Connect eBay Account.bat` named in this message is not in this repo.) |
| `the token for '<name>' signs in as '<x>', not '<y>'` | The token belongs to another eBay user. Fix the token or set `ebay_user_id`. |
| `HTTP 401/403` from Shopify, or `Shopify query error` | Check `store_url` and the Shopify token / client credentials, and that the app can read products. |
| SSL / certificate errors on a Mac | Install `certifi`, or run "Install Certificates.command" from the Python folder in Applications. The built Mac program bundles certifi. |
| Mac says the program cannot be opened | Right-click > Open > Open the first time (it is not signed). |
| Mac program will not start on another Mac | It was built for a different chip type. Rebuild on that Mac. |
| Shopify data looks out of date | Run with `--refresh-shopify` (cache lasts 12 hours). |
| The CSV is written but does not open (e.g. on Linux without `xdg-open`) | The report was written; only opening it failed. Open the CSV from `ccu_report_output/` yourself. |
| `Listings that could not be read: N` | Those `GetItem` calls failed; see the console (or `errors_*.log` for the full report). |

If the packaged program shows "Something went wrong", copy the error text (never a token or password)
and send it to whoever maintains the tool.

## File guide

| Path | Created by | Notes |
| --- | --- | --- |
| `config.yaml` | you | Credentials. Keep it out of git and out of builds. |
| `ccu_ebay_settings.json` | packaged program | Remembered path to `config.yaml`. |
| `ccu_report_output/` | all scripts | Reports, snapshots, logs, Shopify cache. |
| `CCU eBay Reports` / `CCU eBay Reports.exe` | build | Single-file program. |
